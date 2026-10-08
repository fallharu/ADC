---
note_id: adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f
vault_kind: analysis
note_type: experiment
title: "手動・自動射影領域の速度―進行距離比較"
summary: "同一車両の共通76フレームについて手動4点と自動候補4点から速度―進行距離を比較。速度差の絶対値中央値2.94 km/h。自動側は実寸未測量。"
run_id: adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f
parent_run_id: adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-manual-auto-speed-distance-figure, artifact-manual-auto-speed-distance-table, artifact-manual-auto-speed-distance-summary]
revision: 1
status: completed
validation_status: verified
updated: 2026-09-23T20:14:36+00:00
---

# 手動・自動射影領域の速度―進行距離比較

## 問い・仮説

- 解決したい問題: 手動4点と画像から抽出した自動候補4点で、同一車両軌跡の「進んだ距離―速度」曲線がどう変わるか可視化する。
- 原因の仮説: 射影変換領域が違うと、同じ画素の縦方向距離と局所速度が変わる。
- 対象コード: このrunの `code/plot_manual_auto_speed_distance.py` を新規作成。現行アプリの校正値は変更しない。

## 比較条件と再現

- 基準実装・変更案: 手動 `output/calibrations/2_250720_cf_v5.json` の4点と、自動候補 `adc-run-20260923T195056Z-projection-region-auto-manual-48758496` の4点を比較。両者とも公称幅8.5 m・長さ50 mの同一目標矩形へ射影。破線周期補正は適用しない。
- 指標・単位・成功基準: 横軸は対象区間開始からの縦方向の進行距離（各射影で算出、m）、縦軸は縦方向の局所線形回帰速度（km/h、前後0.5秒）。同一フレームだけを比較し、両領域内の連続した軌跡を使う。図・数値表・再現コードを保存する。
- source_id・データ版・件数・除外条件: `2_20250720_000G1541_bike_clips.mp4` の検出CSV（SHA-256 d616f077366fdb8a76b6cde4517f2421f0dadc91499c36e4fd0f36ffdb34e641）、29.97002997 fps。非対象動画、欠損座標、両方の射影領域に入らない点、連続区間外は除外。対象trackと件数は事前点検で決め、結果に記録。
- コード版・未コミット差分・環境・seed: git状態・Python/依存版をmanifestへ記録。決定論的処理で乱数なし。既存の未コミット変更は保持。
- 実行コマンド・作業ディレクトリ: `python docs/analysis-vault/80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/code/plot_manual_auto_speed_distance.py`、repo root。

## 結果と検証

- 観測事実と根拠artifact_id: [比較図](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/figures/manual_vs_auto_speed_distance.png) (`artifact-manual-auto-speed-distance-figure`) を作成。横軸は開始点から進んだ縦方向距離、縦軸は局所推定速度。下段は同一フレームでの自動候補−手動の速度差。車両track 112の連続76フレーム（frame 1542–1617、約2.50秒）を比較した。[派生表](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/tables/speed_distance_comparison.csv) (`artifact-manual-auto-speed-distance-table`) と[集計](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/tables/summary.json) (`artifact-manual-auto-speed-distance-summary`) を保存。
- 観測数値: 手動の終点進行距離46.77 m、自動候補46.80 m。速度中央値は手動66.62 km/h、自動候補66.02 km/h。同一フレーム速度差の絶対値中央値2.94 km/h、最大8.55 km/h。距離終点がほぼ同じでも途中の局所速度は異なる。
- 方法: 両4点を同じ公称8.5 m×50 m矩形へ射影。両領域内の共通点のみ。各時刻の前後0.5秒で射影縦座標の線形回帰勾配を求め速度に換算。横軸は開始点からの縦方向進行量。測定点の小さな逆行が両系列で6回ずつあり、横軸のみ単調回帰（PAVA）で補正した。縦軸の速度は生射影座標から求めた。破線周期の後段補正は適用していない。
- 検証コマンド・結果: `python -m py_compile` で両試験コードの構文確認。派生CSVの76フレーム連続性、両距離軸の単調性、速度の有限性、速度差の算術一致を確認。図を開いて軸・凡例・曲線・注記を目視確認。`python -m pytest tests/test_analysis_vault.py -q` は6 passed。
- 失敗・効果なし・限界: 自動候補は画像の路面輪郭から得た領域で、実寸の測量がない。手前左角はフレーム端で切れている。従って自動候補の約66 km/hを実測速度とみなせない。中央の速度の谷には追跡点の揺れや射影の影響が混じり、真の加減速とは断定できない。1車両・1動画の感度比較。
- 採用／保留／棄却と理由: 比較図は射影領域の選択による差の説明資料として採用。自動候補を速度校正として採用する判断は保留。
- 次の最小実験: 実測の路面基準点・実速度がある区間で両射影の距離誤差と速度誤差を独立評価する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/slides/slide-card.md)
- [比較図](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/figures/manual_vs_auto_speed_distance.png)・[派生表](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/tables/speed_distance_comparison.csv)・[条件](../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/config/conditions.json)
- 試験コードは `../80-Artifacts/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f/code/`、図表は同じ実験の `figures/` へ保存。
