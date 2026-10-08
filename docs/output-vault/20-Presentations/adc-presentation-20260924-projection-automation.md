---
note_id: adc-presentation-20260924-projection-automation
vault_kind: output
note_type: presentation
title: 射影変換の自動化：現状と検証結果
summary: 中央破線の端点差と射影後の距離差、手動・自動候補の領域・速度を8枚で説明。
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal, source-adc-homography-profile-cf-v5-720]
artifact_ids: [artifact-homography-edge-removal-metrics, artifact-center-dash-auto-manual-figure, artifact-center-dash-auto-manual-pairs, artifact-center-dash-auto-manual-summary, artifact-center-dash-projected-points-figure, artifact-center-dash-projected-points-table, artifact-center-dash-projected-points-summary, artifact-projection-region-auto-manual-photo, artifact-projection-region-auto-manual-corners, artifact-projection-region-auto-manual-summary, artifact-region-birdseye-comparison, artifact-region-birdseye-summary, artifact-manual-auto-speed-distance-figure, artifact-manual-auto-speed-distance-table, artifact-manual-auto-speed-distance-summary, artifact-birdseye-max-speed-figure, artifact-birdseye-max-speed-table]
revision: 3
status: completed
validation_status: verified
updated: 2026-09-25
---

# 射影変換の自動化：現状と検証結果

- [編集可能なPPTX（発表用）](../80-Artifacts/adc-presentation-20260924-projection-automation/adc_projection_manual_auto_comparison_20260925_revised.pptx)
- [閲覧用PDF（発表用）](../80-Artifacts/adc-presentation-20260924-projection-automation/adc_projection_manual_auto_comparison_20260925_revised.pdf)
- [全8枚のプレビュー](../80-Artifacts/adc-presentation-20260924-projection-automation/preview_20260925_revised.png)
- [発表者メモ](../80-Artifacts/adc-presentation-20260924-projection-automation/presenter-notes_20260925_revised.md)
- [スライド別のrun/artifact対応と原図ハッシュ](../80-Artifacts/adc-presentation-20260924-projection-automation/sources_20260925_revised.json)
- [生成コード](../80-Artifacts/adc-presentation-20260924-projection-automation/make_slides_20260925_revised.py)・[検証結果](../80-Artifacts/adc-presentation-20260924-projection-automation/delivery_20260925_revised.json)

## 構成

1. 全体要約：自動候補はローカルで作れるが、物理校正は未完。
2. 中央破線：明瞭7本は7/7検出、手前端の画素誤差は中央値1 px・最大19 px。
3. 射影後の端点差：明瞭7本の縦方向差は中央値0.038 m・最大1.537 m。距離補正前で、目視は真値ではない。
4. 射影領域：手動4点と自動路面候補4点の形状差。
5. 俯瞰：同じ公称矩形に展開した2つの見え方。
6. 速度：同一車両76フレームの速度対進行距離。
7. 最大値：手動80.70 km/hと自動候補85.54 km/hの発生位置。
8. ローカル処理と実距離検証の次の手順。

発表で使った図表は分析Vaultの各runに保持し、Output Vaultには重複コピーしていない。各スライドのrun ID・artifact IDは `sources_20260925_revised.json`。自動候補の実寸と真の速度は未測量で、校正の精度としては扱わない。

検証：PPTX 8枚とPDF 8ページ、発表者メモ、原図6件のハッシュ、スライド別artifact IDを照合。全ページをPDFプレビューで確認。実験結果そのものの追加検証はしていない。

## 旧版

2026-09-24の[7枚のPPTX](../80-Artifacts/adc-presentation-20260924-projection-automation/adc_projection_manual_auto_comparison.pptx)と[PDF](../80-Artifacts/adc-presentation-20260924-projection-automation/adc_projection_manual_auto_comparison.pdf)を保持する。

2026-09-25の[カード型の8枚のPPTX](../80-Artifacts/adc-presentation-20260924-projection-automation/adc_projection_manual_auto_comparison_20260925.pptx)と[PDF](../80-Artifacts/adc-presentation-20260924-projection-automation/adc_projection_manual_auto_comparison_20260925.pdf)も保持する。
