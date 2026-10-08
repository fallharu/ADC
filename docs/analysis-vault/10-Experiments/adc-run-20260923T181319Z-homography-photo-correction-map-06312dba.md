---
note_id: adc-run-20260923T181319Z-homography-photo-correction-map-06312dba
vault_kind: analysis
note_type: experiment
title: "実画像上の射影距離補正量の可視化"
summary: "校正線変更前の実画像補正量。最大+8.52 m、手前の近接線で局所倍率28.5倍。現行profileは子runで更新。"
run_id: adc-run-20260923T181319Z-homography-photo-correction-map-06312dba
parent_run_id: adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea
source_ids:
  - source-adc-camera-20250720-representative-01
  - source-adc-homography-profile-cf-v5-720
artifact_ids:
  - artifact-homography-correction-photo-gradient
  - artifact-homography-photo-correction-metrics
revision: 3
status: completed
validation_status: unverified
updated: 2026-09-23T18:28:21+00:00
---

# 実画像上の射影距離補正量の可視化

この図と数値は**校正線削除前**のprofileに基づく履歴。現在の2本削除後のprofileと比較図は [[adc-run-20260923T182334Z-homography-trim-edge-lines-616d80a0]] を参照する。

## 問い・仮説

- 解決したい問題: 実画像のどの道路位置で、現行ホモグラフィに対する距離補正量が大きいかを可視化する。
- 原因の仮説: 4点射影の奥行き位置と等間隔校正線から得る位置の差が場所によって異なる。
- 対象コード: `Source_code/modules/speed_homography/__init__.py` の `HomographyProjection`。校正profileは `2_250720_cf_v5_720`。

## 比較条件と再現

- 基準実装・変更案: 現行の補正前位置 `world_y_raw` と現行補正後位置の差を画像上へ逆投影する。モデル変更なし。
- 指標・単位・成功基準: 補正後−補正前の道路方向距離 (m)。有効道路四角形内のみ描画し、凡例、基準点、最大補正位置を記す。実測真値との差とは呼ばない。
- source_id・データ版・件数・除外条件: profile `2_250720_cf_v5_720` の11本の校正線と、同じ固定カメラの代表動画フレーム690。動画とprofileはVaultへ複製していない。source SHA-256と画像縮小条件は [conditions](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/config/conditions.json)。四角形外・基準範囲外の画素は塗らない。
- コード版・未コミット差分・環境・seed: Git HEAD `75b64a2d792f421e0a7ebd8c76e3c3f4ac6166fe`、対象コードはdirtyで[差分](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/code/speed_homography_source_diff.patch)を保持。Python 3.13.7、OpenCV 4.12.0、NumPy 2.2.6、Matplotlib 3.10.8。乱数なし。
- 実行コマンド・作業ディレクトリ: リポジトリ直下で `python docs/analysis-vault/80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/code/plot_correction_on_photo.py --video <same-camera-source-video> --frame 690 --profile output/calibrations/2_250720_cf_v5_720.json --output docs/analysis-vault/80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/figures/homography_correction_photo_gradient.png --metrics docs/analysis-vault/80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/tables/photo_correction_metrics.json`。

## 結果と検証

- [写真上の補正量と局所倍率](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/figures/homography_correction_photo_gradient.png) (`artifact-homography-correction-photo-gradient`) は、同一カメラの代表フレーム上に `HomographyProjection` の補正前後差を表示。道路四角形内のみ有色。
- [数値表](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/tables/photo_correction_metrics.json) (`artifact-homography-photo-correction-metrics`): 最大補正量は +8.515 m、補正前道路位置 11.485 m 付近。最も手前の校正線2本は、画像上でほぼ重なり、射影後の距離差は0.176 m。モデルはこの2線を5.0 m間隔として扱い、局所距離倍率は28.47倍。
- profileの `homography.interval_m` は5.0 mだが、併存する `known_distance_m=8.0` / `num_intervals=4` は2.0 m/区間に相当する。前者が実測値か、後者が旧モードの残存値かは未確認。
- 検証: 描画スクリプトを実行してPNGと数値JSONを生成。11校正線の生の射影位置と補正位置をコードから再取得して最大値・近接間隔・倍率を照合。画像の四角形が道路に重なることを目視確認。
- 限界: 図は**現在の補正モデルの要求量**であり、独立測量した真の誤差ではない。代表フレームがこのprofileの元フレームであることは未確認。道路左右の誤差は現行1D補正から分からない。実速度真値もないため精度改善は未検証。
- 採否: 校正線の近接と距離基準の不一致は調査対象として採用。現行補正値を正解として学習・速度補正へ広げる判断は保留。
- 次の最小実験: 11校正線の物理的な間隔と手前の2本が重複していないかを現場記録または独立測量で確認し、別runで修正前後の位置・速度を比較する。

## 保存した資料

- [manifest](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/manifest.json)
- [写真上の補正量と局所倍率](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/figures/homography_correction_photo_gradient.png)
- [条件](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/config/conditions.json)と[数値](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/tables/photo_correction_metrics.json)
- [スライド候補・発表者メモ](../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/slides/slide-card.md)
- 試験コードは `../80-Artifacts/adc-run-20260923T181319Z-homography-photo-correction-map-06312dba/code/`、図表は同じ実験の `figures/` へ保存。
