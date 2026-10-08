---
note_id: adc-run-20260923T195056Z-projection-region-auto-manual-48758496
vault_kind: analysis
note_type: experiment
title: "射影変換領域の手動設定と画像からの自動推定を写真で比較"
summary: "同じ道路写真に手動4点領域と路面色から推定した候補領域を重ねた。形状重なり65.4%、手前左の自動境界は画面で切れる。"
run_id: adc-run-20260923T195056Z-projection-region-auto-manual-48758496
parent_run_id: adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-projection-region-auto-manual-photo, artifact-projection-region-auto-manual-corners, artifact-projection-region-auto-manual-summary]
revision: 2
status: completed
validation_status: verified
updated: 2026-09-23T19:50:56+00:00
---

# 射影変換領域の手動設定と画像からの自動推定を写真で比較

## 問い・仮説

- 解決したい問題: 手動設定の4点で囲った射影領域と、画像から機械的に推定できる道路領域の位置差を写真上で示す。
- 仮説: 手動領域は道路の外縁より内側／外側にずれた部分があり、自動推定でも白線の摩耗・遠方の小ささによる不確実性がある。
- 対象: 7月20日G1541動画の21フレーム中央値、現行 `2_250720_cf_v5.json` の4画像点。アプリの校正設定は変更しない。

## 比較条件と再現

- 方法: 手動側はprofileの `scale.homography.image_points` をそのまま使う。自動側は同じ写真の白線・路面エッジから道路境界を推定し、同じ画像高さで4点の比較領域を作る。自動側が手動側を種にする場合はその依存を明記する。
- 指標: 両領域の4画像点(px)、同じ高さでの境界差(px)、重なり率、失敗・不確実な辺。写真には領域を別色と半透明で重ねる。
- 成功基準: 4点と領域境界が目視で追え、手動・自動の定義差と限界が図に記録されること。見た目の重なりを射影精度の証明にしない。
- 保存: 元動画・生exportはVaultへコピーせず、実験コード、座標表、図、条件、検証結果を保持する。

## 結果と検証

- [比較写真](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/figures/manual_vs_auto_projection_region.png) (`artifact-projection-region-auto-manual-photo`) を作成。ピンク実線は現行profileの射影変換4点を囲った範囲、青緑破線は21フレーム中央値画像から彩度の低い路面を抽出した候補範囲。自動側は手動側のx座標を使わず、比較する手前・奥の画像高さだけ同じにした。
- [4隅の表](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/tables/region_corners.csv) (`artifact-projection-region-auto-manual-corners`): 手前左は手動(283,806)・自動(0,806)で自動境界が画面端で切れる。手前右はx1230対1136（−94 px）、奥右は1262対1253（−9 px）、奥左は828対620（−208 px）。[集計](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/tables/summary.json) (`artifact-projection-region-auto-manual-summary`) の形状重なり率は65.4%。これは形の一致度であり、射影距離の誤差率ではない。
- 自動側の方法：21フレーム中央値、HSV彩度<75かつ明度>65、画像高さ±5 pxの行中央値、横方向σ=6 pxの平滑化、31 pxの穴埋め。その高さの画像中央から連続する路面候補の左右端を取った。[条件](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/config/conditions.json) に入力SHA・閾値・依存を保存。
- 限界：手動は物理幅8.5 m・長さ50 mを割り当てた**校正用四辺形**。自動は色で抽出した**見える路面の候補**で、両者は同じ物理地点の4点とは限らない。手前左は写真外まで続くため、自動側から4点ホモグラフィは確定できない。撮影条件・白線・肩・影による色誤判定もあり得る。自動候補に物理距離を付けてアプリへ反映していない。
- 再現：HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、作業ツリーdirty。試験コードは本runの `code/` に保持。リポジトリ直下で `python docs/analysis-vault/80-Artifacts/<run_id>/code/compare_projection_regions.py --video <source_video> --profile output/calibrations/2_250720_cf_v5.json --out-dir docs/analysis-vault/80-Artifacts/<run_id>/tables` を実行。入力動画は既存のuploadsのまま、Vaultへ複製しない。乱数なし。
- 検証：重ね図と4隅表を目視照合し、手前左の画面切れを確認。manifestの成果物SHAと分析Vaultテストを確認。`verified` は今回の画像処理と保存の検証であり、自動校正の正しさを意味しない。
- 採否：手動領域と路面候補の見え方を比較する図として採用。自動ホモグラフィの採用は保留。次は同じ物理地点の左右4点以上を画像で同定し、実測した幅・縦距離と対応付けて射影行列を検証する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/slides/slide-card.md)
- [比較写真](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/figures/manual_vs_auto_projection_region.png)・[4隅の表](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/tables/region_corners.csv)・[条件](../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/config/conditions.json)
- 試験コードは `../80-Artifacts/adc-run-20260923T195056Z-projection-region-auto-manual-48758496/code/`、図表は同じ実験の `figures/` へ保存。
