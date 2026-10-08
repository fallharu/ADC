---
note_id: adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad
vault_kind: analysis
note_type: experiment
title: "Bicycle present versus absent CVAT comparison"
summary: "同一動画の25秒ずつをCVAT化して車両推定速度を暫定比較。自転車なしの全フレーム目視確認と速度真値は未了。"
run_id: adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad
parent_run_id: null
source_ids:
  - src-1575-video
  - src-1575-manual-cvat
  - src-20250720-y-calibration
  - cvat-task-1
  - cvat-task-2
artifact_ids:
  - artifact-car-tracks-same-model
  - artifact-comparison-summary
  - artifact-comparison-figure
  - artifact-cvat-present-manual-bicycle-link
revision: 4
status: inconclusive
validation_status: unverified
updated: 2026-09-30T11:40:19+00:00
---

# Bicycle present versus absent CVAT comparison

## 問い・仮説

- 問い: 同じ撮影地点で自転車走行時と未走行候補時の自動車の推定速度に違いがあるか。
- 仮説: 自転車がいる時間帯は自動車の速度が低い可能性がある。ただし25秒ずつの観察比較であり、因果効果は検証できない。
- 対象コード: 本runの `code/`、既存の `scripts/analyze_cvat_measurement_smoothing.py`、`scripts/visualize_cvat_distance_speed.py`、`Source_code/modules/measure_points.py`、`Source_code/modules/speed_regression.py`。

## 比較条件と再現

- 元動画: `uploads/2_/250720/2_20250720_000G1575.mp4`。30 fps、1280×720、12613フレーム。元動画は表示済みYOLO検出枠を含む。生動画・生CVAT exportはVaultに複製していない。各sourceのSHA-256はmanifestに記録。
- 自転車なし候補: 元動画6000〜6749フレーム（200.000〜224.967秒）の25秒をローカルCVATタスク1に投入。0.2秒間隔125枚の目視サンプルでは自転車を見つけなかった。二輪車は見えるがmotorcycleである。YOLO26xで全750フレームを確認した自転車検出数も0。ただし同モデルは既知の自転車あり区間でも自転車検出0であり、この陰性結果は不在の証明にならない。全フレームの人手確認は未了。
- 自転車あり: 同じ元動画8580〜9329フレーム（286.000〜310.967秒）をCVATタスク2に投入。既存の手動CVAT XMLでは自転車トラックが8324〜9389フレームに存在し、区間のサンプルフレームでも目視確認した。
- 両タスクの自動注釈: 同じYOLO26x、imgsz=960、confidence=0.20、ByteTrack、30 fps。タスク1は16トラック（car 11、truck 4、motorcycle 1）、タスク2は自動22トラック（car 18、truck 4）に既存の手動自転車1トラックを追加した計23トラック。車両の自動注釈は人手レビュー前の提案。元フレームと切り出し動画の先頭・末尾を画像差で照合した。
- 指標: 同じ `2_20250720_y` 校正・0.2秒回帰によるcarトラックごとの速度中央値（km/h）を出し、その中央値を比較。対象は活動60フレーム以上かつ校正範囲内30フレーム以上。速度の絶対値に独立した真値はない。
- 検証用の異質な注釈条件: 既存手動CVATの自転車あり区間も同じ速度計算に通した。主比較は同じ自動モデル同士とする。
- コード版: Git HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、作業ツリーdirty。本runに試験コードを保存し、依存する未コミットコードの状態もmanifestに記録。Python 3.13.7、PyTorch 2.9.1+cu130、Ultralytics 8.3.200。
- 実行ディレクトリ: リポジトリ直下。コマンドとパラメータはmanifest、コードは `80-Artifacts/<run_id>/code/`。認証は実行時環境変数のみ。

## 結果と検証

| 注釈条件 | 自転車あり | 自転車なし候補 | 差（あり−なし） |
| --- | ---: | ---: | ---: |
| 同一YOLO26xで両区間を追跡 | 9.028 km/h（car 6トラック） | 10.708 km/h（car 6トラック） | −1.680 km/h |
| あり側を既存手動CVATに変更 | 7.149 km/h（car 4トラック） | 10.708 km/h（car 6トラック） | −3.559 km/h |

- 主結果の根拠: `artifact-car-tracks-same-model`、`artifact-comparison-summary`、`artifact-comparison-figure`。棒の範囲はトラック中央値の最小〜最大であり信頼区間ではない。
- 検証: CVAT APIでタスク1=750フレーム・16トラック、タスク2=750フレーム・23トラックを再読込。タスク2の自転車は既存手動CVATの750フレームを元動画からのフレームオフセットで照合して取り込んだ。両切り出しの元フレーム先頭・末尾の平均画素差は再圧縮後1.0〜2.3/255。集計コードを再実行し図表を確認した。
- 限界: 「なし」は125枚の目視サンプルと機械検出で選定した候補であり、750フレーム全ての目視保証はない。モデルは既知の「あり」区間の自転車を検出できなかった。自動追跡は分断・車種誤分類があり得る。2区間の交通状況、対向車、車種構成、時間差が揃っていない。速度真値がないため絶対値の精度も不明。
- 判定: CVATタスクと比較データを作成した。自転車の存在が速度差を生んだという結論は保留し、runを `inconclusive / unverified` とする。
- 次の最小実験: タスク1の全750フレームで自転車不在と車両トラックを目視確認し、タスク2も車両トラックを訂正。独立した速度基準を用意し、同一車種・走行方向・道路位置で複数区間を比較する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad/slides/slide-card.md)
- [比較集計表](../80-Artifacts/adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad/tables/comparison_summary.csv)
- [比較図](../80-Artifacts/adc-run-20260930T105426Z-bicycle-present-absent-e6d8b7ad/figures/car_speed_comparison.png)
- 試験コードは同じrunの `code/`、個別トラックの派生集計は `tables/`。CVATタスク1・2はローカル `http://localhost:8080/` に保持。
