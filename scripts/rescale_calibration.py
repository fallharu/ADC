"""既存キャリブレーションを別解像度の動画向けに座標スケールするだけのツール。

アプリのキャリブレーションは作成時のフレーム解像度の画素座標で保存される。
同じカメラでも解像度違いの動画へ適用する場合は座標を等倍でスケールする必要がある。
スケール以外（mode / known_distance_m / num_intervals / width_m / length_m /
interval_m など実寸のメタデータ）は一切変更しない。

使い方:
    python scripts/rescale_calibration.py <元プロファイル> <新プロファイル名> <倍率>
    python scripts/rescale_calibration.py 2_20250720_y 2_20250720_y_720 0.6666667
"""
from __future__ import annotations

import argparse
import copy
import json
import os

CALIB_DIR = os.path.join("output", "calibrations")


def scale_points(obj, s: float):
    """[x, y] の組だけを見つけてスケールする（実寸の数値には触らない）。"""
    if isinstance(obj, dict):
        return {k: scale_points(v, s) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in obj):
            return [obj[0] * s, obj[1] * s]
        return [scale_points(v, s) for v in obj]
    return obj


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("scale", type=float)
    args = ap.parse_args()

    src_path = os.path.join(CALIB_DIR, args.src + ".json")
    with open(src_path, encoding="utf-8") as fh:
        data = json.load(fh)

    out = copy.deepcopy(data)
    if "lines" in out:
        out["lines"] = scale_points(out["lines"], args.scale)

    scale_block = out.get("scale") or {}
    if "lines" in scale_block:
        scale_block["lines"] = scale_points(scale_block["lines"], args.scale)
    homo = scale_block.get("homography") or {}
    if "image_points" in homo:
        homo["image_points"] = scale_points(homo["image_points"], args.scale)
    path_meta = scale_block.get("path") or {}
    if "points" in path_meta:
        path_meta["points"] = scale_points(path_meta["points"], args.scale)

    out["rescaled_from"] = {"profile": args.src, "factor": args.scale}

    dst_path = os.path.join(CALIB_DIR, args.dst + ".json")
    with open(dst_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)

    sm = out.get("scale") or {}
    print("書き出し: %s" % dst_path)
    print("  mode=%s  known_distance_m=%s  num_intervals=%s  scale.lines=%d本"
          % (sm.get("mode"), sm.get("known_distance_m"), sm.get("num_intervals"),
             len(sm.get("lines") or [])))
    h = sm.get("homography") or {}
    if h:
        print("  homography: width_m=%s length_m=%s interval_m=%s"
              % (h.get("width_m"), h.get("length_m"), h.get("interval_m")))
    print("  lines=%s" % sorted((out.get("lines") or {}).keys()))


if __name__ == "__main__":
    main()
