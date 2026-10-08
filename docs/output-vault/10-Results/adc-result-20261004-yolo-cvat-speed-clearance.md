---
note_id: adc-result-20261004-yolo-cvat-speed-clearance
vault_kind: output
note_type: result
title: YOLO・CVAT速度表と距離データの不足
summary: 共通校正の速度窓363件をtrain262・val101へ動画分割。拡幅側の車速中央値は2〜3km/h低いが各条件1動画。距離val0件、絶対精度未検証。
run_id: adc-run-20261004T103803Z-yolo-cvat-speed-clearance-ba59a545
source_ids: [video-A-yolo, video-A-cvat, video-B-yolo, video-B-cvat]
artifact_ids: [artifact-speed-windows, artifact-track-summary, artifact-clearance-encounters, artifact-summary, artifact-speed-boxplot]
revision: 1
status: unverified
updated: 2026-10-04
---

# 分析結果（絶対精度未検証）

同じ自動区間v2校正でYOLO保存測定点とCVAT実キーフレーム由来の速度を計算した。車トラック中央値の道路差（拡幅−未拡幅）はYOLO −2.790km/h（7対2トラック）、CVAT −2.313km/h（6対3トラック）。各条件1動画のため道路の因果効果を分離できない。

速度窓363件（全車種）を元動画単位でtrain262／val101へ分割。離隔距離は未拡幅のYOLO 1.705m、CVAT 1.390mが各1件、拡幅は0件でval未作成。距離は並走時の測定点間横距離で、車体端間距離ではない。

フレーム対応が未確定で、方式間の標本は一対一に照合していない。速度・距離の絶対値に独立真値なし。計算検証8件合格と実表のID・件数・動画非重複を確認したが、物理精度が検証済みという意味ではない。

根拠は上記runのmanifestとartifact ID。発表: [[20-Presentations/adc-presentation-20261004-yolo-cvat-speed-clearance]]。
