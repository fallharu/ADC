---
note_id: adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50
vault_kind: analysis
note_type: experiment
title: "中央破線の射影変換後の自動・目視端点比較"
summary: "同じ自動・目視端点を道路座標(u,v)へ射影。明瞭7本の縦差は中央値0.038 m、最大1.537 m。遠方では1 pxが1.54 mに相当。"
run_id: adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50
parent_run_id: adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-center-dash-projected-points-figure, artifact-center-dash-projected-points-table, artifact-center-dash-projected-points-summary]
revision: 2
status: completed
validation_status: verified
updated: 2026-09-23T19:44:36+00:00
---

# 中央破線の射影変換後の自動・目視端点比較

## 問い・仮説

- 解決したい問題: 画像上の端点差が、射影変換後の道路座標で何mの差になるかを見せる。
- 仮説: 画像上で1 pxの差でも遠方では縦方向に1 m以上の差となる。
- 対象: 前実験の自動・目視端点表、現行の7月20日用ホモグラフィ、既存 `Projection.to_world`。アプリ設定は変更しない。

## 比較条件と再現

- 方法: 両端点を同じ行列で道路座標(u,v)に変換し、点対ごとに横方向Δu、縦方向Δv、平面距離を計算する。鳥瞰図と差の図を保存する。
- 表示: 明瞭な7本を主表示し、探索範囲の境界で切れた手前と遠端の2本を別記号にする。探索範囲外で自動端点のない2本は対比較から除外する。
- 指標・単位: 元画像の点位置px、道路座標m、縦・横・平面差m。成功基準は再投影と表の値が一致し、除外理由が図から分かること。
- 再現: 試験コード・条件・図表・結果を本runに保持。元動画と生exportは複製しない。

## 結果と検証

- [射影後の点の比較図](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/figures/projected_auto_manual_points.png) (`artifact-center-dash-projected-points-figure`) に、道路横方向u・縦方向vの自動点と目視点を示した。左図の横・縦表示縮尺は異なるため、点間の実距離は[対応表](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/tables/projected_point_pairs.csv) (`artifact-center-dash-projected-points-table`) で読む。右図は縦方向の差、自動−目視。薄橙は現行校正線の最奥基準点42.91 mより先。
- 明瞭な7本M01～M07の縦方向差の絶対値は中央値0.038 m、最大1.537 m。M02は画像のx方向19 pxずれで縦方向+0.558 m、平面0.587 m。M06は画像で約1.41 pxずれて縦方向−1.045 m、M07は画像で1 pxずれて縦方向−1.537 m、平面1.541 m。[集計](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/tables/summary.json) (`artifact-center-dash-projected-points-summary`) を保存した。
- 探索帯で切れたM00は縦方向+2.433 m、遠端M08は−2.102 m。両者は境界の不完全な検出であり主要7本の誤差分布には入れない。M09・M10は探索帯外で自動点がなく、対比較できない。
- 変換は現行profileの4点ホモグラフィHによる**射影直後**の道路座標。後段の校正線による1D距離補正と白線周期補正は適用していない。前runと同じ画素座標を同じ行列に通したため、座標差は端点指定の違いによる。ただし目視端点は±3～5 px程度の主観幅があり、独立測量した真値ではない。
- 再現：HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、作業ツリーdirty。試験コードは本runの `code/` に保存。リポジトリ直下で `python docs/analysis-vault/80-Artifacts/<run_id>/code/plot_projected_dash_points.py --paired docs/analysis-vault/80-Artifacts/<parent_run_id>/tables/paired_near_edges.csv --profile output/calibrations/2_250720_cf_v5.json --out-dir docs/analysis-vault/80-Artifacts/<run_id>/tables` を実行。入力版と除外条件は[conditions](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/config/conditions.json)。乱数なし。
- 検証：表の全9組を同じ行列で再投影し、図の向きと差を目視確認。成果物ハッシュと分析Vaultテストを確認。`verified` は計算と保存の検証を指し、実距離の真値検証ではない。
- 採否：射影後の点差の説明図として採用。速度・距離補正の採用判断は保留。次はM02と遠方端点を複数人で再注釈し、実物の破線位置を測る。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/slides/slide-card.md)
- [射影後の図](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/figures/projected_auto_manual_points.png)・[点の対応表](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/tables/projected_point_pairs.csv)・[条件](../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/config/conditions.json)
- 試験コードは `../80-Artifacts/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50/code/`、図表は同じ実験の `figures/` へ保存。
