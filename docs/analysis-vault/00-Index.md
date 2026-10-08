---
note_id: adc-analysis-index
vault_kind: analysis
note_type: index
title: 分析改善の索引
summary: 分析手順、相談、発表準備と実験ノートの短いカタログ。
revision: 30
status: current
updated: 2026-10-08
---

# 分析改善の索引

| Note ID | Summary | Status | Note |
| --- | --- | --- | --- |
| `adc-analysis-entry` | 分析作業の入口。 | current | [[00-AI-Entry]] |
| `adc-experiment-lifecycle` | 試験と再現用成果物の保存手順。 | current | [[20-Workflows/experiment-lifecycle]] |
| `adc-analysis-team` | 3担当の相談・引継ぎ・編集範囲。 | current | [[30-Orchestrators/team]] |
| `adc-interim-presentation` | 中間発表用の根拠と図表の準備。 | current | [[40-Presentation/interim-presentation]] |

## 実験

実験作成コマンドが追記する。完了・失敗・staleへの変更時は整理担当が該当行だけを更新する。

| Note ID | Summary | Status | Note |
| --- | --- | --- | --- |
| `adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea` | 合成ホモグラフィと実CVAT速度結果を区別して発表用に二次整理。実速度精度は未検証。 | completed | [[10-Experiments/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea]] |
| `adc-run-20260923T181319Z-homography-photo-correction-map-06312dba` | 変更前の実画像補正量。最大+8.52 m、近接2線で局所倍率28.5倍。現在のprofileは次のrunで更新。 | completed | [[10-Experiments/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba]] |
| `adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0` | 手前と最奥の校正線を各1本削除。最大局所倍率28.47→1.63倍。実測精度は未検証。 | completed | [[10-Experiments/adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0]] |
| `adc-run-20260923T190346Z-center-dash-current-calibration-2208517e` | 同日映像の中央破線候補2周期は射影直後10.87/10.03 m、線補正後11.25/6.97 m。実周期は未測量。 | completed | [[10-Experiments/adc-run-20260923T190346Z-center-dash-current-calibration-2208517e]] |
| `adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f` | 中央破線の目視比較：明瞭な7本は自動7/7、端点誤差中央値1 px・最大19 px。最手前は探索帯で切れる。 | completed | [[10-Experiments/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f]] |
| `adc-run-20260923T193140Z-center-dash-speed-graph-c9102434` | 同じ車両軌跡の速度グラフ：中央破線の自動・目視端点による試算差は中央値1.71 km/h、最大3.71 km/h。真速度は未測量。 | completed | [[10-Experiments/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434]] |
| `adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50` | 中央破線の射影後の自動・目視端点差：明瞭7本の縦差中央値0.038 m、最大1.537 m。遠方1 px差が約1.54 m。 | completed | [[10-Experiments/adc-run-20260923T194436Z-center-dash-projected-points-bcabaf50]] |
| `adc-run-20260923T195056Z-projection-region-auto-manual-48758496` | 手動4点の射影領域と色から推定した路面候補を同じ写真で比較。形状重なり65.4%、自動の手前左は画面端で切れる。 | completed | [[10-Experiments/adc-run-20260923T195056Z-projection-region-auto-manual-48758496]] |
| `adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd` | 手動射影領域と自動路面候補の俯瞰画像を並べて比較。自動側は実寸未検証の形状比較用。 | completed | [[10-Experiments/adc-run-20260923T200058Z-projection-region-birdseye-7eb65bbd]] |
| `adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f` | 同一車両で手動4点と自動候補4点の速度―進行距離を比較。自動側は実寸未測量。 | completed | [[10-Experiments/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f]] |
| `adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc` | 俯瞰画像に手動・自動候補の最高速度位置を表示。最高値の発生フレームは異なる。 | completed | [[10-Experiments/adc-run-20260923T201533Z-manual-auto-birdseye-max-speed-f98736dc]] |
| `adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad` | 同じ動画の25秒ずつをCVAT化して車の速度を暫定比較。自転車なし全フレーム確認と速度真値は未了。 | inconclusive | [[10-Experiments/adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad]] |
| `adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545` | 共通校正の速度窓363件をtrain262・val101へ動画分割。距離val0件、絶対精度は未検証。 | inconclusive | [[10-Experiments/adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545]] |
| `adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089` | 元動画A/Bの全12613・12643フレームにYOLO26xとByteTrackを連続実行。CVATとのフレーム対応、参照枠の対応率とID変化を集計。実測精度は未検証。 | inconclusive | [[10-Experiments/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089]] |
| `adc-run-20261007T212800Z-multi-video-yolo-e795a922` | 既処理2本＋追加7本の全編処理。全113,607フレーム、追加動画精度は未評価。 | completed | [[10-Experiments/adc-run-20261007T212800Z-multi-video-yolo-e795a922]] |
