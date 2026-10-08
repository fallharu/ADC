---
note_id: adc-presentation-20261004-yolo-cvat-speed-clearance
vault_kind: output
note_type: presentation
title: YOLO・CVATの速度・離隔距離とtrain/val
summary: 速度窓363件の動画分割、車速箱ひげ、未拡幅と拡幅の観測差を8枚で説明。距離val0件・絶対精度未検証を明示。
revision: 2
status: stale
validation_status: unverified
updated: 2026-10-08
source_run_ids: [adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545]
---

# YOLO・CVATの速度・離隔距離

2026年10月8日：元動画全体のYOLO再処理に伴い、切出し結果を使った本資料の再利用を保留する。過去条件の資料として保持し、最新の全体処理結果は [[../10-Results/adc-result-20261008-full-video-yolo-cvat]] を参照する。

- [PowerPoint 8枚](../80-Artifacts/adc-presentation-20261004-yolo-cvat-speed-clearance/yolo_cvat_speed_clearance_20261004.pptx)
- [派生データ一式](../80-Artifacts/adc-presentation-20261004-yolo-cvat-speed-clearance/yolo_cvat_derived_dataset_20261004.zip)
- [スライドと根拠IDの対応](../80-Artifacts/adc-presentation-20261004-yolo-cvat-speed-clearance/sources.json)
- 生成コード: 同じフォルダーの`build_slides.js`。分析図表・元表は上記runを参照する。
- 1:件数、2:測定点と計算、3:動画単位分割、4:車速箱ひげ、5:距離の参考値とval不足、6:道路別速度、7:採用件数、8:追加検証。
- 実データ由来の数値は校正推定値。train262速度窓、val101速度窓。距離trainはYOLO/CVAT各1件、valは0。動画A/Bの各道路条件は1動画ずつなので拡幅効果は判断できない。
- 箱ひげはPowerPointの編集可能な図形、道路比較は編集可能なネイティブ棒グラフ。PowerPointで8枚を開き描画確認。独立した実測真値との照合は未了。
