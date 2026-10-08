"""Replay real CVAT tracks against a compact, derived speed baseline.

The XML and calibration are read in place; their annotations and media are not
copied into the repository. Locally, the matching Downloads data is found
automatically. Elsewhere, set ADC_CVAT_XML and ADC_CVAT_CALIBRATION. The
reference JSON contains aggregate metrics only.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest


REFERENCE = Path(__file__).parent / "fixtures" / "cvat_speed_reference.json"


def _cvat_inputs():
    xml_path = os.environ.get("ADC_CVAT_XML")
    calibration_path = os.environ.get("ADC_CVAT_CALIBRATION")
    downloads = Path.home() / "Downloads"
    if not xml_path:
        candidates = list(downloads.glob("job_2_annotations_*/annotations.xml"))
        if len(candidates) == 1:
            xml_path = str(candidates[0])
    if not calibration_path:
        candidates = list((downloads / "G_ADC" / "OutPut").glob(
            "*/recalc_*_2_20250720_y/calibration.json"
        ))
        if len(candidates) == 1:
            calibration_path = str(candidates[0])
    if not xml_path or not calibration_path:
        pytest.skip("Set ADC_CVAT_XML and ADC_CVAT_CALIBRATION for the real CVAT regression")
    if not Path(xml_path).is_file() or not Path(calibration_path).is_file():
        pytest.fail("CVAT XML or calibration file does not exist")
    return xml_path, calibration_path


def test_cvat_processed_speed_and_distance_regression():
    xml_path, calibration_path = _cvat_inputs()

    from scripts.analyze_cvat_measurement_smoothing import (
        add_legacy_smoothing,
        add_measure_points,
        mark_active_motion,
        read_cvat_tracks,
    )
    from scripts.visualize_cvat_distance_speed import (
        LanePerspectiveModel,
        VerticalLadder,
        add_calibrated_positions,
        add_lateral_distance,
        add_speed_columns,
        build_summary,
        enforce_monotonic_depth,
        scale_calibration_geometry,
    )
    from Source_code.modules.measure_points import stabilize_measure_points

    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    with open(calibration_path, encoding="utf-8-sig") as handle:
        calibration = json.load(handle)
    video_width, video_height = reference["video_size"]
    calibration_width, calibration_height = reference["calibration_size"]
    calibration = scale_calibration_geometry(
        calibration,
        video_width / calibration_width,
        video_height / calibration_height,
    )
    ladder = VerticalLadder(calibration.get("scale") or {})
    assert ladder.ready
    perspective = LanePerspectiveModel(calibration, ladder)
    assert perspective.ready

    annotations = read_cvat_tracks(xml_path)
    frame = mark_active_motion(add_measure_points(annotations))
    assert frame["active_motion"].sum() < len(annotations)  # Exclude CVAT's unchanged tail.
    frame = add_legacy_smoothing(frame, window=11)
    frame = stabilize_measure_points(frame, window=11)
    frame = add_calibrated_positions(frame, ladder, perspective)
    frame = enforce_monotonic_depth(frame)
    frame = add_lateral_distance(frame, perspective.lane_width_m)
    result = build_summary(add_speed_columns(frame, reference["fps"]), reference["fps"])

    assert len(result) == len(reference["tracks"]) == 5
    actual = result.set_index("track_id")
    for expected in reference["tracks"]:
        row = actual.loc[expected["track_id"]]
        assert row["label"] == expected["label"]
        for key in ("active_frames", "calibrated_frames", "strict_calibrated_frames"):
            assert row[key] == expected[key]
        for key in (
            "calibrated_duration_s", "traveled_distance_m", "median_speed_km_h",
            "max_speed_km_h", "endpoint_speed_roughness_km_h",
            "regression_speed_roughness_km_h",
        ):
            assert np.isfinite(row[key])
            assert row[key] == pytest.approx(expected[key], abs=0.02)
        assert row["regression_speed_roughness_km_h"] < row["endpoint_speed_roughness_km_h"]


def test_cvat_road_points_agree_with_road_scale_projection():
    """Check the shared homography on actual CVAT contact points across the road.

    This is a consistency check against the existing lane-width perspective
    estimate, not an independent ground-truth measurement of vehicle speed.
    """
    xml_path, calibration_path = _cvat_inputs()

    from scripts.analyze_cvat_measurement_smoothing import (
        add_measure_points, mark_active_motion, read_cvat_tracks,
    )
    from scripts.visualize_cvat_distance_speed import (
        LanePerspectiveModel, VerticalLadder, _coerce_line_points,
        scale_calibration_geometry,
    )
    from Source_code.modules.speed_homography import HomographyProjection

    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    with open(calibration_path, encoding="utf-8-sig") as handle:
        calibration = json.load(handle)
    video_width, video_height = reference["video_size"]
    calibration_width, calibration_height = reference["calibration_size"]
    calibration = scale_calibration_geometry(
        calibration, video_width / calibration_width, video_height / calibration_height,
    )
    ladder = VerticalLadder(calibration["scale"])
    perspective = LanePerspectiveModel(calibration, ladder)
    far_y = float(_coerce_line_points(ladder.lines[0])[0][1])
    near_y = float(_coerce_line_points(ladder.lines[-1])[0][1])
    far = perspective._details(far_y)
    near = perspective._details(near_y)
    assert far.is_available and near.is_available

    def edge_pair(details):
        return sorted((float(details.left_point[0]), float(details.right_point[0])))

    near_left, near_right = edge_pair(near)
    far_left, far_right = edge_pair(far)
    projection = HomographyProjection({
        "image_points": [
            [near_left, near_y], [near_right, near_y],
            [far_right, far_y], [far_left, far_y],
        ],
        "width_m": perspective.lane_width_m,
        "length_m": ladder.calibrated_length_m,
    })
    annotations = mark_active_motion(add_measure_points(read_cvat_tracks(xml_path)))
    sample = annotations[annotations["active_motion"] & annotations["measure_y"].between(far_y, near_y)]
    assert len(sample) >= 500
    sample = sample.sample(n=500, random_state=1)
    image_points = sample[["measure_x", "measure_y"]].to_numpy(dtype=float)
    projected = projection.image_to_world(image_points)
    reference_points = np.array([
        perspective.world_point(x, y) for x, y in image_points
    ])
    valid = np.isfinite(projected).all(axis=1) & np.isfinite(reference_points).all(axis=1)
    assert valid.sum() >= 400
    depth_error = np.abs(projected[valid, 1] - reference_points[valid, 1])
    assert depth_error.mean() < 0.85  # metres across the 16 m calibrated range
    assert depth_error.max() < 1.5
    np.testing.assert_allclose(
        projection.world_to_image(projected[valid]), image_points[valid], atol=1e-3,
    )
