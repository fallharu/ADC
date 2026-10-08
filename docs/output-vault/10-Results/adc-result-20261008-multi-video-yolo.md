---
note_id: adc-result-20261008-multi-video-yolo
vault_kind: output
note_type: result
title: 全編YOLO処理を9動画へ拡張
summary: 既処理2本に7本を追加し全113,607フレームを処理。追加動画の追跡精度は未評価。
run_id: adc-run-20261007T212800Z-multi-video-yolo-e795a922
source_ids: [video-A, video-B, video-C, video-D, video-E, video-F, video-G, video-H, video-I]
artifact_ids: [artifact-batch-tables-all_video_summary-json, artifact-batch-tables-batch_totals-json]
revision: 1
status: unverified
execution_validation_status: verified
accuracy_status: unverified
updated: 2026-10-08
---

# 全編YOLO処理を9動画へ拡張

全9動画、63.1分、113,607フレームの全編処理が完了。A/Bの既存結果に追加7動画を統合した。YOLO26x + ByteTrack、conf=.20、IoU=.50、imgsz=960、stride=1、half=False。動画別に追跡状態を初期化し、新runとしてDBへ追記。

任意フォルダー・複数フォルダー・個別動画・動画別JSONを入力可能。FPSと解像度を各動画から読み、失敗後も継続する。完了済み入力の再開では内容・モデル・条件・コードとDB件数を照合する。関連テスト14件と全編フレーム数、9runのDB／正規化テーブル集計件数を確認した。

ID数は実際の車両台数ではなく、ID欠損率は検出精度ではない。追加7動画はCVAT未注釈で追跡精度未評価。速度・離隔も校正を自動転用せず未算出。A/B参照内では自転車追跡が不足し、car/truck重複とID変化候補が残る。部分注釈と補間を含む参照であり、独立した実測真値による絶対精度は未検証。

根拠run: `adc-run-20261007T212800Z-multi-video-yolo-e795a922`。参照比較の親run: `adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089`。図表とコードは分析Vaultの同じrunに保持し、元動画・DB・生exportは複製していない。

発表資料: [[../20-Presentations/adc-presentation-20261008-multi-video-yolo]]。実行手順: `docs/program-vault/20-Workflows/full-video-yolo-batch.md`。
