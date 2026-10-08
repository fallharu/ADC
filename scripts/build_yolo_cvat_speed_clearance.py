"""Derived, anonymous metrics for the two current CVAT reference videos.

Read source XML/SQLite in place; never export annotations, images or databases.
Split by original video, including all annotation methods and cut clips.
These are calibrated estimates, not independent ground-truth labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "Source_code/modules").is_dir() and (p / "scripts").is_dir())
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from analyze_cvat_annotations import Projection, parse_cvat_xml
from Source_code.modules.speed_regression import rolling_linear_slope

SOURCES = [
    dict(source_id="video-A", run_id=100551, task="t3", road_type="non_widened",
         profile="cvat_1575_auto_v2", split="train"),
    dict(source_id="video-B", run_id=100423, task="t4", road_type="widened",
         profile="cvat_2945_auto_v2", split="val"),
]
BIKES = {"bicycle", "bike", "cyclist"}
CARS = {"car", "truck", "bus", "van", "automobile", "vehicle"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_tracks(df, projection, fps, method, coordinate_scale):
    """Regress longitudinal position over 0.2 s, within calibrated polygon.

    CVAT: interpolate *world* positions between genuine keyframes. YOLO:
    retain the application's saved measurement points, with no BBOX fallback.
    Regression never bridges a missing detection/invalid calibration frame.
    """
    df = df.copy().sort_values(["track_id", "frame_num"]).reset_index(drop=True)
    if method == "CVAT":
        # Match the previous reference convention for these approaching cars.
        df["measure_x"] = np.where(df.label.isin(BIKES), (df.x1 + df.x2) / 2, df.x2)
        df["measure_y"] = df.y2
    df["measure_x"] *= coordinate_scale
    df["measure_y"] *= coordinate_scale
    y_guard = projection.image_points[:, 1].min() - 40
    safe = df.measure_y > y_guard
    df["u"] = np.nan
    df["v"] = np.nan
    df.loc[safe, ["u", "v"]] = np.column_stack(projection.to_world(
        df.loc[safe, "measure_x"].to_numpy(), df.loc[safe, "measure_y"].to_numpy()))
    if method == "CVAT":
        for _, g in df.groupby("track_id"):
            k = g[(g.is_keyframe == 1) & (g.is_held == 0) & g.u.notna() & g.v.notna()]
            bounded = g.frame_num.between(k.frame_num.min(), k.frame_num.max())
            ix = g.index[bounded & (g.is_held == 0)]
            df.loc[g.index, ["u", "v"]] = np.nan
            if len(k) >= 2:
                for col in ["u", "v"]:
                    df.loc[ix, col] = np.interp(g.loc[ix, "frame_num"], k.frame_num, k[col])
    df["inside"] = (df.u.between(0, projection.width_m) & df.v.between(0, projection.length_m))
    # Split at every frame gap: a one-frame missing detection is not fabricated.
    gap = df.groupby("track_id").frame_num.diff().ne(1)
    df["segment"] = gap.cumsum()
    slope = rolling_linear_slope(df.frame_num, df.v, df.segment, fps,
                                lookback_frames=max(1, round(fps * .2)), valid_mask=df.inside)
    df["speed_km_h"] = slope.abs() * 3.6
    df["signed_speed"] = slope * 3.6
    def direction(v):
        differences = v.diff().dropna()
        return np.sign(differences.median()) if len(differences) else 0.
    df["direction"] = df.groupby("track_id").v.transform(direction)
    # Avoid applying the CVAT right-bottom convention to receding vehicles.
    if method == "CVAT":
        df.loc[(~df.label.isin(BIKES)) & (df.direction > 0), ["speed_km_h", "inside"]] = [np.nan, False]
    return df


def derive_samples(df, fps, meta, method):
    base = {k: meta[k] for k in ["source_id", "road_type", "split"]}
    base.update(method=method, target_kind="calibrated_estimate", fps=fps)
    window = max(1, round(fps * .2))
    speed_rows, track_rows = [], []
    for tid, g in df.groupby("track_id"):
        g = g[g.speed_km_h.notna()]
        if len(g) < 15:
            continue
        ident = f"{meta['source_id']}-{method}-track-{int(tid)}"
        tr = dict(base, sample_id=ident, label=g.label.iloc[0], valid_frames=len(g),
                  speed_km_h=float(g.speed_km_h.median()),
                  q25_km_h=float(g.speed_km_h.quantile(.25)), q75_km_h=float(g.speed_km_h.quantile(.75)))
        track_rows.append(tr)
        for bin_id, w in g.groupby(g.frame_num // window):
            if len(w) < max(3, window // 2):
                continue
            speed_rows.append(dict(base, sample_id=f"{ident}-window-{bin_id}", track_id=ident,
                                   label=w.label.iloc[0], time_s=float(w.frame_num.median()/fps),
                                   n_frames=len(w), speed_km_h=float(w.speed_km_h.median())))
    encounters = []
    bikes = df[df.label.isin(BIKES) & df.inside].copy()
    cars = df[df.label.isin(CARS) & df.inside].copy()
    pairs = bikes.merge(cars, on="frame_num", suffixes=("_bike", "_car"))
    if not pairs.empty:
        pairs = pairs[(pairs.direction_bike == pairs.direction_car) & (pairs.direction_bike != 0)]
        for (bid, cid), g in pairs.groupby(["track_id_bike", "track_id_car"]):
            gap = g.v_car - g.v_bike
            # Same direction and a longitudinal sign crossing define a passing event.
            if not (gap.min() < -1 and gap.max() > 1):
                continue
            side = g[gap.abs() <= 1].copy()
            if side.empty:
                continue
            side["lateral_gap"] = (side.u_car-side.u_bike).abs()
            row = side.loc[(side.v_car-side.v_bike).abs().idxmin()]
            encounters.append(dict(base, sample_id=f"{meta['source_id']}-{method}-pair-{int(bid)}-{int(cid)}",
                                   time_s=float(row.frame_num/fps), n_side_frames=len(side),
                                   clearance_m=float(row.lateral_gap),
                                   euclidean_point_gap_m=float(np.hypot(row.u_car-row.u_bike,row.v_car-row.v_bike)),
                                   speed_km_h=float(row.speed_km_h_car),
                                   bicycle_speed_km_h=float(row.speed_km_h_bike)))
    return speed_rows, track_rows, encounters


def box_stats(values):
    a = np.asarray(values, dtype=float); a = a[np.isfinite(a)]
    if not len(a): return None
    q1, med, q3 = np.quantile(a, [.25,.5,.75]); iqr=q3-q1
    inlier=a[(a>=q1-1.5*iqr)&(a<=q3+1.5*iqr)]
    return dict(n=len(a), median=float(med), q1=float(q1), q3=float(q3),
                low=float(inlier.min()), high=float(inlier.max()),
                outliers=a[(a<q1-1.5*iqr)|(a>q3+1.5*iqr)].tolist(), values=a.tolist())


def validate(speed, tracks, clearance):
    checks = []
    for name, table in [("speed",speed),("tracks",tracks),("clearance",clearance)]:
        assert not table.empty, f"no valid {name} samples"
        assert table.sample_id.is_unique
        assert set(table[table.split == "train"].source_id).isdisjoint(set(table[table.split == "val"].source_id))
        assert np.isfinite(table.speed_km_h.dropna()).all()
        checks.append(f"{name}: unique IDs, finite speeds, video grouping; {len(table)} samples")
        if table[table.split == 'val'].empty:
            checks.append(f"LIMITATION: {name} validation subset empty; no simultaneous calibrated car/bicycle observation in video-B")
    assert (clearance.clearance_m >= 0).all()
    for method in ["YOLO", "CVAT"]:
        assert set(speed[speed.method == method].split) == {"train","val"}
    return checks


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("run_dir", type=Path)
    ap.add_argument("--exports", type=Path, default=Path.home()/"AppData/Local/Temp/cvat_export")
    args=ap.parse_args(); out=args.run_dir.resolve()
    manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
    manifest["parameters"] = dict(sources=SOURCES, split_unit="original_video", seed=None,
        split_ratio="1 original video each: 50/50; sample proportions vary", window_s=.2,
        minimum_speed_frames=15, passing_longitudinal_margin_m=1,
        clearance_definition="lateral measurement-point gap at nearest side-by-side frame; not body-edge clearance",
        coordinate_scale_yolo=1280/1920, cvat_world_interpolation=True,
        absolute_metric_validation="no independent speed/distance reference")
    manifest["status"]="running"
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    con=sqlite3.connect((ROOT/"db/my_app_data.db").as_uri()+"?mode=ro",uri=True)
    speed_rows=[];track_rows=[];encounters=[];provenance=[];quality=[]
    for meta in SOURCES:
        profile=ROOT/"output/calibrations"/(meta["profile"]+".json")
        calibration=json.loads(profile.read_text(encoding="utf-8-sig"))
        proj=Projection(calibration["scale"]["homography"])
        xml=args.exports/meta["task"]/"annotations.xml"
        cvat,xmlmeta=parse_cvat_xml(str(xml))
        assert (xmlmeta['width'],xmlmeta['height']) == (1280,720)
        yolo=pd.read_sql_query("""select group_id as track_id,frame_num,class_name as label,
                 measure_x,measure_y,x1,y1,x2,y2,auto_id from Detection
                 where run_id=? and model_name='yolo26x' and measure_x is not null
                 and measure_y is not null order by group_id,frame_num,auto_id""",con,params=[meta['run_id']])
        dup=int(yolo.duplicated(['track_id','frame_num']).sum())
        yolo=yolo.drop_duplicates(['track_id','frame_num'],keep='last')
        fps=float(con.execute('select v.fps from Video v join ProcessLog p on p.video_id=v.video_id where p.run_id=?',(meta['run_id'],)).fetchone()[0])
        provenance.append(dict(source_id=meta['source_id'],profile_sha256=sha(profile),xml_sha256=sha(xml),
                               selected_yolo_rows_sha256=hashlib.sha256(yolo.to_json().encode()).hexdigest(),
                               max_auto_id=int(yolo.auto_id.max()),n_selected_rows=len(yolo),
                               source_video_group=meta['source_id'],cvat_fps=30,yolo_fps=fps))
        for method,raw,scale,f in [('YOLO',yolo,1280/1920,fps),('CVAT',cvat,1.,30.)]:
            points=project_tracks(raw,proj,f,method,scale)
            a,b,d=derive_samples(points,f,meta,method)
            speed_rows+=a;track_rows+=b;encounters+=d
            quality.append(dict(source_id=meta['source_id'],method=method,rows=len(raw),
                inside_rows=int(points.inside.sum()),valid_speed_frames=int(points.speed_km_h.notna().sum()),
                retained_tracks=len(b),speed_windows=len(a),passing_pairs=len(d),duplicate_yolo_rows=dup if method=='YOLO' else 0))
    con.close()
    speed=pd.DataFrame(speed_rows); tracks=pd.DataFrame(track_rows)
    clearance=pd.DataFrame(encounters,columns=list(encounters[0]) if encounters else ['sample_id','split','source_id','speed_km_h','clearance_m'])
    checks=validate(speed,tracks,clearance)
    for name,table in [('speed_windows',speed),('track_summary',tracks),('clearance_encounters',clearance),('quality',pd.DataFrame(quality))]:
        table.to_csv(out/'tables'/f'{name}.csv',index=False,encoding='utf-8-sig',float_format='%.6f')
        if 'split' in table:
            for split in ['train','val']:
                table[table.split==split].to_csv(out/'tables'/f'{name}_{split}.csv',index=False,encoding='utf-8-sig',float_format='%.6f')
    summary={'quality':quality,'boxes':{},'validation':checks,'road_comparison':[]}
    for method in ['YOLO','CVAT']:
        for meta in SOURCES:
            label=f"{method} / {meta['source_id']}"
            sub=tracks[(tracks.method==method)&(tracks.source_id==meta['source_id'])&(tracks.label=='car')]
            summary['boxes'][label+' / speed']=box_stats(sub.speed_km_h)
            sub=clearance[(clearance.method==method)&(clearance.source_id==meta['source_id'])]
            summary['boxes'][label+' / clearance']=box_stats(sub.clearance_m)
        for metric,table,column in [('speed',tracks[tracks.label=='car'],'speed_km_h'),('clearance',clearance,'clearance_m')]:
            a=table[(table.method==method)&(table.road_type=='non_widened')][column]
            b=table[(table.method==method)&(table.road_type=='widened')][column]
            summary['road_comparison'].append(dict(method=method,metric=metric,n_non_widened=len(a),n_widened=len(b),
                non_widened_median=float(a.median()) if len(a) else None,widened_median=float(b.median()) if len(b) else None,
                difference_widened_minus_non_widened=float(b.median()-a.median()) if len(a) and len(b) else None,
                interpretation='one video per road type; site/date/method and track selection confounding; no causal inference'))
    (out/'tables/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (out/'config/source_provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    (out/'logs/validation.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps({'quality':quality,'road_comparison':summary['road_comparison'],'validation':checks},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
