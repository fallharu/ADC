# ADC

動画から車両・自転車を検出・追跡し、速度や追い越しを分析するアプリケーションです。

## コードと実行

- 現行アプリ: [Source_code](Source_code/)
- 起動: 依存関係とローカル設定を準備した環境で `python -m Source_code.app`、または `run.bat`
- システム説明: [ADC_System_Specification.md](docs/ADC_System_Specification.md)
- 依存関係: [docs/requirements.txt](docs/requirements.txt)

## 複数動画の全編YOLO処理

[batch_full_video_yolo.py](scripts/batch_full_video_yolo.py) は、フォルダー・複数の個別動画・動画別JSONを入力にして、全フレームを連続処理します。

[実行手順と条件](docs/program-vault/20-Workflows/full-video-yolo-batch.md) に、実験runの作成、入力の指定、再開方法、DBへの保存方法を記載しています。

## CVATとの比較と発表資料

- [複数動画の処理結果](docs/output-vault/10-Results/adc-result-20261008-multi-video-yolo.md)
- [全編動画のCVAT・YOLO比較](docs/output-vault/10-Results/adc-result-20261008-full-video-yolo-cvat.md)
- [発表スライドの説明・保存先](docs/output-vault/20-Presentations/adc-presentation-20261008-multi-video-yolo.md)

9本・113,607フレームの全編処理を確認しました。追加7本には対応するCVAT参照がないため、追跡精度は未検証です。既存2本のID変更候補は、正式なIDSW評価とは区別しています。

動画・DB・秘密設定・生データ・生成されたPPTX/PDFはローカルで保持し、Gitには含めません。
