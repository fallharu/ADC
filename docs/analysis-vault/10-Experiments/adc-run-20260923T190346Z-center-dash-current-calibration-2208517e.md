---
note_id: adc-run-20260923T190346Z-center-dash-current-calibration-2208517e
vault_kind: analysis
note_type: experiment
title: "現行校正での道路中央破線周期の確認"
summary: "7月20日の中央破線候補を現行校正で測定。基準内3本の2周期は射影直後10.87/10.03 m、補正後11.25/6.97 m。実周期は未測量。"
run_id: adc-run-20260923T190346Z-center-dash-current-calibration-2208517e
parent_run_id: adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0
source_ids:
  - source-adc-camera-20250720-representative-01
  - source-adc-homography-profile-cf-v5-1080-after-edge-removal
artifact_ids:
  - artifact-current-central-dash-candidates-image
  - artifact-current-central-dash-candidates-table
  - artifact-current-central-dash-summary
revision: 2
status: completed
validation_status: unverified
updated: 2026-09-23T19:07:17+00:00
---

# 現行校正での道路中央破線周期の確認

## 問い・仮説

- 解決したい問題: 現行7月20日ホモグラフィ校正の写真に見える道路中央破線が、どのような距離基準になり得るか確認する。
- 原因の仮説: 破線の前端同士の周期が物理的に一定なら、射影後の周期のばらつきは位置ごとの距離縮尺を疑う材料になる。
- 対象コード: `scripts/check_calibration_distortion.py` の背景中央値・中央破線候補検出、`Source_code/modules/speed_homography/__init__.py` の現行距離補正。

## 比較条件と再現

- 基準実装・変更案: 現行9本校正profileを対象に、同日・同カメラ動画の背景中央値から中央線周囲の白い塊を検出し、前端間の射影距離と補正後距離を比較する。アプリの校正値は変更しない。
- 指標・単位・成功基準: 破線候補数、前端間の周期(m)、周期の変動係数。画像上で候補の妥当性を目視確認し、実測真値なしなら絶対距離は結論しない。
- source_id・データ版・件数・除外条件: 7月20日の同カメラ動画と `2_250720_cf_v5` の編集後profile。破線同士の連結、校正点外、未検出を区別する。元動画をVaultへ複製しない。
- コード版・未コミット差分・環境・seed: HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`。分析元スクリプト2本はuntrackedのため試験版をrunの`code/`に保存、速度射影のdirty差分も保持。Python 3.13.7、OpenCV 4.12.0、NumPy 2.2.6、Pandas 2.3.3、SciPy 1.17.0。乱数なし。
- 実行コマンド・作業ディレクトリ: リポジトリ直下で `python docs/analysis-vault/80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/code/analyze_center_dash_current.py --video <source-adc-camera-20250720-representative-01> --profile docs/analysis-vault/80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/config/profile_1080_after_edge_removal.json --annotated docs/analysis-vault/80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/figures/central_dash_candidates.png --candidates docs/analysis-vault/80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/tables/central_dash_candidates.csv --summary docs/analysis-vault/80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/tables/central_dash_summary.json`。sourceのハッシュは[conditions](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/config/conditions.json)。

## 結果と検証

- profileの `lines.center_line` は中央線をたどる62個の画像座標ポリライン。個々の破線端点や物理的な破線長は保存されていない。前runで9本にした `scale.lines` の横断校正線とは別の設定。
- 21フレームの中央値背景から中央線周辺の白い塊9個を検出。手前の候補は校正領域外、遠方の候補は現行補正の基準点範囲外で、基準点内は3個。[候補写真](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/figures/central_dash_candidates.png) (`artifact-current-central-dash-candidates-image`) で緑の丸1〜3が採用候補。黄線は保存済み中央線、赤は検出白領域。
- [候補表](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/tables/central_dash_candidates.csv) (`artifact-current-central-dash-candidates-table`) と[要約](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/tables/central_dash_summary.json) (`artifact-current-central-dash-summary`): 前端の射影直後の道路位置は4.294、15.163、25.193 m、現行補正後は6.298、17.547、24.519 m。

| 前端から次の前端までの周期 | 射影直後 (m) | 現行の線補正後 (m) |
| --- | ---: | ---: |
| 候補1→2 | 10.869 | 11.249 |
| 候補2→3 | 10.030 | 6.972 |

- 2周期だけでの変動係数は射影直後4.0%、補正後23.5%。破線周期が物理的に一定なら、この範囲では現行の5 m等間隔線補正が周期の一様性を悪化させている。ただし2周期だけの参考値で、検出誤差・実際の施工差は未評価。
- 既存の `output/cvat_job2_2_250803_new2/distortion_check/dash_periods.csv` は**別日（8月3日）の映像**。その基準周期中央値や `interval_m × 2 = 10 m` の既定値は、この7月20日の物理的な周期実測値にはならない。
- 検証: 候補写真を目視し、採用候補が道路中央の白い破線に重なることを確認。数値は現行の4点射影 `Projection` と `HomographyProjection` の同じHから計算。独立の巻尺・測量値なし。
- 限界: 白線の摩耗・遮蔽、遠方での連結、曲線と勾配、中央線と車両走行線の差。物理周期と真速度がないため絶対距離と速度精度は未検証。
- 採否: 中央破線を相対縮尺の診断材料として採用。今回の2周期から現行補正を自動変更する判断は保留。
- 次の最小実験: 同じ道路で隣接する破線前端間を1〜数周期だけ実測し、画像上の端点を手動確認したうえで、射影直後・現行補正後と照合する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/manifest.json)
- [候補写真](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/figures/central_dash_candidates.png)
- [条件](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/config/conditions.json)と[集計](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/tables/central_dash_summary.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/slides/slide-card.md)
- 試験コードは `../80-Artifacts/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e/code/`、図表は同じ実験の `figures/` へ保存。
