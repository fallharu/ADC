---
note_id: adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f
vault_kind: analysis
note_type: experiment
title: 道路中央の白い破線：自動検出と目視注釈の比較
summary: 目視で明瞭な中央破線7本は自動検出7/7。端点誤差中央値1 px、最大19 px。最手前の線は探索範囲で欠ける。
run_id: adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f
parent_run_id: adc-run-20260923T190346Z-center-dash-current-calibration-2208517e
source_ids: [source-adc-camera-20250720-representative-01, source-adc-homography-profile-cf-v5-1080-after-edge-removal]
artifact_ids: [artifact-center-dash-auto-manual-figure, artifact-center-dash-auto-manual-pairs, artifact-center-dash-auto-manual-summary]
revision: 2
status: completed
validation_status: verified
updated: 2026-09-23T19:19:33+00:00
---

# 道路中央の白い破線：自動検出と目視注釈の比較

## 問い・仮説

- 問い：既存の白色成分検出は、目視で確認できる中央破線を何本検出し、各破線のカメラに近い端を何ピクセルずれて選ぶか。
- 仮説：近・中距離では検出できるが、遠方では白線が数ピクセルとなり検出漏れや端点ずれが増える。
- 対象：2025-07-20 の同一固定カメラ動画の21フレーム中央値画像。現在の `2_250720_cf_v5.json` を座標変換に使う。アプリの補正値は変更しない。

## 比較条件と再現

- 基準実装：`scripts/check_calibration_distortion.py` の `median_background(samples=21)` と `detect_dashes`。比較前にパラメータを変更しない。
- 目視：自動検出結果を表示しない原寸画像で、中央破線ごとの「カメラに近い端」を注釈する。明瞭な線と判定困難な線を区別し、後者は主要指標から外す。注釈座標と判断理由を保存する。これは担当AIによる目視で、独立した人間の正解データではない。
- 指標：明瞭な目視破線に対する検出率、検出の適合率、手前端の画素誤差と射影後の縦方向距離差（m）。除外条件と対応付けの閾値を明記する。
- 成功基準：目視で明瞭な線の検出漏れがなく、手前端の中央値誤差が5 px以内。遠方と境界部分は別集計。
- 元動画は既存の `uploads/` に保持し、Vaultには試験コード・注釈値・集計・注釈済みの派生図のみ保存する。

## 結果と検証

- 条件：1920×1080 の同一動画から21フレーム中央値を作成。前回と同一の自動検出器・校正JSONを使用。元動画・校正・検出器のSHA-256と除外条件は[conditions](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/config/conditions.json)。コード版はGit `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、作業ツリーdirty。検出器と射影クラスの未コミット版は親実験のスナップショットとSHAが一致した。
- 作業ディレクトリ：リポジトリ直下。`python docs/analysis-vault/80-Artifacts/<run_id>/code/prepare_manual_view.py --video <source_video> --out temp_output/center_dash_manual_view.png --zoom-out temp_output/center_dash_zoom.png` で自動マークのない目視画像を作り、[手動注釈CSV](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/config/manual_near_edges.csv)を先に固定。その後 `python docs/analysis-vault/80-Artifacts/<run_id>/code/compare_auto_manual.py --video <source_video> --profile <active_profile> --manual docs/analysis-vault/80-Artifacts/<run_id>/config/manual_near_edges.csv --out-dir docs/analysis-vault/80-Artifacts/<run_id>/tables` を実行した。
- x=285～1075 px の観察範囲で目視11本を注釈。自動検出は9成分で、画像上で9本とも実在する白線に対応した。探索帯内で両端が確認できる7本は7/7本を検出。残りは最手前の1本が探索帯で切れる、遠端の1本が探索帯の端にかかる、遠方の2本が探索帯外、という内訳。[重ね図](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/figures/auto_vs_manual_near_edges.png) (`artifact-center-dash-auto-manual-figure`) に示した。
- 明瞭な7本の手前端について、画素距離の誤差は中央値1.0 px、平均3.20 px、最大19.0 px。7本中6本は5 px以内。最大誤差はM02の左端で、目視(690,779)に対し自動(709,779)。最手前の探索帯で切れたM00は目視(285,875)に対し自動(370,860)で86.3 pxずれる。[対応表](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/tables/paired_near_edges.csv) (`artifact-center-dash-auto-manual-pairs`) と[集計](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/tables/summary.json) (`artifact-center-dash-auto-manual-summary`) を保存した。
- 射影後の縦距離差の絶対値は7本で中央値0.038 m、最大1.54 m。遠方M07では画像のy方向1 px差だけで約1.54 mに相当した。目視注釈自体に±3～5 px程度の幅があるため、これを真の距離誤差とは扱わない。
- 判定：事前基準の「7本の漏れなし・中央値5 px以下」は満たす。ただしM02の19 px外れ値と最手前の探索帯切れがあり、距離補正の基準点として無検査で採用しない。親実験で現行補正の基準点範囲内に入る自動候補は3本のみであり、この実験の7本検出成功と距離補正の妥当性は別の話。
- 制約：目視は担当AIの1回の注釈で、以前の自動候補座標も既知だったため盲検ではない。白線周期の実測距離と車両位置の独立正解はない。遠方x>1075の白線は本数評価の対象外。測定の採用前に人手でM02の端点と探索帯の延長を再確認する。
- 検証：重ね図を元画像と照合し、各成果物のSHA-256をmanifestに記録。`python -m pytest tests/test_analysis_vault.py -q` は6件成功。ここでの `verified` は実験保存形式と再現可能な集計の検証であり、目視注釈の物理的正しさを保証しない。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/manifest.json)
- [スライドカード](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/slides/slide-card.md)
- [目視座標](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/config/manual_near_edges.csv)・[条件](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/config/conditions.json)・[図](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/figures/auto_vs_manual_near_edges.png)・[表](../80-Artifacts/adc-run-20260923T191933Z-center-dash-auto-manual-30c6130f/tables/paired_near_edges.csv)
