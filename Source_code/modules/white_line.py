# Source_code/modules/white_line.py
# ==========================================
# 白線距離用プログラム (モジュール)
# ==========================================
# 車線幅（白線間距離）に基づいた座標変換や距離計算のロジックを提供します。

from typing import Optional, Dict
from ..modules.common import DistanceResult # Fixed import for ADC_08 structure

# デフォルトの車線幅 (メートル)
DEFAULT_LANE_WIDTH_M: float = 3.5

def calculate_pixel_to_meter_ratio(
    lane_width_px: float,
    lane_width_m: float = DEFAULT_LANE_WIDTH_M
) -> Optional[float]:
    """
    ピクセルからメートルへの変換比率を計算する。
    
    Args:
        lane_width_px: 車線幅 (ピクセル)
        lane_width_m: 車線幅 (メートル)。デフォルトは3.5m。
    
    Returns:
        Optional[float]: cm/px の変換比率。計算不可の場合はNone。
    
    Note:
        この比率を用いて、ピクセル距離を実距離に変換します。
        cm_per_px = (lane_width_m * 100) / lane_width_px
    """
    if lane_width_px <= 0:
        return None
    
    return (lane_width_m * 100.0) / lane_width_px


def convert_distance_units(
    distance_px: float,
    cm_per_px: float,
    lane_width_px: Optional[float] = None
) -> DistanceResult:
    """
    ピクセル距離を実距離に変換する。
    
    Args:
        distance_px: ピクセル単位の距離
        cm_per_px: ピクセル→センチメートルの変換比率
        lane_width_px: 車線幅 (ピクセル)。指定時は比率も計算。
    
    Returns:
        DistanceResult: 各単位での距離
    """
    distance_cm = distance_px * cm_per_px
    distance_m = distance_cm / 100.0
    
    px_ratio = None
    if lane_width_px and lane_width_px > 0:
        px_ratio = (distance_px / lane_width_px) * 100.0
    
    return DistanceResult(
        px=distance_px,
        cm=distance_cm,
        m=distance_m,
        px_ratio=px_ratio
    )


def harmonize_manual_distance_units(
    overtaker_px: float,
    lane_width_px: float,
    lane_width_m: float = DEFAULT_LANE_WIDTH_M
) -> Optional[Dict[str, float]]:
    """
    手動計測距離の単位を整合させる。
    
    Args:
        overtaker_px: 追い越し車両の車線からの距離 (ピクセル)
        lane_width_px: 車線幅 (ピクセル)
        lane_width_m: 車線幅 (メートル)
    
    Returns:
        Optional[Dict[str, float]]: 変換結果の辞書
            - cm_per_px: 変換比率
            - distance_m: メートル単位の距離
            - distance_cm: センチメートル単位の距離
            - px_ratio: 車線幅に対する比率 (%)
    """
    if lane_width_px <= 0:
        return None
    
    cm_per_px = (lane_width_m * 100.0) / lane_width_px
    distance_cm = overtaker_px * cm_per_px
    distance_m = distance_cm / 100.0
    px_ratio = (overtaker_px / lane_width_px) * 100.0
    
    return {
        "cm_per_px": cm_per_px,
        "distance_m": distance_m,
        "distance_cm": distance_cm,
        "px_ratio": px_ratio
    }


def check_line_crossing(
    point_x: float,
    point_y: float,
    line_points: list[list[float]],
    direction: str = "left"
) -> bool:
    """
    指定した点が線を越えているかを判定する。
    
    Args:
        point_x: 点のX座標
        point_y: 点のY座標
        line_points: 線の点群 [[x1, y1], [x2, y2], ...] (Y座標でソート済み前提)
        direction: 越境判定の方向 ("left", "right")
            - "left": 線より左側ならTrue (右側通行で左白線を越えて外へ出る場合など)
                     ※ここでは「G_ADC」の要件に合わせて、
                       Left line (白線): x < line_x (左側にある = 外側) -> True
                       Center line (中央線): x > line_x (右側にある = 対向車線) -> True
                       と文脈に合わせて呼び出し元で指定することを想定。
                       
                       シンプルに:
                       direction="smaller": point_x < line_x なら True
                       direction="larger": point_x > line_x なら True
    
    Returns:
        bool: 越えている場合はTrue
    """
    if not line_points:
        return False
        
    # Y座標に基づいて対応する線分を探す
    # 線形補間して、そのYにおける線のX座標を求める
    
    target_line_x = None
    
    # 完全に範囲外の場合の処理 (外挿するか、直近を使うか)
    # ここでは直近の点を使う簡易実装とする
    if point_y <= line_points[0][1]:
        target_line_x = line_points[0][0]
    elif point_y >= line_points[-1][1]:
        target_line_x = line_points[-1][0]
    else:
        # 範囲内の場合、挟む2点を探す
        for i in range(len(line_points) - 1):
            p1 = line_points[i]
            p2 = line_points[i+1]
            
            if p1[1] <= point_y <= p2[1]:
                # 線形補間
                ratio = (point_y - p1[1]) / (p2[1] - p1[1]) if p2[1] != p1[1] else 0
                target_line_x = p1[0] + (p2[0] - p1[0]) * ratio
                break
    
    if target_line_x is None:
        return False
        
    if direction == "smaller": # x < line_x (左側)
        return point_x < target_line_x
    elif direction == "larger": # x > line_x (右側)
        return point_x > target_line_x
        
    return False


