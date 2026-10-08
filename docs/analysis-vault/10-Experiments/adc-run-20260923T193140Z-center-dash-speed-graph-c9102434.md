---
note_id: adc-run-20260923T193140Z-center-dash-speed-graph-c9102434
vault_kind: analysis
note_type: experiment
title: "中央破線の自動・目視差を速度グラフで示す"
summary: "同じ車両軌跡で中央破線の自動・目視端点を速度へ換算。差の絶対値中央値1.71 km/h、最大3.71 km/h。周期一定仮定の感度試算。"
run_id: adc-run-20260923T193140Z-center-dash-speed-graph-c9102434
parent_run_id: adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-center-dash-speed-graph, artifact-center-dash-speed-comparison, artifact-center-dash-speed-summary]
revision: 2
status: completed
validation_status: verified
updated: 2026-09-23T19:31:40+00:00
---

# 中央破線の自動・目視差を速度グラフで示す

## 問い・仮説

- 解決したい問題: 前runの端点差が、同じ映像の推定速度にどの程度効くかグラフで確認する。
- 仮説: 一部の端点ずれと遠方の1 px差が、場所によって速度曲線に大きく反映される。
- 対象: 前runの自動・目視端点表、7月20日同動画の既存車両検出軌跡、現行ホモグラフィ。距離補正の設定は変更しない。

## 比較条件と再現

- 比較: 同じ車両・同じ時刻の画像軌跡を現行ホモグラフィで射影し、中央破線周期を一定と仮定した相対距離補正を自動端点と目視端点それぞれで計算。実物の周期が未測量なので、両者を共通の10.4302 mへ正規化する。この値は最初の2周期ずつの射影値の中央値であり実測距離ではない。
- 指標: 車両の縦方向速度 (km/h) の時系列と、場所ごとの自動・目視による速度差。両手法の差が視覚的に追える図と集計表を作る。独立速度真値がないため改善・悪化の判定はしない。
- 除外: 探索帯で切れた手前1本・遠端1本と探索帯外2本。前runで明瞭と判定した7本を使用。速度軌跡が同じ映像で得られなければ、実測速度と偽らず相対速度倍率のみ描く。
- 再現: コード・条件・表・図を本runの `80-Artifacts/` に保存し、元の検出CSVや動画はコピーしない。

## 結果と検証

- データ：同じG1541動画の検出CSVから `yolo26x` の車 `track_id=112` を選択。29.970 fps、道路位置4.61～82.45 mの軌跡109点を利用。フレーム間隔は最大2フレーム。既存CSVの `speed_km_h` はこのtrackで0のため使用せず、`measure_x/y` を射影した位置の±0.5秒窓内線形回帰の傾きから縦速度を再計算。元CSVと元動画をVaultへ複製せず、SHAは[条件](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/config/conditions.json)へ記録。
- 方法：親実験で「明瞭」と判定した7本M01～M07のみ使用。隣接端点間の射影周期をPCHIPで位置方向へ補間し、共通基準周期÷局所周期を積分して相対距離を作った。同じ109フレームの生射影・自動端点補正・目視端点補正から速度を計算した。[速度グラフ](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/figures/auto_manual_speed_graph.png) (`artifact-center-dash-speed-graph`) の上段は速度、下段は自動－目視の差。薄橙は現行校正線の最奥基準点42.91 mより先。
- 結果：[速度表](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/tables/speed_comparison.csv) (`artifact-center-dash-speed-comparison`) と[集計](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/tables/summary.json) (`artifact-center-dash-speed-summary`) に保存。109点で、生射影速度中央値75.58 km/h、自動端点補正66.34 km/h、目視端点補正64.23 km/h。自動－目視差の絶対値中央値1.71 km/h、最大3.71 km/h。校正線基準内の67点は差の絶対値中央値0.81 km/h、基準外の42点は3.09 km/h。
- 注意：30～40 m付近の大きな谷は生射影にもあり、車両追跡・測定点の揺れが含まれる。遠方の生射影速度の上昇を校正誤差と断定できない。破線の物理間隔一定、車両の実速度、目視端点の真値はいずれも未検証。図は自動と目視の端点の**速度への感度**であり、補正後速度の正しさや改善効果を示さない。
- 再現：HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、作業ツリーdirty。対象試験コードは本runの `code/` に保存。リポジトリ直下で `python docs/analysis-vault/80-Artifacts/<run_id>/code/plot_dash_speed_sensitivity.py --detections <detections_csv> --profile <profile_json> --paired docs/analysis-vault/80-Artifacts/<parent_run_id>/tables/paired_near_edges.csv --video-name 2_20250720_000G1541_bike_clips.mp4 --fps 29.97002997002997 --track-id 112 --half-window-s 0.5 --out-dir docs/analysis-vault/80-Artifacts/<run_id>/tables` を実行。条件・正確な入力パス・ハッシュは上記conditionsとmanifest。乱数なし。
- 検証：グラフを元表と照合し、対応する車両と白線7本を確認。`python -m pytest tests/test_analysis_vault.py -q` は6件成功。manifestの成果物ハッシュを照合した。`verified` は集計・保存の検証を指し、独立した実速度検証ではない。
- 採否：速度への影響を示す説明図として採用。現行アプリの速度補正を変える判断は保留。次は同じ区間の破線周期と車両速度を独立実測し、複数trackで誤差を比較する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/slides/slide-card.md)
- [速度グラフ](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/figures/auto_manual_speed_graph.png)・[速度表](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/tables/speed_comparison.csv)・[条件](../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/config/conditions.json)
- 試験コードは `../80-Artifacts/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434/code/`、図表は同じ実験の `figures/` へ保存。
