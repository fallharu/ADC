"""Continuous full-video tracking for arbitrary inputs, with append-only app runs.

Raw boxes stay in the application DB. Only metadata and aggregate counts are
written to the experiment folder. Calibration is per source; no profile is
inferred from filenames. This runner measures tracking coverage, not accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import fnmatch
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.m4v', '.webm', '.mpg', '.mpeg', '.wmv'}
LABELS = {1: 'bicycle', 2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
DEFAULT_EXCLUDES = ['*bbox*', '*bike_clips*', '*annotated*', '*tracked*']
INSERT_BOX = ('INSERT INTO Detection(run_id,video_id,class_id,frame_num,x1,y1,x2,y2,'
              'model_name,class_name,track_id,confidence,group_id,measure_x,measure_y) '
              'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def discover(folders, recursive=True, includes=None, excludes=None):
    """Deterministic, deduplicated discovery; patterns match relative paths/names."""
    includes = includes or ['*']
    excludes = DEFAULT_EXCLUDES if excludes is None else excludes
    videos = {}
    for folder in folders:
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise NotADirectoryError(folder)
        for path in folder.rglob('*') if recursive else folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            names = [path.name.lower(), path.relative_to(folder).as_posix().lower()]
            matches = lambda patterns: any(fnmatch.fnmatchcase(n, p.lower()) for n in names for p in patterns)
            if matches(includes) and not matches(excludes):
                videos[path_key(path)] = path.resolve()
    return [videos[key] for key in sorted(videos)]


def sources_from_paths(paths):
    unique = {path_key(path): Path(path).resolve() for path in paths}
    return [dict(source_id='video-' + hashlib.sha256(key.encode()).hexdigest()[:12], path=str(path))
            for key, path in sorted(unique.items())]


def load_sources(manifest):
    path = Path(manifest).resolve()
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or not isinstance(value.get('sources'), list):
        raise ValueError('manifest requires a sources list')
    records = []
    ids, paths = set(), set()
    for source in value['sources']:
        source = dict(source)
        sid = source.get('source_id', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', sid) or sid in ids:
            raise ValueError('source IDs must be unique safe identifiers')
        video = Path(source['path']).expanduser()
        video = (path.parent / video).resolve() if not video.is_absolute() else video.resolve()
        if path_key(video) in paths:
            raise ValueError('duplicate video path in manifest')
        if video.suffix.lower() not in EXTENSIONS:
            raise ValueError('unsupported video extension')
        profile = source.get('calibration_profile')
        if profile and (not isinstance(profile, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', profile)):
            raise ValueError('invalid calibration profile identifier')
        source['path'] = str(video)
        ids.add(sid); paths.add(path_key(video)); records.append(source)
    return records


def probe_video(path):
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError('video_open_failed')
        props = dict(reported_frames=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
                     fps=float(capture.get(cv2.CAP_PROP_FPS)),
                     width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                     height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if not math.isfinite(props['fps']) or props['fps'] <= 0 or min(props['width'], props['height']) <= 0:
            raise ValueError('invalid_video_metadata')
        return props
    finally:
        capture.release()


def signature(source, props, settings, model_hash):
    """Reuse requires identical content, metadata, model, parameters and runner."""
    value = dict(source_sha256=sha(source['path']), metadata=props, settings=settings,
                 model_sha256=model_hash, runner_sha256=sha(__file__),
                 road_type=source.get('road_type'), collection_year=source.get('collection_year'),
                 calibration_profile=source.get('calibration_profile'))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(), value


def reusable(record, fingerprint, conn):
    if not record or record.get('status') != 'completed' or record.get('fingerprint') != fingerprint:
        return False
    run = conn.execute('SELECT status,total_detections FROM ProcessLog WHERE run_id=?',
                       (record.get('db_run_id'),)).fetchone()
    rows = conn.execute('SELECT COUNT(*) FROM Detection WHERE run_id=?', (record.get('db_run_id'),)).fetchone()[0]
    return bool(run and run[0] == 'completed' and run[1] == rows == record.get('detection_rows'))


def create_db_run(conn, source, props, output):
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    existing = conn.execute('SELECT video_id FROM Video WHERE source_path=?', (source['path'],)).fetchone()
    vid = existing[0] if existing else conn.execute(
        'INSERT INTO Video(filename,upload_datetime,duration,fps,source_path,road_type,collection_year) VALUES(?,?,?,?,?,?,?)',
        (Path(source['path']).name, stamp, props['reported_frames'] / props['fps'], props['fps'], source['path'],
         source.get('road_type'), source.get('collection_year'))).lastrowid
    rid = conn.execute(
        'INSERT INTO ProcessLog(video_id,base_video_id,process_start,output_folder,folder_alias,status,calibration_profile) VALUES(?,?,?,?,?,?,?)',
        (vid, vid, stamp, str(output), 'multi-video-full-yolo', 'processing', source.get('calibration_profile'))).lastrowid
    conn.commit()
    return vid, rid


def infer(source, props, settings, model_path, conn, run_dir, fingerprint, provenance, model_factory=None):
    """Construct a new model per video: never carry tracker state across inputs."""
    sid = source['source_id']
    output = ROOT / 'output/full_video_yolo' / run_dir.name / sid
    output.mkdir(parents=True, exist_ok=True)
    vid, rid = create_db_run(conn, source, props, output)
    record = dict(source_id=sid, db_run_id=rid, db_video_id=vid, **props,
                  fingerprint=fingerprint, provenance=provenance, status='running',
                  processed_frames=0, detection_rows=0, missing_track_id_rows=0,
                  accuracy_status='unverified', calibration_profile=source.get('calibration_profile'),
                  measurement_points='bicycle bottom-center; other vehicle bottom-right',
                  speed_clearance_status='not_computed', cvat_comparison_status='not_performed')
    target = run_dir / 'config' / f'{sid}_execution.json'
    write_json(target, record)
    model = None
    started = time.monotonic()
    counts, tracks, buffer = Counter(), set(), []
    try:
        if model_factory is None:
            from ultralytics import YOLO
            model_factory = YOLO
        model = model_factory(str(model_path))
        for frame, result in enumerate(model.track(source=source['path'], stream=True, persist=True,
                tracker=settings['tracker'], classes=list(LABELS), conf=settings['conf'], iou=settings['iou'],
                imgsz=settings['imgsz'], device=settings['device'], batch=1, vid_stride=1, half=False,
                verbose=False, save=False, save_txt=False)):
            record['processed_frames'] = frame + 1
            boxes = result.boxes
            if boxes is not None and len(boxes):
                xy = boxes.xyxy.cpu().numpy(); cls = boxes.cls.int().cpu().tolist()
                scores = boxes.conf.cpu().tolist()
                ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(boxes)
                for bbox, c, score, tid in zip(xy, cls, scores, ids):
                    label = LABELS[int(c)]; x1, y1, x2, y2 = map(float, bbox)
                    mx = (x1 + x2) / 2 if label == 'bicycle' else x2
                    buffer.append((rid, vid, int(c), frame + 1, x1, y1, x2, y2, model_path.stem,
                                   label, tid, float(score), tid, mx, y2))
                    record['detection_rows'] += 1; counts[label] += 1
                    record['missing_track_id_rows'] += tid is None
                    if tid is not None: tracks.add(int(tid))
            if record['processed_frames'] % 300 == 0:
                conn.executemany(INSERT_BOX, buffer); conn.commit(); buffer.clear()
                record['elapsed_s'] = round(time.monotonic() - started, 1)
                write_json(run_dir / 'logs' / f'{sid}_progress.json', record)
                print(f"{sid}: {record['processed_frames']}/{props['reported_frames']} frames, {record['elapsed_s']} s", flush=True)
        if not record['processed_frames']:
            raise ValueError('no_decoded_frames')
        if props['reported_frames'] > 0 and record['processed_frames'] != props['reported_frames']:
            raise ValueError('incomplete_decode')
        if buffer: conn.executemany(INSERT_BOX, buffer)
        from Source_code.modules.normalized_detection_schema import sync_normalized_detection_tables
        normalized = sync_normalized_detection_tables(conn, run_id=rid, include_manual=False)
        conn.execute('UPDATE ProcessLog SET status=?,process_end=?,total_detections=? WHERE run_id=?',
                     ('completed', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), record['detection_rows'], rid))
        conn.commit()
        record.update(status='completed', decode_status='complete' if props['reported_frames'] > 0 else 'frame_count_unverified',
                      class_counts=dict(counts), detected_tracks=len(tracks), normalized=normalized,
                      elapsed_s=round(time.monotonic() - started, 1))
        write_json(output / 'summary.json', record)
    except Exception as exc:
        conn.rollback()
        conn.execute('UPDATE ProcessLog SET status=?,process_end=?,error_message=? WHERE run_id=?',
                     ('error', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), type(exc).__name__, rid))
        conn.commit()
        record.update(status='failed', error_type=type(exc).__name__,
                      error_code=str(exc) if str(exc) in {'incomplete_decode', 'no_decoded_frames'} else 'inference_failed',
                      elapsed_s=round(time.monotonic() - started, 1))
    finally:
        write_json(target, record)
        if model is not None:
            del model
        import torch
        if torch.cuda.is_available(): torch.cuda.empty_cache()
    return record


def run_batch(sources, settings, model_path, db_path, run_dir, resume=False, dry_run=False):
    run_dir = Path(run_dir).resolve()
    if not (run_dir / 'manifest.json').is_file():
        raise ValueError('create an analysis run before processing')
    if not sources: raise ValueError('no videos selected')
    conditions = run_dir / 'config/conditions.json'
    if conditions.is_file() and json.loads(conditions.read_text(encoding='utf-8')) != settings:
        raise ValueError('changed parameters require a new analysis run')
    if not dry_run and not resume and any((run_dir / 'config' / f'{s["source_id"]}_execution.json').exists() for s in sources):
        raise ValueError('existing executions require --resume or a new analysis run')
    for name in ('config', 'tables', 'logs'): (run_dir / name).mkdir(exist_ok=True)
    write_json(run_dir / 'config/sources.json', dict(sources=sources))
    write_json(run_dir / 'config/conditions.json', settings)
    model_hash = None if dry_run else sha(model_path)
    if not dry_run and not Path(db_path).is_file(): raise FileNotFoundError('application database not found')
    results = []
    for source in sources:
        sid = source['source_id']
        try:
            props = probe_video(source['path'])
            profile = source.get('calibration_profile')
            if profile and not (ROOT / 'output/calibrations' / f'{profile}.json').is_file():
                raise ValueError('calibration_profile_not_found')
            if dry_run:
                record = dict(source_id=sid, status='planned', **props, calibration_profile=profile)
            else:
                fingerprint, provenance = signature(source, props, settings, model_hash)
                previous = run_dir / 'config' / f'{sid}_execution.json'
                prev = json.loads(previous.read_text(encoding='utf-8')) if resume and previous.is_file() else None
                with sqlite3.connect(db_path, timeout=60) as conn:
                    if reusable(prev, fingerprint, conn):
                        record = dict(prev, reused=True)
                        print(f'{sid}: reused completed run {record["db_run_id"]}', flush=True)
                    else:
                        record = infer(source, props, settings, model_path, conn, run_dir, fingerprint, provenance)
        except Exception as exc:
            record = dict(source_id=sid, status='failed', error_type=type(exc).__name__, error_code='input_or_setup_failed')
        results.append(record)
        write_json(run_dir / 'tables/batch_summary.json', results)
        print(json.dumps({k: record[k] for k in ('source_id', 'status', 'processed_frames', 'db_run_id', 'error_type') if k in record}), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--folder', action='append', type=Path, help='repeat for multiple roots; recursive by default')
    inputs.add_argument('--video', action='append', type=Path, help='repeat for specific videos')
    inputs.add_argument('--sources', type=Path, help='JSON manifest with per-video metadata')
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--include', action='append', help='filename/relative path glob; repeat for OR')
    parser.add_argument('--exclude', action='append', help='additional exclusion glob')
    parser.add_argument('--include-derived', action='store_true', help='disable default bbox/clip/annotation exclusions')
    parser.add_argument('--no-recursive', action='store_true')
    parser.add_argument('--resume', action='store_true', help='reuse only verified identical completed runs')
    parser.add_argument('--dry-run', action='store_true', help='probe inputs without inference or DB writes')
    parser.add_argument('--model', type=Path, default=ROOT / 'models/yolo26x.pt')
    parser.add_argument('--database', type=Path, default=ROOT / 'db/my_app_data.db')
    parser.add_argument('--tracker', default='bytetrack.yaml')
    parser.add_argument('--device', default='0')
    parser.add_argument('--conf', type=float, default=.20)
    parser.add_argument('--iou', type=float, default=.5)
    parser.add_argument('--imgsz', type=int, default=960)
    args = parser.parse_args()
    if not 0 <= args.conf <= 1 or not 0 <= args.iou <= 1 or args.imgsz <= 0:
        parser.error('conf/iou must be 0..1 and imgsz must be positive')
    excludes = ([] if args.include_derived else DEFAULT_EXCLUDES) + (args.exclude or [])
    sources = load_sources(args.sources) if args.sources else sources_from_paths(
        discover(args.folder, not args.no_recursive, args.include, excludes) if args.folder else args.video)
    settings = dict(model=str(args.model.resolve()), tracker=args.tracker, device=args.device,
                    conf=args.conf, iou=args.iou, imgsz=args.imgsz, seed=0,
                    vid_stride=1, half=False, batch=1, classes=list(LABELS), tracker_reset='between videos')
    if not args.dry_run:
        import torch
        import numpy as np
        torch.manual_seed(0); np.random.seed(0)
    results = run_batch(sources, settings, args.model.resolve(), args.database.resolve(),
                        args.run_dir, args.resume, args.dry_run)
    manifest_path = args.run_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    failed = sum(r['status'] == 'failed' for r in results)
    verified_decode = all(r.get('decode_status') == 'complete' for r in results)
    manifest.update(source_ids=[s['source_id'] for s in sources], parameters=settings,
                    status='planned' if args.dry_run else ('failed' if failed else 'completed'),
                    execution_status='not_started' if args.dry_run else ('partial_failure' if failed else 'completed'),
                    validation_status='unverified', accuracy_status='unverified',
                    runner_sha256=sha(__file__), command=sys.argv,
                    working_directory=str(ROOT),
                    environment={n: importlib.metadata.version(n) for n in ('ultralytics', 'torch', 'opencv-python')},
                    validation=[dict(kind='full_video_decode', status='not_performed' if args.dry_run else ('failed' if failed else ('passed' if verified_decode else 'unverified')))])
    write_json(manifest_path, manifest)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
