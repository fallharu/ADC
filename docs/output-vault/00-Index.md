---
note_id: adc-output-index
vault_kind: output
note_type: index
title: アウトプットの索引
summary: ADCの確認済み分析結果と発表資料のカタログ。未登録の結果は存在するものとして扱わない。
revision: 10
status: current
updated: 2026-10-08
---

# アウトプットの索引

| Note ID | Summary | Status | Note |
| --- | --- | --- | --- |
| `adc-output-entry` | 出力の検索と登録の入口。 | current | [[00-AI-Entry]] |
| `adc-register-output` | 検証状態と根拠を付けて出力を登録する。 | current | [[20-Workflows/register-output]] |

## 結果・発表資料

確認済みの発表資料を登録する。既存の分析結果は自動登録しない。

| Note ID | Summary | Status | Note |
| --- | --- | --- | --- |
| `adc-presentation-20260924-projection-automation` | 中央破線の画素差と射影後の距離差を分け、手動・自動候補の領域・速度と限界を8枚で説明。 | completed | [[20-Presentations/adc-presentation-20260924-projection-automation]] |
| `adc-presentation-20261004-yolo-cvat-speed-clearance` | 切出しYOLO結果による過去条件の資料。全体処理での比較へ移行したため再利用保留。 | stale | [[20-Presentations/adc-presentation-20261004-yolo-cvat-speed-clearance]] |
| `adc-result-20261004-yolo-cvat-speed-clearance` | 共通校正の速度窓363件を動画単位で分割。各条件1動画、距離val0件、絶対精度は未検証。 | unverified | [[10-Results/adc-result-20261004-yolo-cvat-speed-clearance]] |
| `adc-presentation-20261006-manual-cvat-auto-yolo` | 切出し条件の手動・自動比較6枚。元動画全体の再処理に伴い再利用保留。 | stale | [[20-Presentations/adc-presentation-20261006-manual-cvat-auto-yolo]] |
| `adc-result-20261008-full-video-yolo-cvat` | 全12613・12643フレームのYOLO処理とCVAT対応診断。ID変化候補は重複検出の影響を含み、絶対精度は未検証。 | unverified | [[10-Results/adc-result-20261008-full-video-yolo-cvat]] |
| `adc-result-20261008-multi-video-yolo` | 全編YOLO処理を9動画へ拡張。処理は検証、追加動画精度は未評価。 | unverified | [[10-Results/adc-result-20261008-multi-video-yolo]] |
| `adc-presentation-20261008-multi-video-yolo` | 全9動画処理とCVAT参照比較・追跡課題を8枚で説明。 | current | [[20-Presentations/adc-presentation-20261008-multi-video-yolo]] |
