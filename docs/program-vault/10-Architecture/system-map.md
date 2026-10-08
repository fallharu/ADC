---
note_id: adc-architecture-map
vault_kind: software
note_type: architecture
title: ADC_08 system map
summary: The active product is a Flask application in Source_code with root templates; scripts/0903_adc is a separate modular reimplementation and delivery tree.
revision: 4
status: current
updated: 2026-09-26
---

# System map

## Current application

- Entry: `Source_code/app.py`
- HTTP routes: `Source_code/routes/`
- Domain and analysis logic: `Source_code/modules/`
- UI templates: `templates/`
- Browser assets: `Source_code/static/`
- Runtime data: `db/`, `uploads/`, `output/`, configured paths, and ignored database files

The application is a Flask/Jinja system backed by SQLite and local analysis assets. Existing modules include video processing, calibration, detection, overtaking, clearance, exports, comparative reports, and optional AI insight generation.

### Measurement and speed path

The speed pipeline in `Source_code/modules/speed/` first matches vehicle detections with tire detections and selects a measurement point. It stabilizes the point from separately smoothed box center, box dimensions, and in-box anchor, then estimates velocity over a configurable frame window with rolling regression. The defaults currently recorded in `docs/ADC_System_Specification.md` are a 0.2-second speed window and a 5-frame centered median window.

Homography projection is implemented in `Source_code/modules/speed_homography/`. It can apply camera lens correction and a longitudinal position map. `Source_code/modules/homography_preview.py` uses the same projection class for the calibration page’s bird’s-eye preview; the API route is `/api/calibration/<run_id>/homography_preview`.

### Report and inference additions

Comparative-report records include event frame and video time, with optional sampled scatter series and IQR filtering. `Source_code/modules/ai_insight.py` builds chart-specific context and insight cards from the report statistics. The detection page can show the resolved model sequence and a CUDA preflight result before a run starts.

## 必要なコードを探す索引

次の表は読む場所を絞るための索引。挙動を変更するときだけ、対象モジュールと直接の呼出元・テストを読む。

| 作業 | 主な入口 |
| --- | --- |
| 検出・推論 | `Source_code/routes/inference.py` → `Source_code/modules/inference.py` |
| キャリブレーション | `Source_code/routes/calibration.py`、`Source_code/tools/calibration_tool.py` |
| 速度の計算 | `Source_code/modules/speed/`、`speed_homography/`、`speed_y_axis/`（いずれもmodules配下） |
| 速度窓の回帰・計測点安定化 | `Source_code/modules/speed_regression.py`、`Source_code/modules/measure_points.py` |
| 俯瞰プレビュー | `Source_code/modules/homography_preview.py`、`Source_code/routes/calibration.py` |
| 計測点 | `Source_code/modules/measure_points.py` |
| 分析と比較レポート | `Source_code/routes/analysis.py`、`Source_code/modules/comparative_report.py` |
| DB保存契約 | `Source_code/modules/db_manager.py`と対象の呼出元 |
| AI考察 | `Source_code/modules/ai_insight.py`と[[40-Design/ai-development-rules]] |
| 試験と発表用の保存ルール | `docs/analysis-vault/00-AI-Entry.md`（リポジトリ相対） |

## Separate implementation tree

`scripts/0903_adc/` contains a newer modular application, design book, migrations, tests, reports, and delivery artifacts. It is not the default edit target for the root Flask application. Read its `README_ja.md` only when a task explicitly targets that tree or asks for migration between implementations.

## Auxiliary desktop tool

`tools/tire_distance_studio/` is a standalone Windows/Tkinter tool for tire-distance analysis, visualization, annotation, and training workflows. Its displayed distance is in image pixels; metric distance requires separate calibration. See its `README.md` and `DEVELOPER_GUIDE.md` for setup and coordinate/threading details.

## Authority

Code and tests define executable behavior. `docs/` describes the current/root system. This Vault contains concise routing, architecture, and decisions; it does not duplicate full design documents.

## Workspace change record

The 2026-09-26 workspace snapshot is summarized in [[30-Development/2026-09-26-worktree-change-record]]. It covers the current measurement and speed-estimation changes, calibration preview and preservation, comparative reporting, inference preflight, and shared UI updates. The snapshot records code state; it does not assert that the added tests have passed.
