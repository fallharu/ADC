from flask import Blueprint

main = Blueprint("main", __name__)

from . import (
    index,
    manual,
    analysis,
    post_process,
    misc,
    calibration,
    database,
    video,
    inference,
    export_routes,
)

from .inference import yolo_progress

@main.context_processor
def inject_progress():
    return dict(yolo_progress=yolo_progress)
