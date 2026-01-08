# 役割: 並列処理に関する共通ユーティリティ関数
from __future__ import annotations

import os
from typing import Optional


def resolve_worker_count(
    env_var: str,
    fallback: Optional[int] = None,
    *,
    min_workers: int = 1,
    max_workers: Optional[int] = None,
) -> int:
    """環境変数やCPUコア数からスレッド数を決定する"""

    if fallback is None:
        cpu_count = os.cpu_count() or 1
        fallback = max(min_workers, cpu_count - 1)

    workers = fallback

    env_value = os.getenv(env_var)
    if env_value:
        try:
            parsed = int(env_value)
        except ValueError:
            parsed = None
        if parsed and parsed > 0:
            workers = parsed

    if max_workers is not None:
        workers = min(workers, max_workers)

    workers = max(min_workers, workers)
    return workers


__all__ = ["resolve_worker_count"]
