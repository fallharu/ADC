---
note_id: adc-software-entry
vault_kind: software
note_type: router
title: ADC AI entry
summary: 作業に必要なADCのコード・保存・分析ルールへの入口。
revision: 4
status: current
updated: 2026-09-26
---

# AI entry

該当する行だけ読む。コード・docs/で始まるパスはリポジトリ相対、他はこのVault内。

| 作業 | 参照先 |
| --- | --- |
| Flask・画面 | `Source_code/app.py`、対象route・template |
| 検出・推論前のモデル/GPU表示 | `Source_code/routes/inference.py`、`Source_code/modules/inference.py`、`Source_code/modules/resource_monitor.py` |
| 計測点・平滑化・速度回帰 | `Source_code/modules/measure_points.py`、`Source_code/modules/speed_regression.py`、`Source_code/modules/speed/` |
| ホモグラフィ速度・レンズ/縦方向補正 | `Source_code/modules/speed_homography/`、`Source_code/modules/speed_y_axis/` |
| 校正保存・俯瞰プレビュー | `Source_code/routes/calibration.py`、`Source_code/modules/homography_preview.py`、`Source_code/tools/calibration_tool.py` |
| 比較散布図・AIチャート所見 | `Source_code/routes/analysis.py`、`Source_code/modules/comparative_report.py`、`Source_code/modules/ai_insight.py` |
| Tire Distance Studio | `tools/tire_distance_studio/README.md`、`tools/tire_distance_studio/DEVELOPER_GUIDE.md` |
| DB契約 | `Source_code/modules/db_manager.py` と直接の呼出元 |
| AI考察 | `Source_code/modules/ai_insight.py` と `40-Design/ai-development-rules.md` |
| 検索・トークン削減 | `20-Workflows/context-retrieval.md` |
| Obsidian保存構造 | `40-Design/obsidian-vault-contract.md` |
| 実験・相談・発表 | `docs/analysis-vault/00-AI-Entry.md` |
| 出力カタログ | `docs/output-vault/00-AI-Entry.md` |
| 0903版への明示依頼 | `scripts/0903_adc/README_ja.md` |
