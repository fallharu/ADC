---
note_id: adc-presentation-20261006-manual-cvat-auto-yolo
vault_kind: output
note_type: presentation
title: 手動（CVAT）と自動（YOLO）の比較
summary: 測定方法、車速分布、横方向点間距離、対応比較の必要性を6枚で説明。YOLOの車速中央値は3.7〜4.2km/h低いが、車両対応と絶対精度は未検証。
revision: 2
status: stale
validation_status: unverified
updated: 2026-10-08
source_run_ids: [adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545]
---

# 手動（CVAT）と自動（YOLO）の比較

2026年10月8日：YOLOを元動画全体に再実行したため、本資料は切出し結果を使った過去条件の説明として保持する。現在の全体処理結果は [[../10-Results/adc-result-20261008-full-video-yolo-cvat]]。このPPTXの群中央値差を全体動画の対応車両比較として再利用しない。

- [PowerPoint 6枚](../80-Artifacts/adc-presentation-20261006-manual-cvat-auto-yolo/manual_cvat_auto_yolo_20261006.pptx)
- [PDF閲覧版](../80-Artifacts/adc-presentation-20261006-manual-cvat-auto-yolo/manual_cvat_auto_yolo_20261006.pdf)
- [発表者ノート](../80-Artifacts/adc-presentation-20261006-manual-cvat-auto-yolo/presenter-notes.md)
- [スライドと根拠IDの対応](../80-Artifacts/adc-presentation-20261006-manual-cvat-auto-yolo/sources.json)
- [生成コード](../80-Artifacts/adc-presentation-20261006-manual-cvat-auto-yolo/build_slides.cjs)

1. 手動BBOXと保存済みYOLO測定点の違い
2. 共通の路面校正・0.2秒速度窓と、測定点定義の違い
3. 車速中央値：AでCVAT 59.42 / YOLO 55.70、Bで57.11 / 52.91 km/h
4. 各車両の速度中央値を1標本とした箱ひげと全18標本
5. 横方向点間距離：CVAT 1.390 / YOLO 1.705 m、各1件
6. 同一車両・同一フレーム・統一測定点による精度評価

既存runの匿名派生集計の二次説明。元動画、DB、CVAT exportを再取得・複製せず、新たなYOLO推論・実験は行っていない。元集計のハッシュを確認。標本が対応していないため、群中央値差は車両単位誤差や系統的な偏りとは解釈しない。横方向点間距離は車体端間の安全離隔ではない。絶対精度の検証には独立した実測真値が必要。

表、棒グラフ、箱ひげの構成要素とテキストはPowerPointで編集可能。全6枚をPowerPointで開きPNGとPDFへ出力して目視確認。発表資料の動作確認と、推定速度・距離の実測精度検証は区別し、数値の検証状態は親runの `unverified` を引き継ぐ。
