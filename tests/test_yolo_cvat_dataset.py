import numpy as np
import pandas as pd

from scripts.build_yolo_cvat_speed_clearance import Projection, project_tracks, validate


def moving_track():
    frames = np.arange(15)
    return pd.DataFrame(dict(track_id=1, frame_num=frames, label="car",
                             measure_x=5., measure_y=80.-frames*2))


def projection():
    return Projection(dict(image_points=[[0,100],[10,100],[10,0],[0,0]], width_m=10, length_m=100))


def test_known_velocity_and_resolution_conversion():
    raw = moving_track()
    result = project_tracks(raw, projection(), 10, "YOLO", 1.)
    np.testing.assert_allclose(result.speed_km_h.dropna(), 72., atol=1e-6)
    raw[["measure_x", "measure_y"]] *= 1.5
    scaled = project_tracks(raw, projection(), 10, "YOLO", 2/3)
    np.testing.assert_allclose(scaled.speed_km_h.dropna(), result.speed_km_h.dropna())


def test_regression_does_not_cross_a_detection_gap():
    raw = moving_track().drop(index=7)
    result = project_tracks(raw, projection(), 10, "YOLO", 1.)
    assert result.loc[result.frame_num.isin([8,9]), "speed_km_h"].isna().all()
    np.testing.assert_allclose(result.loc[result.frame_num==10, "speed_km_h"], 72., atol=1e-6)


def test_cvat_held_tail_does_not_become_stationary_training_data():
    raw = moving_track()
    raw["x1"]=3.; raw["x2"]=5.; raw["y2"]=raw.measure_y
    raw["is_keyframe"]=raw.frame_num.isin([0,10]).astype(int)
    raw["is_held"]=(raw.frame_num>10).astype(int)
    result=project_tracks(raw,projection(),10,"CVAT",1.)
    assert result.loc[result.frame_num>10,"speed_km_h"].isna().all()
    np.testing.assert_allclose(result.speed_km_h.dropna(),72.,atol=1e-6)


def test_video_overlap_is_rejected_even_when_sample_ids_differ():
    table=pd.DataFrame(dict(sample_id=["a","b","c","d"],
                            source_id=["same","same","other","other"],
                            split=["train","val","train","val"],
                            method=["YOLO","YOLO","CVAT","CVAT"], speed_km_h=[20.]*4))
    import pytest
    with pytest.raises(AssertionError):
        validate(table,table,table.assign(clearance_m=1.))
