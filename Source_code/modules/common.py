from dataclasses import dataclass
from typing import Optional

@dataclass
class DistanceResult:
    """距離計算結果を保持するクラス"""
    px: float
    cm: float
    m: float
    px_ratio: Optional[float] = None
