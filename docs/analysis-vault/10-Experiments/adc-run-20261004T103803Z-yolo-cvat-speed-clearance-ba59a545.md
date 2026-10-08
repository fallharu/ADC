---
note_id: adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545
vault_kind: analysis
note_type: experiment
title: "YOLO・CVATの速度離隔距離train-valと道路条件比較"
summary: "同じ校正で速度窓363件（train262・val101）と箱ひげ図を作成。拡幅側の車速中央値は2〜3km/h低いが各条件1動画。距離は各方式1件、val0件。絶対精度未検証。"
run_id: adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545
parent_run_id: null
source_ids: [video-A-yolo, video-A-cvat, video-A-calibration, video-B-yolo, video-B-cvat, video-B-calibration]
artifact_ids: [artifact-speed-windows, artifact-track-summary, artifact-clearance-encounters, artifact-summary, artifact-speed-boxplot]
revision: 2
status: inconclusive
validation_status: unverified
updated: 2026-10-04T10:38:03+00:00
---

# YOLO・CVATの速度離隔距離train-valと道路条件比較

## 問い・仮説

- Issue22の速度計算・速度と離隔距離のtrain/val表・箱ひげ図スライド・道路条件比較を実行する。
- YOLOの保存測定点とCVATの手動BBOXを同じ路面校正で比較する。既存の縦スケールと自動区間v2の速度は混ぜない。
- 対象コード: `scripts/build_yolo_cvat_speed_clearance.py`、`scripts/plot_yolo_cvat_dataset.py`。実行版はrunの`code/`に保存。

## 比較条件と再現

- YOLO26xの既存検出に保存済みの測定点を使用。1920×1080→1280×720に2/3倍。CVATは自転車下辺中央・車右下を実キーフレームで路面に射影して補間。今回新たなYOLO推論は実行していない。
- 校正: `cvat_1575_auto_v2`（A、45m）、`cvat_2945_auto_v2`（B、30m）。速度は0.2秒窓の縦方向位置−時間回帰の絶対値（km/h）。既存の破線周期・車線幅の仮定を引き継ぐ。
- 校正範囲外、CVAT保持末尾、検出欠落・無効点をまたぐ回帰、15有効フレーム未満のトラックを除外する。
- 元動画Aをtrain、元動画Bをvalに固定。同一元動画の切出し・注釈方式・全車両を同じ側に保持。2動画のため動画数1:1。乱数seedなし。
- 距離は同方向・前後反転・両点校正内・縦方向差±1mを満たすペアの横方向測定点間距離（m）。車体端間の安全離隔ではない。併せてユークリッド点間距離も保存する。
- 元データは匿名source ID、XML・校正のSHA256、選択YOLO行のハッシュを`config/source_provenance.json`に保持。原動画・DB・未加工exportはコピーしていない。
- コード版・環境・コマンドはmanifestと`config/execution.json`。作業ツリーの既存変更を維持。試験コードをrunへ保持。
- 実行: リポジトリ直下で `python scripts/build_yolo_cvat_speed_clearance.py docs/analysis-vault/80-Artifacts/adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545`。入力export親は`--exports`で指定可能。

## 結果と検証

実行終了。計算の整合性確認済み、実速度・実距離の絶対精度は未検証。距離val未作成のため`inconclusive / unverified`。

| 指標 | YOLO A 未拡幅 | YOLO B 拡幅 | CVAT A 未拡幅 | CVAT B 拡幅 |
| --- | ---: | ---: | ---: | ---: |
| 速度窓件数（全車種） | 156 | 42 | 106 | 59 |
| 箱ひげ用carトラック数 | 7 | 2 | 6 | 3 |
| carトラック速度中央値（km/h） | 55.70 | 52.91 | 59.42 | 57.11 |
| 距離件数 | 1 | 0 | 1 | 0 |
| 横方向点間距離（m） | 1.705 | ― | 1.390 | ― |

- 合計363速度窓、24トラック。train262窓／17トラック、val101窓／7トラック。距離train2推定値、val0。
- 拡幅−未拡幅の車速中央値差はYOLO −2.790、CVAT −2.313km/h。各条件1動画で場所・日時・交通条件と交絡し、拡幅効果を分離できない。
- YOLOは切出し動画、CVATは元動画でありフレーム対応未確定。別標本の分布比較であり、車両単位の精度評価ではない。
- `python -m pytest tests/test_yolo_cvat_dataset.py tests/test_speed_regression.py -q`：8 passed。既知速度・座標倍率・欠落をまたがない回帰・保持末尾除外・同一動画混入の拒否を確認。
- 実表の件数、一意ID、有限値、元動画群のtrain/val非重複を確認。保存版コードを再実行し同じ集計を得た。
- 8枚PPTXを作成。PowerPointで開き全ページを描画し目視確認。箱ひげは編集可能な図形、道路比較はネイティブ棒グラフ。元表・PNG・SVG・生成コード・発表者メモを保持。
- 採用: 現入力に対する速度計算・派生表・説明資料。保留: 正解ラベルとしての利用、距離val、拡幅の因果効果、車両単位誤差。
- 次: 切出し−元動画のフレーム対応を確定し、拡幅側で校正内に同時観測される車と自転車を追加する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545/slides/slide-card.md)
- 試験コードは `../80-Artifacts/adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545/code/`、図表は同じ実験の `figures/` へ保存。
