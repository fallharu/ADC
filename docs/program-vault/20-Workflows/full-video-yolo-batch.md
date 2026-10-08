---
note_id: adc-full-video-yolo-batch
vault_kind: software
note_type: workflow
title: 任意の複数動画を全編YOLO追跡する
summary: フォルダー・個別動画・動画別メタデータから全フレームを処理し、既存DBへ別runで追記する。
revision: 1
status: current
updated: 2026-10-08
---

# 複数動画の全編処理

`scripts/batch_full_video_yolo.py` は比較実験用の実行入口。現行画面のフォルダー処理は `Source_code/modules/inference.py::process_video_folder`。

まず `python scripts/new_analysis_run.py multi-video-yolo --title "複数動画の全編YOLO処理"` で保存先を作る。以下の `RUN_DIR` は作成された `artifacts` パスに置換する。

```powershell
# フォルダーを再帰的に探索。--folder は複数回指定できる。
.venv/Scripts/python.exe scripts/batch_full_video_yolo.py --folder D:\Videos --run-dir RUN_DIR --dry-run
.venv/Scripts/python.exe scripts/batch_full_video_yolo.py --folder D:\Videos --run-dir RUN_DIR --resume

# 個別動画、または動画別の道路条件・校正プロファイルを指定。
.venv/Scripts/python.exe scripts/batch_full_video_yolo.py --video D:\Videos\a.mp4 --video D:\Videos\b.mov --run-dir RUN_DIR
.venv/Scripts/python.exe scripts/batch_full_video_yolo.py --sources sources.json --run-dir RUN_DIR --resume
```

`sources.json` の例。相対パスはJSONの所在を基準に解決する。`source_id` は重複しない英数字・ハイフン・アンダースコア。道路条件や撮影年は省略可能で、ファイル名から推測しない。

```json
{"sources": [
  {"source_id": "video-01", "path": "a.mp4", "road_type": "widened", "collection_year": 2026, "calibration_profile": "profile_a"},
  {"source_id": "video-02", "path": "b.mov"}
]}
```

- MP4 / AVI / MOV / MKV / M4V / WEBM / MPG / MPEG / WMVを探索。`--include` は任意の名前・相対パスglob、`--exclude` は追加除外。`--no-recursive` で直下だけに限定する。
- 既定では名前にbbox / bike_clips / annotated / trackedを含む動画を除外。これらも対象にする場合は `--include-derived`。個別動画・JSONで明示した入力にはこの自動除外を適用しない。
- FPS、解像度、フレーム数を各動画から取得。全フレームを連続追跡し、動画間でモデルとトラッカーを初期化する。読めない動画・途中で止まった動画は失敗として残し、次の動画へ進む。
- 既定はYOLO26x、ByteTrack、conf=0.20、IoU=0.50、imgsz=960、stride=1、half=False、seed=0。モデル・トラッカー・しきい値・画像サイズ・デバイスは引数で変更可能。
- クラスはCOCOのbicycle=1、car=2、motorcycle=3、bus=5、truck=7を使う。モデルを変更する場合も、このID対応を持つ重みを使用する。
- `--resume` は動画内容・モデル・条件・実行コードのハッシュとDBの完了状態／件数が一致した動画だけ再利用する。失敗動画は新runで再試行する。条件変更は新しい実験に保存する。
- ライブラリ更新、完了した入力の版変更、別条件の再実験は新しいrunを作る。環境の依存ライブラリ版はmanifestにも保持する。
- 生のBBOXは既存アプリDBへ新規runとして追記。実験フォルダーには入力の参照、条件、進捗、派生集計を保持。原動画・生export・DBを複製しない。
- 校正の指定は動画ごとの参照情報として保持する。この入口は速度・離隔を算出しない。校正が未指定の動画でも検出・追跡は可能。A・Bの校正を他の動画へ自動転用しない。
- 全編処理の完了、追跡ID数、ID欠損数は精度指標とは区別する。CVATとの比較には対応するアノテーションとフレーム同期の確認が必要。独立した実測による速度・離隔の精度は別途検証する。

検証: `python -m pytest tests/test_batch_full_video_yolo.py tests/test_normalized_detection_schema.py tests/test_yolo_cvat_dataset.py -q`。異なるFPS／解像度の取り扱い、動画間のモデル初期化、失敗後の継続、途中終了の失敗判定、DBと一致した再開、重複入力・不正IDの拒否を確認する。
