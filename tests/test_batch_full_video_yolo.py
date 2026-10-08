import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from scripts import batch_full_video_yolo as batch


def test_discovery_multiple_roots_formats_filters_and_duplicates(tmp_path):
    sub = tmp_path / 'sub'
    sub.mkdir()
    for path in (tmp_path / 'one.MP4', tmp_path / 'one-bbox.mp4', sub / 'two.mov', sub / 'two_bike_clips.mp4', sub / 'note.txt'):
        path.touch()
    assert [p.name for p in batch.discover([tmp_path, sub])] == ['one.MP4', 'two.mov']
    assert len(batch.discover([tmp_path], recursive=False)) == 1
    assert len(batch.discover([tmp_path], excludes=[])) == 4
    assert [p.name for p in batch.discover([tmp_path], includes=['sub/*'], excludes=['*clips*'])] == ['two.mov']


def test_manifest_per_video_metadata_and_relative_paths(tmp_path):
    manifest = tmp_path / 'sources.json'
    manifest.write_text(json.dumps(dict(sources=[dict(source_id='v1', path='a.mp4', calibration_profile='a', collection_year=2026),
                                               dict(source_id='v2', path='b.mov')])))
    sources = batch.load_sources(manifest)
    assert sources[0]['path'] == str(tmp_path / 'a.mp4')
    assert sources[0]['collection_year'] == 2026
    assert 'calibration_profile' not in sources[1]


@pytest.mark.parametrize('sources', [
    [dict(source_id='../outside', path='a.mp4')],
    [dict(source_id='v1', path='a.mp4'), dict(source_id='v1', path='b.mp4')],
    [dict(source_id='v1', path='a.mp4'), dict(source_id='v2', path='./a.mp4')],
    [dict(source_id='v1', path='a.mp4', calibration_profile='../bad')],
])
def test_manifest_rejects_unsafe_or_duplicate_inputs(tmp_path, sources):
    manifest = tmp_path / 'sources.json'
    manifest.write_text(json.dumps(dict(sources=sources)))
    with pytest.raises(ValueError): batch.load_sources(manifest)


def make_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript('''
          CREATE TABLE Video(video_id INTEGER PRIMARY KEY,filename,upload_datetime,duration,fps,source_path,road_type,collection_year);
          CREATE TABLE ProcessLog(run_id INTEGER PRIMARY KEY,video_id,base_video_id,process_start,output_folder,folder_alias,status,calibration_profile,process_end,total_detections,error_message);
          CREATE TABLE Detection(run_id,video_id,class_id,frame_num,x1,y1,x2,y2,model_name,class_name,track_id,confidence,group_id,measure_x,measure_y);
        ''')


def test_reuse_checks_identity_completion_and_actual_db_rows(tmp_path):
    db = tmp_path / 'app.db'; make_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO ProcessLog(run_id,status,total_detections) VALUES(1,'completed',0)")
        record = dict(status='completed', fingerprint='same', db_run_id=1, detection_rows=0)
        assert batch.reusable(record, 'same', conn)
        assert not batch.reusable(record, 'changed', conn)
        conn.execute('INSERT INTO Detection(run_id) VALUES(1)')
        assert not batch.reusable(record, 'same', conn)
        conn.execute("UPDATE ProcessLog SET status='error' WHERE run_id=1")
        assert not batch.reusable(record, 'same', conn)


def test_batch_continues_after_failure_fresh_model_and_variable_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, 'ROOT', tmp_path)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    from Source_code.modules import normalized_detection_schema
    monkeypatch.setattr(normalized_detection_schema, 'sync_normalized_detection_tables', lambda *a, **k: {})
    run = tmp_path / 'run'; run.mkdir(); (run / 'manifest.json').write_text('{}')
    db = tmp_path / 'app.db'; make_db(db)
    model = tmp_path / 'model.pt'; model.write_bytes(b'model')
    paths = [tmp_path / 'bad.mp4', tmp_path / 'good.mov']
    for p in paths: p.write_bytes(p.name.encode())
    sources = batch.sources_from_paths(paths)
    monkeypatch.setattr(batch, 'probe_video', lambda p: dict(reported_frames=2 if p.endswith('mp4') else 3,
                                                          fps=25. if p.endswith('mp4') else 59.94, width=640, height=480))
    created = []
    class Model:
        def __init__(self, path): created.append(self)
        def track(self, **kwargs):
            assert kwargs['vid_stride'] == 1 and kwargs['persist'] is True
            yield SimpleNamespace(boxes=None)
            if kwargs['source'].endswith('mp4'): raise RuntimeError('bad input')
            yield SimpleNamespace(boxes=None)
            yield SimpleNamespace(boxes=None)
    original_infer = batch.infer
    monkeypatch.setattr(batch, 'infer', lambda *a: original_infer(*a, model_factory=Model))
    settings = dict(tracker='bytetrack.yaml', device='cpu', conf=.2, iou=.5, imgsz=960)
    results = batch.run_batch(sources, settings, model, db, run)
    assert [r['status'] for r in results] == ['failed', 'completed']
    assert len(created) == 2 and created[0] is not created[1]
    assert results[1]['processed_frames'] == 3 and results[1]['fps'] == 59.94
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT fps FROM Video ORDER BY video_id').fetchall() == [(25.,), (59.94,)]
        assert conn.execute('SELECT status FROM ProcessLog ORDER BY run_id').fetchall() == [('error',), ('completed',)]
    repeated = batch.run_batch(sources, settings, model, db, run, resume=True)
    assert repeated[1]['reused'] is True and len(created) == 3
    with pytest.raises(ValueError, match='changed parameters'):
        batch.run_batch(sources, dict(settings, imgsz=640), model, db, run, resume=True)
    with pytest.raises(ValueError, match='existing executions'):
        batch.run_batch(sources, settings, model, db, run)


def test_truncated_decode_is_failed_not_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, 'ROOT', tmp_path)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    run = tmp_path / 'run'; run.mkdir()
    db = tmp_path / 'app.db'; make_db(db)
    class Truncated:
        def __init__(self, path): pass
        def track(self, **kwargs): yield SimpleNamespace(boxes=None)
    with sqlite3.connect(db) as conn:
        record = batch.infer(dict(source_id='truncated', path=str(tmp_path / 'x.mp4')),
                             dict(reported_frames=2, fps=29.97, width=1920, height=1080),
                             dict(tracker='bytetrack.yaml', conf=.2, iou=.5, imgsz=960, device='cpu'),
                             Path('model.pt'), conn, run, 'signature', {}, Truncated)
        assert record['status'] == 'failed' and record['error_code'] == 'incomplete_decode'
        assert conn.execute('SELECT status FROM ProcessLog').fetchone()[0] == 'error'
