---
note_id: adc-presentation-20261008-multi-video-yolo
vault_kind: output
note_type: presentation
title: CVATとYOLOの比較：全編・複数動画と追跡課題
summary: 全9動画処理、手動と自動の違い、自転車の検出不足、ID変化、対応車速比較を8枚で説明。
revision: 1
status: current
validation_status: unverified
accuracy_status: unverified
updated: 2026-10-08
source_run_ids: [adc-run-20261007T212800Z-multi-video-yolo-e795a922, adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089]
---

# CVATとYOLOの比較：全編・複数動画

- [PowerPoint 8枚](../80-Artifacts/adc-presentation-20261008-multi-video-yolo/manual_cvat_auto_yolo_multi_video_20261008.pptx)
- [PDF閲覧版](../80-Artifacts/adc-presentation-20261008-multi-video-yolo/manual_cvat_auto_yolo_multi_video_20261008.pdf)
- [発表者ノート](../80-Artifacts/adc-presentation-20261008-multi-video-yolo/presenter-notes.md)
- [スライドと根拠の対応](../80-Artifacts/adc-presentation-20261008-multi-video-yolo/sources.json)
- [生成コード](../80-Artifacts/adc-presentation-20261008-multi-video-yolo/build_slides.cjs)

1. 2動画から9動画の全編処理へ拡張
2. 手動BBOXとYOLO検出／ByteTrack追跡、共通の測定点と校正
3. 任意動画の選択、動画別FPS／解像度、追跡初期化、継続／再開
4. 9動画のフレーム・検出BBOX・ID種類数・ID欠損率
5. CVAT参照内の自転車追跡不足：A25.4%／B10.6%（各1台）
6. ID変化17候補のうち10候補で旧・新ID同時存在と重複BBOX
7. 同一車両・対応フレームの車速中央値（車10台中9台、507フレーム）
8. 追加動画の参照注釈と動画別校正を用いた精度評価へ

全8枚をPowerPointで開き、PDF／PNGへ出力して確認。表・棒グラフ・図形・文字は編集可能。発表資料の動作確認とモデル・速度・離隔の精度は区別する。追跡率は部分注釈・補間を含む参照内での値で、全動画の再現率ではない。追加7動画の精度は未評価。切出し動画を用いた古い群中央値差は再利用していない。
