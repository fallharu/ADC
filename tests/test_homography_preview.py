import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest
from flask import Blueprint, Flask

from Source_code.modules.homography_preview import render_homography_preview
from Source_code.modules.speed_homography import HomographyProjection, apply_homography_speed
from test_speed_homography import _empty_vertical_context, _trajectory


def geometry():
    return {
        "image_points": [[0, 0], [100, 0], [100, 200], [0, 200]],
        "width_m": 10, "length_m": 20,
    }


@pytest.mark.parametrize("model", ["standard", "fisheye"])
def test_lens_and_nonuniform_distance_correction_match_speed(model):
    camera = {
        "model": model,
        "camera_matrix": [[300, 0, 50], [0, 300, 100], [0, 0, 1]],
        "dist_coeffs": [0.08, -0.01, 0.001, 0.002],
    }
    meta = geometry()
    meta["longitudinal_correction"] = {
        "estimated_positions_m": [0, 8, 20],
        "corrected_positions_m": [2, 6, 16],
    }
    projection = HomographyProjection(meta, camera)
    # Includes both ends and points outside the correction knots (offset extrapolation).
    world = np.array([[5, 1], [5, 2], [5, 5], [5, 10], [5, 16], [5, 17]])
    pixels = projection.world_to_image(world)
    np.testing.assert_allclose(projection.image_to_world(pixels), world, atol=2e-4)

    measured = world[1:4]
    pixels = projection.world_to_image(measured)
    df = _trajectory(pixels[:, 1])
    df["smooth_measure_x"] = pixels[:, 0]
    assert apply_homography_speed(
        df, df.frame_num.diff() / 10, 10, 10, meta,
        _empty_vertical_context(df.index), camera_meta=camera, speed_window_frames=2,
    )
    np.testing.assert_allclose(df.world_y, measured[:, 1], atol=2e-4)
    assert df.loc[2, "speed_mps"] == pytest.approx(40, abs=0.002)


@pytest.mark.parametrize("horizontal", [False, True])
@pytest.mark.parametrize("reversed_order", [False, True])
def test_preview_pixels_and_rulers_use_corrected_distance(horizontal, reversed_order):
    # A known stripe at image y=80 is raw 8m and corrected 10m.
    frame = np.zeros((201, 101, 3), dtype=np.uint8)
    frame[78:83, :, 1] = 255
    meta = geometry()
    if reversed_order:
        meta["image_points"] = [[0, 200], [100, 200], [100, 0], [0, 0]]
    meta["interval_m"] = 10
    lines = [[[0, y], [100, y]] for y in [0, 80, 200]]
    payload = {"scale": {"homography": meta, "lines": lines}}
    image, info = render_homography_preview(frame, payload, 101, 201, horizontal)
    assert info["longitudinal_corrected"]
    np.testing.assert_allclose(info["stations_m"], [0, 10, 20], atol=1e-5)
    assert info["zero_is_near"] == reversed_order
    if horizontal:
        assert image[50, 50, 1] > 245
    else:
        assert image[100, 50, 1] > 245


def test_preview_extent_and_explicit_correction_override_guides():
    meta = geometry()
    meta.update(interval_m=10, longitudinal_correction={
        "estimated_positions_m": [0, 20], "corrected_positions_m": [3, 13],
    })
    payload = {"scale": {"homography": meta, "lines": [[[0, y], [100, y]] for y in [0, 80, 200]]}}
    frame = np.zeros((201, 101, 3), dtype=np.uint8)
    image, info = render_homography_preview(frame, payload, 101, 201)
    assert info["length_m"] == 10
    assert info["y_min_m"] == 3
    assert info["y_max_m"] == 13
    np.testing.assert_allclose(info["stations_m"], [0, 6, 10], atol=1e-5)
    assert image.shape == (101, 101, 3)


def test_invalid_geometry_is_rejected():
    meta = geometry()
    meta["image_points"] = [[0, 0], [1, 1], [2, 2], [3, 3]]
    with pytest.raises(ValueError):
        HomographyProjection(meta)


@pytest.fixture
def preview_api():
    # Load this route module without importing the full app or migrating a real DB.
    package = types.ModuleType("Source_code.routes")
    package.main = Blueprint("main", __name__)
    name = "Source_code.routes.calibration"
    path = Path(__file__).parents[1] / "Source_code/routes/calibration.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    folder_utils = types.ModuleType("Source_code.modules.folder_utils")
    folder_utils.find_source_video_path = mock.Mock()
    with mock.patch.dict(sys.modules, {
        "Source_code.routes": package, name: module,
        "Source_code.modules.folder_utils": folder_utils,
    }), mock.patch("dotenv.load_dotenv"):
        spec.loader.exec_module(module)
    app = Flask(__name__)
    app.add_url_rule("/preview/<int:run_id>", view_func=module.calibration_homography_preview, methods=["POST"])
    return app.test_client(), module


def test_preview_api_uses_requested_frame_and_unsaved_calibration(preview_api):
    client, module = preview_api
    with mock.patch.object(module, "_get_video_path_calib", return_value="test-video") as resolve, mock.patch.object(
        module, "load_video_frame", return_value=np.zeros((201, 101, 3), dtype=np.uint8)
    ) as load:
        response = client.post("/preview/0?path_hint=test-video", json={
            "frame": 7, "width": 101, "height": 201,
            "calibration": {"scale": {"homography": geometry()}},
        })
    assert response.status_code == 200
    resolve.assert_called_once_with(0, "test-video")
    load.assert_called_once_with("test-video", 7)
    assert response.json["image"].startswith("data:image/png;base64,")
    assert response.json["length_m"] == 20


def test_preview_api_rejects_oversized_requests_before_reading_video(preview_api):
    client, module = preview_api
    with mock.patch.object(module, "load_video_frame") as load:
        response = client.post("/preview/1", json={"width": 2400, "height": 2400})
    assert response.status_code == 400
    load.assert_not_called()
