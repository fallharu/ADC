---
note_id: adc-result-20261008-full-video-yolo-cvat
vault_kind: output
note_type: result
title: 元動画全体のYOLO追跡とCVAT参照比較
summary: 全12613・12643フレームのYOLO処理を完了。対応先ID変化17回のうち10回はcar/truckの重畳検出を伴う。部分CVAT参照での診断であり追跡・実速度の絶対精度は未検証。
revision: 1
status: unverified
validation_status: unverified
updated: 2026-10-08
source_run_ids: [adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089]
artifact_ids: [artifact-full-tables-full_video_summary-json, artifact-full-tables-id_change_candidates-csv, artifact-full-tables-id_change_candidate_diagnosis-csv, artifact-full-figures-full_video_reference_comparison-png]
---

# 元動画全体のYOLO追跡とCVAT参照比較

検出枠を重ねる前の全体動画A/BにYOLO26x・ByteTrackを実行した。動画内で追跡状態を維持し、間引き・切出しをせず全フレーム処理した。アプリDBの既存結果を維持し、新規runに保存。

| 動画 | 全処理フレーム | アプリrun ID | 保存検出行 | CVAT参照トラック | 対応先ID変化候補 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A（未拡幅） | 12613 | 100669 | 21963 | 8 | 3 |
| B（拡幅） | 12643 | 100670 | 10659 | 4 | 14 |

- Aの12実キーフレームで重畳版との0フレーム対応を支持。BはCVATタスク作成時と同じ全体動画。30fps、1280×720、confidence=0.20、IoU=0.5、imgsz=960。
- 参照枠への追跡付き対応（IoU>=0.5）：Aのcar 1830/1930、自転車285/1122。Bのcar 997/1911、自転車197/1863。部分注釈・補間を含むため全車両の追跡精度とは解釈しない。
- 対応先IDの変化17回のうち10回では、変化先フレームに旧・新IDのcar/truck枠が同時に存在し、IoU 0.97以上で重なった。純粋なIDスイッチ件数とは区別する。候補フレームと診断表を保存。
- 車速は両方式で同じBBOX測定点・同じ路面校正・0.2秒窓を使い、同じ車両の共通フレームから比較。旧runのタイヤ優先点や切出し標本と条件が異なるため、旧群中央値差を改善量としない。
- 全フレーム処理、保存検出行数、同フレーム・追跡IDの非重複、正規化DBへの新run反映を確認。速度計算の既存テスト8件と対応の単純例を確認。対応の目視確認・独立実測真値との照合は未了。

根拠は [実験記録](../../analysis-vault/10-Experiments/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089.md)、[比較図](../../analysis-vault/80-Artifacts/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089/figures/full_video_reference_comparison.png)、同runの `tables/` と `manifest.json`。原動画・DB・CVAT exportをVaultへコピーしていない。