def get_line_x_at_y(
    y: float,
    line_points: list[list[float]]
) -> Optional[float]:
    """
    指定されたY座標における線のX座標を線形補間で求める。
    line_points: [[x1, y1], [x2, y2], ...] (yでソート済み前提)
    """
    if not line_points or len(line_points) < 2:
        return None
        
    # Yでソート (念のため)
    # line_points.sort(key=lambda p: p[1]) 

    min_y = min(p[1] for p in line_points)
    max_y = max(p[1] for p in line_points)
    
    # 範囲外チェック: 多少の余裕を持たせるか、Noneにするか。
    # ユーザー要望は画面全体のスケール感なので、外挿も考慮すべきかもしれないが、
    # まずは内挿のみで実装。Yが範囲外の場合はNoneを返す。
    # Clamping: Yが範囲外の場合は端点を使用
    if y < min_y:
        # 一番上の点を探す (Yが最小)
        p = min(line_points, key=lambda p: p[1])
        return p[0]
    if y > max_y:
        # 一番下の点を探す (Yが最大)
        p = max(line_points, key=lambda p: p[1])
        return p[0]

    # 各区間をチェック
    for i in range(len(line_points) - 1):
        p1 = line_points[i]
        p2 = line_points[i+1]
        
        y1, y2 = p1[1], p2[1]
        
        # yがこの区間に含まれるか (順序不問)
        if (y1 <= y <= y2) or (y2 <= y <= y1):
            if y1 == y2: # 水平
                return p1[0]
            
            # 線形補間
            ratio = (y - y1) / (y2 - y1)
            x = p1[0] + ratio * (p2[0] - p1[0])
            return x
            
    return None


def calculate_dynamic_scale_at_y(
    y: float,
    left_line: list[list[float]],
    center_line: list[list[float]],
    real_lane_width_m: float = 3.5
) -> Dict[str, Optional[float]]:
    """
    指定されたY座標におけるレーン幅(px)と動的スケール(m/px)を算出する。
    
    Returns:
        Dict:
            - lane_width_px: float
            - scale_m_per_px: float
            - left_x: float (at y)
            - center_x: float (at y)
    """
    lx = get_line_x_at_y(y, left_line)
    cx = get_line_x_at_y(y, center_line)
    
    result = {
        "lane_width_px": None,
        "scale_m_per_px": None,
        "left_x": lx,
        "center_x": cx
    }
    
    if lx is not None and cx is not None:
        width_px = abs(cx - lx)
        if width_px > 1.0: # 0除算防止
            result["lane_width_px"] = width_px
            result["scale_m_per_px"] = real_lane_width_m / width_px
            
    return result


def calculate_metric_x_from_lines(
    x: float,
    y: float,
    left_line: list[list[float]],
    center_line: list[list[float]],
    right_line: list[list[float]] = None,
    lane_width_left_m: float = 3.5,
    lane_width_right_m: float = 3.5
) -> Dict[str, Optional[float]]:
    """
    指定された座標(x, y)の、センターラインを基準(0m)とした横方向のメートル位置を計算する。
    左レーンと右レーンで個別のスケールを使用する (非対称/遠近対応)。
    
    Args:
        x: 対象点のX座標
        y: 対象点のY座標
        left_line: 左白線
        center_line: 中央線
        right_line: 右白線 (Optional)
        lane_width_left_m: 左レーンの実幅 (m). Defaults to 3.5.
        lane_width_right_m: 右レーンの実幅 (m). Defaults to 3.5.
        
    Returns:
        Dict:
            - pos_x_m: float (センターライン基準のメートル位置。左は負、右は正)
            - scale_m_per_px: float (その位置での適用スケール)
    """
    lx = get_line_x_at_y(y, left_line)
    cx = get_line_x_at_y(y, center_line)
    rx = get_line_x_at_y(y, right_line) if right_line else None
    
    result = {
        "pos_x_m": None,
        "scale_m_per_px": None
    }
    
    if cx is None:
        return result
        
    # Scale Calculation
    scale_left = None
    scale_right = None
    
    if lx is not None:
        width_left_px = abs(cx - lx)
        if width_left_px > 1.0:
            scale_left = lane_width_left_m / width_left_px
            
    if rx is not None:
        width_right_px = abs(rx - cx)
        if width_right_px > 1.0:
            scale_right = lane_width_right_m / width_right_px

    # If right line is missing, assume symmetric scale (scaled by width ratio naturally if using perspective, 
    # but here we just copy the value if we assume symmetric LENS/Camera)
    # ユーザー要望: "白線から両側+2m分の助恵右を作成し" -> 右白線がない場合の推測が必要かもだが、
    # 基本はCalibがあれば使う。なければ左のスケールを代用するか、ユーザー入力幅のみに頼る。
    if scale_right is None and scale_left is not None:
        scale_right = scale_left # Fallback
    if scale_left is None and scale_right is not None:
        scale_left = scale_right
        
    # Determine Position
    if x <= cx:
        # On the Left Side
        if scale_left:
            # cx is 0m. Moving left (smaller x) means negative meters.
            dist_px = cx - x
            result["pos_x_m"] = -(dist_px * scale_left)
            result["scale_m_per_px"] = scale_left
    else:
        # On the Right Side
        if scale_right:
            # cx is 0m. Moving right (larger x) means positive meters.
            dist_px = x - cx
            result["pos_x_m"] = dist_px * scale_right
            result["scale_m_per_px"] = scale_right
            
    return result
