"""YOLO検出や手動追い越しで利用するクラスフィルタを集約するモジュール。"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable, Set, Tuple

_DEFAULT_VEHICLE_CLASSES: Set[str] = {"car", "truck", "bus", "bicycle"}
_ENV_KEYS: Tuple[str, ...] = (
    "YOLO11X_ALLOWED_CLASSES",
    "YOLOV8X_ALLOWED_CLASSES",
)


def _parse_class_list(value: str | None, fallback: Iterable[str]) -> Set[str]:
    """環境変数からクラス名リストを読み取り、小文字集合を返す。"""

    if not value:
        return {cls.lower() for cls in fallback}
    tokens = [token.strip().lower() for token in value.split(",")]
    filtered = {token for token in tokens if token}
    return filtered or {cls.lower() for cls in fallback}


@lru_cache(maxsize=1)
def vehicle_allowed_classes() -> Tuple[str, ...]:
    """車両検出に使用する許可クラス集合を返す（ソート済みタプル）。"""

    env_value: str | None = None
    for key in _ENV_KEYS:
        env_value = os.getenv(key)
        if env_value:
            break
    allowed = _parse_class_list(env_value, _DEFAULT_VEHICLE_CLASSES)
    return tuple(sorted(allowed))


def is_vehicle_class(name: str | None) -> bool:
    """車両クラスとして扱うかどうかを判定する。"""

    if not name:
        return False

    normalized = str(name).strip().lower()
    if not normalized:
        return False

    allowed = set(vehicle_allowed_classes())
    if normalized in allowed:
        return True

    alias_map = {
        "pushbike": "bicycle",
        "bike": "bicycle",
        "bikes": "bicycle",
        "cars": "car",
        "trucks": "truck",
        "buses": "bus",
    }
    mapped = alias_map.get(normalized)
    return bool(mapped and mapped in allowed)
