---
note_id: adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0
vault_kind: analysis
note_type: experiment
title: "射影校正の手前・奥の基準線削除と再評価"
summary: "手前の重複線と最奥線を各1本削除。最大局所倍率28.47→1.63倍、最大正補正+8.52→+3.52 m。実測精度は未検証。"
run_id: adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0
parent_run_id: adc-run-20260923T181319Z-homography-photo-correction-map-06312dba
source_ids:
  - source-adc-camera-20250720-representative-01
  - source-adc-homography-profile-cf-v5-720
artifact_ids:
  - artifact-homography-edge-removal-photo-compare
  - artifact-homography-edge-removal-metrics
  - artifact-homography-edge-removal-3d-after
revision: 2
status: completed
validation_status: unverified
updated: 2026-09-23T18:28:21+00:00
---

# 射影校正の手前・奥の基準線削除と再評価

## 問い・仮説

- 解決したい問題: 利用者の指示に従い、校正線の手前と最奥を各1本削除し、補正マップを再計算する。
- 原因の仮説: 手前にほぼ重複した2線があり、現行の5 m等間隔補正で距離倍率を極端に大きくしている。
- 対象コード: `Source_code/modules/speed_homography/__init__.py` の既存補正処理（コード変更なし）。対象profileは `2_250720_cf_v5` とその1280×720版。

## 比較条件と再現

- 基準実装・変更案: 11本の `scale.lines` から、奥の配列0番と手前の配列9番を除去する。手前の10番は射影四角形の端点と一致するため残す。幾何の四隅、道路寸法、5 m間隔設定は触らない。元profileは実験runのconfigに保存。
- 指標・単位・成功基準: 校正線数、最大累積補正量(m)、最大局所距離倍率、補正が基準点で定義される範囲(m)。狙いは近接2線による極端な倍率の解消。真値精度の向上は主張しない。
- source_id・データ版・件数・除外条件: 親run `adc-run-20260923T181319Z-homography-photo-correction-map-06312dba` と同じカメラ・profile・代表フレーム。除外する線は2本。現場距離の独立真値なし。
- コード版・未コミット差分・環境・seed: HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、対象処理はdirtyで [差分](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/code/speed_homography_source_diff.patch)を保持。Python 3.13.7、OpenCV 4.12.0、NumPy 2.2.6、Matplotlib 3.10.8。乱数なし。
- 実行コマンド・作業ディレクトリ: リポジトリ直下。削除は [trim_edge_lines.py](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/code/trim_edge_lines.py) にbefore profileと実profileのパスを渡して実行。比較図は [compare_edge_line_removal.py](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/code/compare_edge_line_removal.py) で同一代表動画・frame 690・before/afterの720 profileを入力。具体的なsource IDと引数は[change.json](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/config/change.json)とmanifestに保持。

## 結果と検証

- `2_250720_cf_v5` と `2_250720_cf_v5_720` の `scale.lines` から、配列0番（最奥）と9番（手前の近接2線のうち片方）を削除。手前の10番は射影四角形の境界点に一致するため残した。11本から9本になった。その他のJSONフィールドは完全一致。
- [実画像での変更前後](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/figures/edge_line_removal_before_after.png) (`artifact-homography-edge-removal-photo-compare`)、[数値](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/tables/edge_line_removal_metrics.json) (`artifact-homography-edge-removal-metrics`)。

| 指標 | 変更前 | 変更後 |
| --- | ---: | ---: |
| 校正線数 | 11 | 9 |
| 最大正補正 (m) | +8.515 | +3.515 |
| 最小補正 (m) | 約0 | −2.908 |
| 最大局所距離倍率 | 28.47倍 | 1.63倍 |
| 最奥の有効基準点・射影直後 (m) | 50.000 | 42.908 |

- 削除後、最後の基準線は射影直後42.908 m、補正後40.000 m。その先の道路端50 mで現行コードは端点の差を延長して47.092 mとする。ここは独立基準点なし。新しい[3D図](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/figures/homography_correction_3d_after.png) (`artifact-homography-edge-removal-3d-after`) では負補正も表示。
- 検証: `python -m pytest tests/test_speed_homography.py tests/test_homography_preview.py -q` → 17 passed。before/after profileのJSON差分が両解像度とも `scale.lines` の2本だけであること、720 profileが1080 profileの2/3縮尺であることを確認。比較図・3D図を目視確認。
- 限界: 最大補正量の低下は内部モデルの変化であり、実測精度の改善を証明しない。5 m間隔と旧設定8 m/4区間の整合は未確認。代表フレームは同一カメラだが元の校正フレームとの同一性は未確認。
- 採否: 指定された2線の削除を採用。距離基準を確認するまで追加の補正学習と精度主張は保留。
- 次の最小実験: 残る9線の物理間隔、特に最奥基準点から道路端までの距離を独立に測り、別runで位置・速度の誤差を比較する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/manifest.json)
- [実画像での変更前後](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/figures/edge_line_removal_before_after.png)
- [変更設定とbefore/afterのprofile](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/config/change.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/slides/slide-card.md)
- 試験コードは `../80-Artifacts/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0/code/`、図表は同じ実験の `figures/` へ保存。
