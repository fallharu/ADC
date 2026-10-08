---
note_id: adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea
vault_kind: analysis
note_type: experiment
title: "CVAT射影変換と速度の関係・発表用二次整理"
summary: "合成ホモグラフィ試験と実CVAT車線透視校正の速度結果を区別して整理。実速度精度は未検証。"
run_id: adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea
parent_run_id: null
source_ids: []
artifact_ids:
  - artifact-cvat-projection-evidence-summary
  - artifact-synthetic-homography-speed-chart
  - artifact-cvat-lane-perspective-speed-chart
  - artifact-secondary-analysis-code
revision: 2
status: completed
validation_status: unverified
updated: 2026-09-23T17:53:51+00:00
---

# CVAT射影変換と速度の関係・発表用二次整理

## 問い・仮説

- 問い: 画像座標を道路平面の距離に直すと速度推定がどう変わるか。合成ホモグラフィ検証と実CVAT適用を分けて整理する。
- 仮説: 道路平面上の位置変化から速度を計算すれば、画面内の透視縮尺変化を速度に直接混ぜずに済む。窓内回帰は2点差分より速度の隣接変動を減らせる。
- 対象コード: `scripts/generate_projection_speed_test_data.py`, `Source_code/modules/speed_homography/`, `scripts/visualize_cvat_distance_speed.py`, `Source_code/modules/speed_regression.py`。

## 比較条件と再現

- 本runは既存成果物の二次整理。合成試験・CVAT計測のパイプライン、元動画、CVAT XMLは再実行・複製していない。
- 合成ホモグラフィ: 30 fps、道路10 m × 100 m、走行範囲5–95 m、画像座標ノイズσ=0.65 px、速度窓0.2秒、速度の5フレーム中央値平滑化。乱数seedは100/101。
- シナリオ: 54 km/h一定（172評価区間）、28.8→57.6→28.8 km/hの対称加速・減速（217評価区間）。既知の真値と射影後推定を比較。
- 実CVAT: 校正profile `2_20250720_y`。1920×1080の校正形状を1280×720に縮尺。16 mの縦距離ラダーに対し、車線の見かけ幅の逆数から奥行きを推定する車線透視モデルをfit。注釈済み範囲外へ外挿しない。
- 実CVATの速度比較: 同一の校正後位置に対し0.2秒窓の端点差分と窓内最小二乗回帰を比較。track 0（自転車）の集計値を確認。
- source artifacts: `artifacts/projection_speed_test/README.md` と合成post-projection CSV、`artifacts/cvat_distance_speed_regression/README.md` と `track_distance_speed_summary.csv`。
- 実行コマンド: `python docs/analysis-vault/80-Artifacts/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea/code/summarize_projection_speed_evidence.py`。

## 結果と検証

### 合成データ: ホモグラフィ適用後の速度

既知の真値に対する結果。誤差集計は元生成コードと同じ評価区間で既存CSVから再計算し、元READMEの値と照合した。

| シナリオ | 位置RMSE | 速度bias | 速度MAE | 速度RMSE | 最大絶対誤差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 54 km/h一定 | 0.137 m | -0.095 km/h | 1.410 km/h | 1.940 km/h | 6.091 km/h |
| 加速・減速 | 0.130 m | +0.276 km/h | 1.576 km/h | 2.174 km/h | 6.397 km/h |

### 実CVAT: 車線透視校正後の速度

- 車線透視fit誤差: RMSE 0.377 m、最大0.780 m（校正点への適合誤差）。
- focus track 0（自転車）: 校正済み1,027フレーム、34.2秒、走行距離30.465 m、速度中央値2.699 km/h、最大15.449 km/h。
- 速度の隣接サンプル差RMS（roughness）: 端点差分1.110 → 窓内回帰0.848 km/h/sample、23.6%低下。
- 集計CSVのfocus track値はREADMEと再照合した。これは速度の滑らかさの比較であり、実速度との誤差ではない。

### 解釈と限界

- 合成データでは射影後位置と既知速度を直接比較できた。二つの軌跡とも速度RMSEは約1.9–2.2 km/hだが、最大区間誤差は約6.1–6.4 km/h残る。
- 実CVAT側の変換は2Dホモグラフィそのものではなく、車線幅の逆数と距離ラダーから奥行きを推定する別モデル。実CVATデータでホモグラフィの速度精度を検証した結果とは扱わない。
- 実CVATに独立した速度真値がないため、実データで精度が上がったとは結論できない。roughness低下は滑らかさのみを示す。
- 合成検証は既知の四隅・道路寸法から作った制御条件で、校正点誤差、レンズ歪み、路面勾配、車線外の軌跡、実検出誤差に対する頑健性は未評価。
- 総合判定: 手法の挙動を示す説明材料として採用可。実速度精度の結論には保留。

## 次の最小検証

同じCVAT軌跡に対して、独立に測った区間距離と速度（レーダー、GPS等の参照値）を用意し、射影前後または校正条件違いを同じ区間で比較する。距離別・track別にbias、MAE、RMSEを出し、校正点を少し動かした感度も確認する。実験を始める際は別runを作成する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea/manifest.json)
- [次回発表の2枚構成案](../80-Artifacts/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea/slides/next-presentation-outline.md)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea/slides/slide-card.md)
- [再集計コード](../80-Artifacts/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea/code/summarize_projection_speed_evidence.py)
- 図表: `../80-Artifacts/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea/figures/`。
