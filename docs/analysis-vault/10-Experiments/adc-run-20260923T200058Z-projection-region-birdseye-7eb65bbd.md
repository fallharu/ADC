---
note_id: adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd
vault_kind: analysis
note_type: experiment
title: "手動射影領域と自動路面候補の俯瞰画像"
summary: "同じ動画背景を手動4点と自動路面候補4点で俯瞰画像に変換。左が現行手動、右が自動候補。右の物理寸法は未検証。"
run_id: adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd
parent_run_id: adc-run-20260923T195056Z-projection-region-auto-manual-48758496
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-region-birdseye-comparison, artifact-region-birdseye-manual, artifact-region-birdseye-auto-candidate, artifact-region-birdseye-summary]
revision: 2
status: completed
validation_status: verified
updated: 2026-09-23T20:00:58+00:00
---

# 手動射影領域と自動路面候補の俯瞰画像

## 問い・仮説

- 問い：先ほど重ねた手動領域と自動路面候補を、それぞれ俯瞰へ写したとき道路の見え方がどう変わるか。
- 仮説：自動候補は手前左が画面端で切れ、手動領域とは道路幅・白線の位置が違って見える。
- 対象：同じ7月20日G1541動画の21フレーム中央値画像、現行profileの手動4点と親実験の自動候補4点。

## 比較条件と再現

- 比較方法：両4点を同じ幅8.5 m×縦50 m相当の矩形に射影し、同じ画素解像度で左右に並べる。自動候補の物理幅・距離は実測されていないため、そのm表示は**見た目を揃えるための仮置き**。距離補正や白線周期補正は行わない。
- 指標：画像出力、上下・左右の対応確認、入力4点と変換行列、格子と保存ハッシュ。成功基準は同じ画像・同じ出力寸法で再現し、上下方向が逆転しないこと。
- 保存：試験コード、条件、行列、比較画像を本runへ保存。元動画・生exportはコピーしない。

## 結果と検証

- [俯瞰比較図](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/figures/manual_vs_auto_birdseye.png) (`artifact-region-birdseye-comparison`) を作成。左は現行profileの手動4点、右は親実験で画像から抽出した路面輪郭候補4点。どちらも同じ21フレーム中央値画像から作り、同じ矩形へ写した。個別の[手動俯瞰PNG](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/figures/manual_birdseye.png) (`artifact-region-birdseye-manual`) と[自動候補俯瞰PNG](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/figures/auto_candidate_birdseye.png) (`artifact-region-birdseye-auto-candidate`) も保持した。
- 入力手動4点と親実験の自動候補4点を `cv2.getPerspectiveTransform` で幅272×高さ1600 pxへ変換し、`cv2.warpPerspective` で画像を引いた。画像の上が遠方、下が手前。名目幅8.5 m×縦50 mは**両画像を同じ表示寸法にする条件**であり、自動候補の実寸とは未確認。[条件](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/config/conditions.json) に入力版、解像度、方法を保存。
- [集計](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/tables/summary.json) (`artifact-region-birdseye-summary`) には両行列・入力4点・四隅の代数的再投影残差を保存。再投影残差は両者とも約3×10⁻¹² pxで、指定した4点を矩形へ写す計算が合っていることだけを示す。実距離や速度の精度を表す数値ではない。
- 観測：自動候補の白い中央破線は手動版より画像中央寄りに見える。右端の白線も位置・曲がり方が異なる。見た目だけでどちらが物理的に正しいか判断できない。
- 限界：自動候補の手前左点は画像左端x=0で切れた路面境界で、道路の実際の4点対応ではない。自動側には道路幅と縦距離の独立実測値がない。既存の線補正や破線周期補正も適用していない。したがって右図は形状比較用の仮の俯瞰画像であり、アプリの射影校正の代替にはしない。
- 再現：HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、作業ツリーdirty。試験コードは本runの `code/` に保存。リポジトリ直下で `python docs/analysis-vault/80-Artifacts/<run_id>/code/make_region_birdseye_comparison.py --video <source_video> --profile output/calibrations/2_250720_cf_v5.json --region-corners docs/analysis-vault/80-Artifacts/<parent_run_id>/tables/region_corners.csv --out-dir docs/analysis-vault/80-Artifacts/<run_id>/tables --pixels-per-meter 32` を実行。元動画はVaultに複製しない。乱数なし。
- 検証：両画像の寸法が一致し、上が遠方・下が手前であることを目視確認。入力4点がprofile・親実験の表と一致すること、成果物SHA、分析Vaultのテストを確認。`verified` は作図・保存の検証であり、物理的な俯瞰精度の検証ではない。
- 採否：形状比較用の俯瞰図として採用。自動候補への校正切替は保留。次は画面内で完結する左右4点以上の物理対応点と実測距離を用意する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/slides/slide-card.md)
- [俯瞰比較図](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/figures/manual_vs_auto_birdseye.png)・[条件](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/config/conditions.json)・[変換行列と検証値](../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/tables/summary.json)
- 試験コードは `../80-Artifacts/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd/code/`、図表は同じ実験の `figures/` へ保存。
