---
note_id: adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc
vault_kind: analysis
note_type: experiment
title: "俯瞰視点の手動・自動候補最高速度比較"
summary: "同一車両76フレームの俯瞰軌跡に手動・自動候補それぞれの最高推定速度を表示。手動80.70 km/hは奥側、自動候補85.54 km/hは手前側で発生。"
run_id: adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc
parent_run_id: adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-birdseye-max-speed-figure, artifact-birdseye-max-speed-table, artifact-birdseye-max-speed-summary]
revision: 1
status: completed
validation_status: verified
updated: 2026-09-23T20:19:55+00:00
---

# 俯瞰視点の手動・自動候補最高速度比較

## 問い・仮説

- 解決したい問題: 直前の速度比較における手動側・自動候補側それぞれの最大推定速度を、俯瞰画像上の位置と共に見比べられるようにする。
- 原因の仮説: 最大速度の値だけでは、どのフレーム・どの位置で発生したか分かりにくい。俯瞰に軌跡とピーク点を重ねれば比較できる。
- 対象コード: 本runの `code/plot_birdseye_max_speed.py` を新規作成する。アプリとprofileは変更しない。

## 比較条件と再現

- 基準実装・変更案: 親run `adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f` の派生表（同じ車両・同じ76フレーム）と、祖父runの2枚の俯瞰背景を再利用する。各射影の `u,v` を俯瞰画像内の同一公称8.5 m×50 m座標に描く。
- 指標・単位・成功基準: 各系列の最大推定速度（km/h）、発生frame、位置（奥からの公称縦座標m）、両最大値の差（km/h）を図と表に記す。最高点を明瞭な印で示し、同一フレームとは限らないことを明記する。
- source_id・データ版・件数・除外条件: 親runの派生CSV `tables/speed_distance_comparison.csv` を入力。対象はframe 1542–1617の76点のみ。俯瞰背景 `manual_birdseye.png` / `auto_candidate_birdseye.png` は祖父runから参照。原動画・生exportは複製しない。
- コード版・未コミット差分・環境・seed: git SHA・Python/依存版・成果物ハッシュをmanifestに記録。乱数なし。既存の未コミット変更を維持する。
- 実行コマンド・作業ディレクトリ: `python docs/analysis-vault/80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/code/plot_birdseye_max_speed.py`、repo root。

## 結果と検証

- 観測事実と根拠artifact_id: [俯瞰比較図](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/figures/manual_auto_birdseye_max_speed.png) (`artifact-birdseye-max-speed-figure`) を作成。手動4点での最高推定速度は80.70 km/h（frame 1542、奥から2.8 m）、自動候補4点では85.54 km/h（frame 1617、奥から47.2 m）。共通76フレームの軌跡を同じ速度色尺度で道路の俯瞰背景に重ね、星印が各最高点。[位置表](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/tables/peak_locations.csv) (`artifact-birdseye-max-speed-table`) と[集計](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/tables/peak_summary.json) (`artifact-birdseye-max-speed-summary`) を保存。
- 同時刻の照合: 手動ピークのframe 1542では自動候補76.14 km/h。自動ピークのframe 1617では手動76.99 km/h。各系列の最高値同士の差は自動候補−手動=+4.84 km/hだが、発生時刻は異なる。
- 方法: 親runの派生CSVの `u,v`（公称m）を、祖父runの俯瞰画像（272×1600 px、名目8.5 m×50 m）へ重ねた。背景は21フレーム中央値の路面で、当該車両の画像ではない。両ピークは対象区間の端点。速度算出は親runの局所回帰（前後0.5秒）に従い、端点では片側窓になる。
- 検証コマンド・結果: 入力CSVとpeak JSONの最大値、frame、位置、同時刻速度の一致を検証。背景寸法をコードで確認。PNGを開いて軸・単位・星印・凡例・注記を目視確認。`python -m pytest tests/test_analysis_vault.py -q` を実行。
- 失敗・効果なし・限界: 自動候補は実寸未測量。速度軌跡の遠方側には検出座標の大きな揺れが見える。両最大値は端点の片側窓推定であり、車両の真の最高速度や加減速の証拠ではない。
- 採用／保留／棄却と理由: 俯瞰比較図は位置・発生時刻を説明する資料として採用。速度校正の優劣判断は保留。
- 次の最小実験: 路面実測距離と独立した実速度を照合し、双方の誤差を計測する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/slides/slide-card.md)
- [俯瞰比較図](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/figures/manual_auto_birdseye_max_speed.png)・[ピーク位置表](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/tables/peak_locations.csv)・[条件](../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/config/conditions.json)
- 試験コードは `../80-Artifacts/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc/code/`、図表は同じ実験の `figures/` へ保存。
