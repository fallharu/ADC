---
note_id: adc-run-20261007T212800Z-multi-video-yolo-e795a922
vault_kind: analysis
note_type: experiment
title: 複数動画への全編YOLO処理の拡張
summary: 追加7本と既処理2本の計9本、全113,607フレームの処理を確認。追加動画の精度は未評価。
run_id: adc-run-20261007T212800Z-multi-video-yolo-e795a922
parent_run_id: adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089
source_ids: [video-A, video-B, video-C, video-D, video-E, video-F, video-G, video-H, video-I]
artifact_ids: [artifact-batch-tables-all_video_summary-json, artifact-batch-tables-batch_totals-json]
revision: 2
status: completed
validation_status: verified
accuracy_status: unverified
updated: 2026-10-08
---

# 複数動画への全編YOLO処理の拡張

## 問い・仮説

A/B固定の研究用実行コードを、任意の動画・複数フォルダーへ拡張する。動画ごとのFPS／解像度、独立した追跡状態、失敗後の継続と再開を確認する。

対象は `scripts/batch_full_video_yolo.py`。現行アプリの `Source_code/modules/inference.py::process_video_folder` には既存のフォルダー処理があり、画面や他のrunの挙動は変更していない。

## 比較条件と再現

- 親run: adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089。A/Bの結果は保持し、他の7動画を新規runで追加処理。
- 入力: 同じ保存先の全編元動画9本（入力名の区分：未拡幅3、near2、middle2、far2）。bbox描画版、切出し、編集動画を除外。参照は `config/inventory_all.json`、原動画は複製していない。
- 条件: YOLO26x + ByteTrack、conf=.20、IoU=.50、imgsz=960、stride=1、half=False、seed=0。車／自転車／二輪／バス／トラック。各入力の先頭から末尾まで連続追跡、動画間で初期化。
- 今回の動画は全て30fps、1280×720。A/Bの校正を追加動画へ転用していない。追加動画は速度／離隔を算出していない。
- 実行: `.venv/Scripts/python.exe scripts/batch_full_video_yolo.py --folder E:\VSC\ADC_mae --include 'overtake-full-*.mp4' --exclude '*000G1575*' --exclude '*000G2945*' --run-dir docs/analysis-vault/80-Artifacts/adc-run-20261007T212800Z-multi-video-yolo-e795a922 --resume`
- コード版と条件: manifestと `code/batch_full_video_yolo.py`、`config/conditions.json`。生検出はアプリDBの新規runのみ。

## 結果と検証

計9本、63.12分、113,607フレーム、延べ検出BBOX 217,167件。追加7本は全て完了。

全フレーム数の一致、新規runと正規化テーブルの集計件数、保存済み9runのBBOX・ID種類数・ID欠損数を確認。関連テスト14件が成功。異なるFPS／解像度、動画間のモデル初期化、失敗後継続、途中終了、再開、重複／不正IDの拒否を検証。

追加動画のCVAT参照はないため、追跡精度は未評価。ID数は実際の車両台数ではない。A/Bの参照比較は親runに由来し、自転車は各1台。ID変化17候補のうち10候補では旧・新ID同時存在とcar/truckの重複BBOXを確認したが、正式なIDSWとは扱わない。独立した速度／距離の真値は未評価。

採用: 任意入力、動画別メタデータ、追跡状態初期化、失敗継続と条件付き再開。次の検証は追加動画のCVAT注釈、重複クラスとID変化候補の目視分類、動画別校正と対応評価。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20261007T212800Z-multi-video-yolo-e795a922/manifest.json)
- [動画別集計](../80-Artifacts/adc-run-20261007T212800Z-multi-video-yolo-e795a922/tables/all_video_summary.csv)
- [全編処理の図](../80-Artifacts/adc-run-20261007T212800Z-multi-video-yolo-e795a922/figures/multi_video_processing.png)
- [スライド候補](../80-Artifacts/adc-run-20261007T212800Z-multi-video-yolo-e795a922/slides/slide-card.md)
