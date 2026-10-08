# プログラム概要

## アプリケーション構成
- `Source_code/app.py` で Flask アプリを初期化し、環境変数からアップロード先を決定したうえで Blueprint `main` を登録します。テンプレートは `templates` ディレクトリを参照し、アプリのシークレットキーとアップロード設定をまとめています。【F:Source_code/app.py†L2-L17】
- ルートビュー (`/`) では処理履歴のサマリ、直近の Run、フォルダ単位の集計を取り込み、YOLO 推論や後処理の進捗も合わせてダッシュボード表示します。【F:Source_code/routes.py†L2742-L2759】
- `/upload` は動画のアップロードと、あらかじめ登録したフォルダリンクの生成に対応しています。対応拡張子判定後に `uploads` 配下へ保存し、完了メッセージを返します。【F:Source_code/routes.py†L2835-L2913】
- `/detect` ではアップロード済みファイルや登録フォルダから推論を起動します。フォルダ一括処理の場合は進行状況のコールバックを組み合わせ、単一動画の場合はバックグラウンドスレッドで YOLO 推論を実行し、完了・エラーを進捗状態に反映します。【F:Source_code/routes.py†L2915-L3180】

## 推論・後処理パイプライン
- YOLO 推論は `Source_code/modules/inference.py` の `process_video` が担い、動画のメタデータ取得、処理ログ作成、モデル選択（環境変数を含むフォールバック付き）、推論ループ、Detection テーブルへの一括挿入、サマリファイル出力までを一連で処理します。【F:Source_code/modules/inference.py†L477-L755】
- 推論後の後処理は `run_postprocess_pipeline_sync` で7段階（グループ ID、運動学、追い越し、接近/離隔、白線距離、車両間距離、TTC）を順次実行し、成功/失敗を集計する構造になっています。【F:Source_code/modules/inference.py†L487-L506】

## バッチ処理とフォルダ設定
- `/detect` のフォルダモードでは `process_video_folder` を呼び出し、フォルダ内の動画探索、個別ファイルの開始/完了、CSV バンドルの生成状態をコールバックで UI へ流し込みます。処理数やエラー有無をメッセージ化し、結果を画面表示用に整形しています。【F:Source_code/routes.py†L2933-L3106】
- フォルダごとの自動後処理や CSV 出力の設定は `save_folder_settings` を通じて読み書きされ、`ResolvedFolderSettings` を受け取ったポストプロセス登録処理を備えています。【F:Source_code/routes.py†L2933-L3090】

## キャリブレーション機能
- `/calibration` 系エンドポイントは Run ID とプロファイル名を入力として動画のメタデータ取得、フレーム画像の提供、保存済みキャリブレーションデータの読み出しや距離テストの実行を行います。入力エラー時は UI/JSON 双方でメッセージを返し、動画の有無や候補パスもレスポンスに含めます。【F:Source_code/routes.py†L3217-L3340】
