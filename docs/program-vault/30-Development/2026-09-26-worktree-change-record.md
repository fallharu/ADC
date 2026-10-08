---
note_id: adc-code-change-record-20260926
vault_kind: software
note_type: change-record
title: ADC_08 workspace changes (2026-09-26)
summary: Workspace snapshot covering measurement and speed estimation, calibration, comparative reports, inference preflight, shared UI, Tire Distance Studio, and project knowledge tooling.
revision: 1
status: current
updated: 2026-09-26
---

# ADC_08 workspace changes (2026-09-26)

This note summarizes the application and support-code changes visible in the workspace on 2026-09-26. Source code, tests, and Git history remain authoritative. It summarizes implementation areas and does not claim a release or verified test result. Generated output and local datasets are not copied into this note.

## Measurement points and speed estimation

- `Source_code/modules/measure_points.py` associates vehicle detections with tire detections and chooses a measurement point, with geometric fallbacks when a tire point is unavailable. Missing travel-direction fields are handled without failing the fallback path.
- Measurement-point smoothing separates the bounding-box center, size, and normalized in-box anchor, smooths those components, then reconstructs the point. The local quadratic Savitzky–Golay filter is applied per track segment, splitting at long frame gaps so short gaps do not join unrelated motion.
- `Source_code/modules/speed_regression.py` adds rolling linear-regression velocity and scaled-axis position integration. The speed paths use a configurable time window (default 0.2 seconds); the final speed series uses a configurable centered median window (default 5 frames).
- Homography speed estimation can undistort points using camera intrinsics, use measured longitudinal correction samples or derive correction from calibrated guide lines, and select longitudinal or XY distance. The default distance mode is longitudinal. Vertical-scale fallback uses the same rolling-slope approach.
- `Source_code/modules/speed/__init__.py` writes the horizontal scale value along with the speed and direction fields. `docs/ADC_System_Specification.md` records the smoothing and calibration settings.

## Calibration and projection preview

- `Source_code/modules/homography_preview.py` and `/api/calibration/<run_id>/homography_preview` render a bird’s-eye preview using the projection used by speed estimation and return the calibrated dimensions, station positions, and correction-state metadata.
- The calibration page adds the preview and related measurement controls. Calibration payload preparation validates speed-window and homography-correction fields, accepts valid camera-intrinsic parameters, and preserves existing camera/correction values when unrelated settings are saved without changing the homography geometry.

## Comparative reporting and AI insights

- `Source_code/modules/comparative_report.py` includes event frame, FPS, and video time in the report records, derives time from FPS when needed, and uses a stored manual overtaking speed when there is no speed profile.
- `Source_code/routes/analysis.py` builds time, speed, clearance, and line-distance scatter series. It supports optional IQR filtering and caps each series at 2,500 plotted points.
- `Source_code/modules/ai_insight.py` builds compact contexts from grouped statistics, sample counts, trends, tests, composition, correlations, and chart data. It adds per-chart Japanese insight cards with JSON parsing and fallback cards for omitted model responses.
- The comparative-report page adds controls and displays for scatter plots and chart-level insights.

## Inference and shared interface

- Before inference starts, the detection page can show the selected model sequence and the expected device. CUDA availability is checked with a small operation; an incompatible or unavailable CUDA device is presented as CPU. `YOLO_FORCE_CPU=1` remains an explicit override.
- The Flask app returns HTML error pages for page requests and JSON errors for API/AJAX requests.
- `templates/base.html`, `Source_code/static/css/app.css`, and `Source_code/static/js/app-ui.js` provide the shared sidebar/top bar, responsive layout, toasts, confirmations, and busy-state behavior. Calibration, comparative-report, detection, gallery, and other pages were adapted to the shared layout.

## Tire Distance Studio

- `tools/tire_distance_studio/` adds a standalone Windows/Tkinter interface for tire-distance analysis, visualization, manual annotation, and model training. Its UI validates settings before sending immutable configuration to worker threads, reports progress through a queue, and avoids overwriting same-name CSV outputs.
- The distance it displays is measured in image pixels. It is not a real-world distance unless a separate camera/road calibration is applied. The Studio’s README and developer guide describe setup, coordinates, and thread-safety rules.

## Knowledge and developer support

- The repository now contains a registry for Software, Output, and Analysis Vaults, retrieval/run-creation helpers, and notes describing the save and retrieval contracts. The analysis and output folders also contain their workflow and catalog notes.
- Root-level helper scripts cover CVAT annotation and speed analyses, measurement smoothing, calibration distortion and projection checks, comparison plots, database visualization, and presentation generation.
- `.gitignore` excludes local secrets and personal Obsidian settings, while marking analysis/output artifact folders as durable local storage rather than cleanup targets.
- New or extended test files cover measurement points, homography projection, rolling regression, and related projection/speed behavior. Tests were not run for this workspace snapshot, so no pass/fail claim is made here.

## Related analysis records

These are separate dated experiment records that provide context for measurement-point and calibration work. They do not verify the current workspace code:

- `docs/analysis-vault/10-Experiments/adc-run-20260923T174743Z-cvat-projection-speed-review-03a800ea.md`
- `docs/analysis-vault/10-Experiments/adc-run-20260923T200734Z-manual-auto-distance-speed-820f6b9f.md`
- `docs/analysis-vault/10-Experiments/adc-run-20260923T193140Z-center-dash-speed-graph-c9102434.md`

## Main code references

- Measurement and speed: `Source_code/modules/measure_points.py`, `Source_code/modules/speed_regression.py`, `Source_code/modules/speed/`, `Source_code/modules/speed_homography/`, `Source_code/modules/speed_y_axis/`
- Calibration: `Source_code/modules/homography_preview.py`, `Source_code/tools/calibration_tool.py`, `Source_code/routes/calibration.py`, `templates/calibration.html`
- Reports and insights: `Source_code/modules/comparative_report.py`, `Source_code/modules/ai_insight.py`, `Source_code/routes/analysis.py`, `templates/comparative_report.html`
- Inference and shared UI: `Source_code/modules/inference.py`, `Source_code/modules/resource_monitor.py`, `Source_code/routes/inference.py`, `templates/detect.html`, `templates/base.html`, `Source_code/static/`
- Tire Distance Studio: `tools/tire_distance_studio/README.md`, `tools/tire_distance_studio/DEVELOPER_GUIDE.md`
- Specification and tests: `docs/ADC_System_Specification.md`, `tests/test_measure_points.py`, `tests/test_speed_regression.py`, `tests/test_speed_homography.py`, `tests/test_homography_preview.py`
