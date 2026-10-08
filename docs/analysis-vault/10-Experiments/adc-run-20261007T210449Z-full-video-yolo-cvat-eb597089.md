---
note_id: adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089
vault_kind: analysis
note_type: experiment
title: "元動画全体のYOLO追跡とCVAT対応比較"
summary: "元動画A/Bの全12613・12643フレームにYOLO26xとByteTrackを連続実行。CVATとのフレーム対応、参照枠の対応率とID変化を集計。実測精度は未検証。"
run_id: adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089
parent_run_id: adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545
source_ids: []
artifact_ids: [artifact-full-tables-full_video_summary-json, artifact-full-tables-id_change_candidates-csv, artifact-full-figures-full_video_reference_comparison-png]
revision: 2
status: inconclusive
validation_status: unverified
updated: 2026-10-08
---

# 元動画全体のYOLO追跡とCVAT対応比較

## 問い・仮説

- 解決したい問題: 切出し動画のYOLO結果ではなく、CVATと同じ全体動画の冒頭から末尾まで連続追跡する。
- 原因の仮説: 切出しで失う追跡履歴、検出枠重畳、フレーム対応不一致が比較に影響している可能性。
- 対象コード: run内 `code/full_video_yolo.py`、既存 `scripts/build_yolo_cvat_speed_clearance.py`、`scripts/analyze_cvat_annotations.py`。

## 比較条件と再現

- 基準実装・変更案: 旧runは短いbike_clipsの保存済み測定点。今回は検出枠を描く前の全体動画A/BにYOLO26xとByteTrackを実行。各動画の追跡状態を独立させ、動画内ではリセット・切出し・フレーム間引きをしない。
- 指標・単位・成功基準: 全12613/12643フレームの処理完了を確認。CVAT有効参照枠のIoU>=0.5対応率、対応するYOLO ID数とID変化数、共通フレームの速度差(km/h)を集計。未注釈車の誤検出率や正式なMOT精度は算出しない。
- source_id・データ版・件数・除外条件: video-A-full/video-B-full、1280x720、30fps、CVATタスク3/4。保持末尾を除外。速度は同じBBOX下辺測定点と校正、0.2秒窓を使用。タイヤ検出は今回含めないため旧runとは測定点条件も異なる。
- コード版・未コミット差分・環境・seed: 実行コードをrunに保存。既存 `.venv` のPyTorch 2.9.1+cu130、Ultralytics 8.3.200、RTX5070。seed=0。confidence=0.20、IoU=0.5、imgsz=960。
- 実行コマンド・作業ディレクトリ: `.venv/Scripts/python.exe docs/analysis-vault/80-Artifacts/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089/code/full_video_yolo.py`、リポジトリ直下。

## 結果と検証

全体動画2本の実行終了。全フレーム読込、DBへの新run保存、CVAT対応集計を確認。実測真値・追跡対応の目視確認は未了のため `inconclusive / unverified`。

| 動画 | 全処理フレーム | アプリrun ID | CVAT参照トラック | 参照枠への対応 | 対応ID変化 | 複数ID対応の参照トラック |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| video-A | 12613 | 100669 | 8 | 2115 / 3052 (69.3%) | 3 | 2 |
| video-B | 12643 | 100670 | 4 | 1194 / 3774 (31.6%) | 14 | 3 |

- 元の切出しYOLO runは上書きしない。新規runで検出結果をアプリDBに保持。生動画、DB、CVAT exportをVaultへ複製しない。
- Aは検出枠重畳前の全体動画を使用。12か所の車の実キーフレームを重畳版と数値照合し、0フレームずれを支持。BはCVATタスク作成時と同じ全体動画。両動画30fps、1280×720。データ版とハッシュはconfig参照。
- 追跡状態は動画ごとに初期化し、動画内では連続維持。全体を処理した後、同一フレームの参照枠とIoU>=0.5で1対1対応。car/truck/busは車の同一クラス群として照合。
- 対応率は保持末尾を除いた参照枠に限る。部分注釈・補間を含むため、全動画の適合率・再現率や正式なMOT指標とは扱わない。可視参照枠と実キーフレームの件数もCSVに保存。
- 対応ID変化は同じCVATトラックへの連続する対応観測でYOLO IDが変わった回数。幾何対応による候補であり、ID誤りの確定には画像での確認が必要。未対応区間の再開回数も保存。
- 診断表 `tables/id_change_candidate_diagnosis.csv`：対応先IDの変化17回のうち10回では、変化先フレームに旧・新IDが同時に存在し、car/truckの枠がIoU 0.97以上で重なっていた（A 1回、B 9回）。重複検出と対応先の選択の影響を含むため、17回を純粋なIDスイッチ数とは扱わない。候補のフレーム番号は `tables/id_change_candidates.csv`。
- 検出と追跡の参照対応を `tables/reference_detection_tracking_coverage.csv` に分けた。検出枠が対応しても追跡IDがない観測を別件数で保持。
- 速度は両方式で車右下・自転車下辺中央、同じ路面校正と0.2秒窓を使用。CVATは実キーフレームを路面へ射影して補間。タイヤ検出・測定点平滑化を使った旧保存値とは条件が異なるため、旧群中央値差を今回の改善量とはしない。
- 元表：`tables/*_cvat_tracking_comparison.csv`、全体YOLOの校正内速度：`tables/*_full_track_speeds.csv`、並走点間距離：`tables/*_full_encounters.csv`。空の距離表は観測0件を意味する。
- 図：`figures/full_video_reference_comparison.png` / `.svg`。共通フレームに有効速度があるcarを1台1点で表示。
- 検証：全処理件数12613/12643、アプリrunの完了状態、保存検出行数、座標倍率1、CVATメタデータ一致、IoU対応の単純例を確認。計算の整合性確認と実測精度検証を区別する。
- 採用：全体動画を連続追跡した結果と、同じ車両・フレームの対応候補。保留：独立した速度真値、対応候補の目視確認、未注釈物体を含む追跡精度。
- 次：複数ID対応、対応率の低い参照トラックを目視確認し、車両の対応を確定して速度・点間距離の誤差を再評価する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089/slides/slide-card.md)
- 試験コードは `../80-Artifacts/adc-run-20261007T210449Z-full-video-yolo-cvat-eb597089/code/`、図表は同じ実験の `figures/` へ保存。
