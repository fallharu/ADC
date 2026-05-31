# 役割: 追い越し判定（フラグと相手ID）、および追い越しイベントの速度プロファイル保存
import sqlite3
from typing import List, Optional, Tuple

import pandas as pd
from tqdm import tqdm
import json
import os
from pathlib import Path
from dotenv import load_dotenv
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .db_manager import (
    MAIN_DB_PATH,
    configure_connection,
    ensure_detection_distance_columns,
    ensure_overtake_event_columns,
)
from .video_path_resolver import collect_video_candidates
from .calibration_loader import load_calibration_json

OVERTAKE_EVENT_INSERT_COLUMNS = [
    "run_id",
    "event_frame_num",
    "overtaker_group_id",
    "overtaken_group_id",
    "overtaker_auto_id",
    "overtaken_auto_id",
    "approach_distance_px",
    "approach_distance_m",
    "clearance_distance_px",
    "clearance_distance_m",
    "clearance_distance_cm",
    "l_line_distance",
    "l_line_distance_m",
    "l_line_distance_cm",
    "r_line_distance",
    "r_line_distance_m",
    "r_line_distance_cm",
    "line_distance",
    "line_distance_m",
    "line_distance_cm",
    "speed_profile_json",
    "overtaker_l_line_cross_m",
    "overtaker_r_line_cross_m",
    "overtaken_l_line_cross_m",
    "overtaken_r_line_cross_m",
]

_OVERTAKE_EVENT_INSERT_SQL = (
    "INSERT INTO OvertakeEvents ("
    + ", ".join(OVERTAKE_EVENT_INSERT_COLUMNS)
    + ") VALUES ("
    + ", ".join(["?"] * len(OVERTAKE_EVENT_INSERT_COLUMNS))
    + ")"
)

load_dotenv()


def _resolve_aliases(env_key: str, defaults: str) -> set[str]:
    raw = os.getenv(env_key, defaults)
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def _select_representative_class(values: pd.Series) -> str:
    if values.empty:
        return ""
    mode = values.mode()
    if not mode.empty:
        return str(mode.iat[0])
    return str(values.iat[0])


def _safe_float(value) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


_SKIP_REASON_JP = {
    "Bike Detected": "自転車検出",
    "Direction Mismatch or Invalid": "進行方向が不一致/無効",
    "Never Adjacent": "並走フレームなし",
    "No Behind State Detected": "後方状態なし",
    "No Ahead State Detected": "前方状態なし",
    "Order Invalid": "前後順序が不正",
    "Crossing Gap Too Large": "交差ギャップが大きい",
    "Ray-Cast: Dist Too Large": "レイキャスト: 距離が大きい",
    "Unknown": "不明",
}


def _to_skip_reason_jp(reason: str) -> str:
    return _SKIP_REASON_JP.get(reason, reason)


# ローカルフォントパスの候補
# プロジェクトルートからの相対パスを解決
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOCAL_FONT_PATHS = [
    os.path.join(_PROJECT_ROOT, "fonts", "Noto_Sans_JP", "NotoSansJP-VariableFont_wght.ttf"),
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/arial.ttf",
]

_cached_font: dict = {}


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """ローカルフォントを取得（キャッシュ付き）。"""
    if size in _cached_font:
        return _cached_font[size]
    
    for font_path in _LOCAL_FONT_PATHS:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, size)
                _cached_font[size] = font
                print(f"[overtake] フォント読み込み成功: {font_path}")
                return font
            except Exception as e:
                print(f"[overtake] フォント読み込み失敗: {font_path} - {e}")
                continue
    
    # フォールバック: デフォルトフォント
    print("[overtake] 警告: 日本語フォントが見つかりません。デフォルトフォントを使用します。")
    font = ImageFont.load_default()
    _cached_font[size] = font
    return font


def _put_text_pil(
    img: np.ndarray,
    text: str,
    position: Tuple[int, int],
    font_size: int = 32,
    color: Tuple[int, int, int] = (255, 255, 255),
    bg_color: Optional[Tuple[int, int, int]] = None,
) -> np.ndarray:
    """PILを使ってOpenCV画像にテキストを描画する。"""
    # OpenCV (BGR) -> PIL (RGB)
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    font = _get_font(font_size)
    
    # テキストサイズを取得
    try:
        bbox = draw.textbbox(position, text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except AttributeError:
        # 旧バージョンのPillow
        text_width, text_height = draw.textsize(text, font=font)
        bbox = (position[0], position[1], position[0] + text_width, position[1] + text_height)
    
    # 背景を描画
    if bg_color:
        padding = 4
        bg_bbox = (bbox[0] - padding, bbox[1] - padding, bbox[2] + padding, bbox[3] + padding)
        draw.rectangle(bg_bbox, fill=bg_color)
    
    # テキストを描画 (RGB)
    draw.text(position, text, font=font, fill=color)
    
    # PIL (RGB) -> OpenCV (BGR)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def _export_overtake_snapshots(
    run_id: int,
    snapshot_requests: List[dict],
    *,
    output_folder: Optional[str],
    video_filename: Optional[str],
    source_path: Optional[str],
    folder_alias: Optional[str],
    calibration_profile: Optional[str],
    calibration_data: Optional[dict] = None,
) -> int:
    """追い越し発生フレームの静止画を保存する。生成枚数を返す。"""

    if not snapshot_requests:
        return 0

    upload_folder = os.getenv("Upload_folder", "uploads")

    candidates = collect_video_candidates(
        upload_folder=upload_folder,
        filename=video_filename or "",
        source_path=source_path,
        output_folder=output_folder,
        folder_alias=folder_alias,
    )

    video_path = next((path for path in candidates if os.path.exists(path)), None)
    video_path = next((path for path in candidates if os.path.exists(path)), None)
    
    # Fallback: Try source_path directly if resolver failed but source_path exists
    if video_path is None and source_path and os.path.exists(source_path):
        video_path = source_path
        print(f"[assign_overtake] リゾルバで動画が見つかりませんでしたが、source_path ({source_path}) を使用します。")

    if video_path is None:
        print(
            "[assign_overtake] 🛑 追い越しスナップショット用の動画が見つかりません。探索候補:\n"
            + "\n".join(candidates)
        )
        if source_path:
             print(f"source_path: {source_path} (存在しません)")
        return
    
    print(f"[assign_overtake] 動画ファイルをオープンします: {video_path}")

    try:
        cap = cv2.VideoCapture(video_path)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[assign_overtake] 動画のオープンに失敗したためスナップショット生成をスキップします: {exc}"
        )
        return 0

    if not cap.isOpened():
        print(f"[assign_overtake] 動画が開けないためスナップショット生成をスキップします: {video_path}")
        cap.release()
        return 0

    snapshot_dir = Path(output_folder or os.path.dirname(video_path)) / "overtake_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    calibration = calibration_data
    left_line_points: Optional[np.ndarray] = None
    right_line_points: Optional[np.ndarray] = None
    if calibration is None and calibration_profile:
        try:
            calibration, _ = load_calibration_json(run_id, calibration_profile)
        except Exception as exc:  # noqa: BLE001
            print(
                "[assign_overtake] スナップショット描画用のキャリブレーション取得に失敗しました:"
                f" {exc}"
            )

    if calibration:
        lines = calibration.get("lines", {}) if isinstance(calibration, dict) else {}

        def _to_array(points) -> Optional[np.ndarray]:
            if not points:
                return None
            try:
                arr = np.array(points, dtype=float)
            except Exception:
                return None
            if arr.ndim != 2 or arr.shape[1] != 2:
                return None
            return arr

        left_line_points = _to_array(lines.get("left_white_line"))
        right_line_points = _to_array(lines.get("right_white_line"))

    def _interpolate_lane_x(points: Optional[np.ndarray], y: int) -> Optional[float]:
        if points is None or len(points) < 2:
            return None
        for idx in range(len(points) - 1):
            x1, y1 = points[idx]
            x2, y2 = points[idx + 1]
            if (y1 <= y <= y2) or (y2 <= y <= y1):
                if y2 == y1:
                    return float(x1)
                ratio = (y - y1) / (y2 - y1)
                return float(x1 + ratio * (x2 - x1))
        return None

    def _as_point(value) -> Optional[Tuple[int, int]]:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return None
        try:
            x_val = float(value[0])
            y_val = float(value[1])
        except (TypeError, ValueError):
            return None
        if not np.isfinite(x_val) or not np.isfinite(y_val):
            return None
        return int(round(x_val)), int(round(y_val))

    def _format_clearance_label(payload: dict) -> Optional[str]:
        for key, unit in (
            ("clearance_cm", "cm"),
            ("clearance_m", "m"),
            ("clearance_px", "px"),
            ("approach_m", "m"),
            ("approach_px", "px"),
        ):
            value = payload.get(key)
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(numeric):
                continue
            if unit == "cm":
                return f"離隔:{numeric:.0f}cm"
            if unit == "m":
                return f"離隔:{numeric:.2f}m"
            return f"離隔:{numeric:.1f}px"
        return None

    def _format_lane_label(side: str, value) -> Optional[str]:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(numeric):
            return None
        return f"{side}:{abs(numeric):.1f}px"

    created = 0
    for index, request in enumerate(snapshot_requests, start=1):
        frame_num = int(request.get("frame", 0))
        target_index = max(frame_num, 0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_index)

        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"[assign_overtake] フレーム {frame_num} の読み込みに失敗しました。")
            continue

        # annotated = frame.copy() # No annotation needed
        # Just save the raw frame

        filename = (
            f"overtake_{frame_num:06d}_car{request.get('car_group')}_"
            f"bike{request.get('bike_group')}_{index:02d}.png"
        )
        output_path = snapshot_dir / filename
        try:
            cv2.imwrite(str(output_path), frame) # Save raw frame
            created += 1
            
            # 離隔距離をターミナルに出力
            label = _format_clearance_label(request) or "距離不明"
            print(f"[Overtake Snapshot] Saved (Raw): {output_path.name} | {label}")
        except Exception as exc:  # noqa: BLE001
            print(f"[assign_overtake] スナップショットの保存に失敗しました ({output_path}): {exc}")

    cap.release()

    if created:
        print(f"✅ [assign_overtake] 追い越しスナップショット {created} 枚を以下に保存しました:\n   📂 {snapshot_dir}")
    else:
        print(f"[assign_overtake] スナップショットリクエスト {len(snapshot_requests)} 件に対し、生成された画像は 0 件でした。")

    return created


from .measure_points import attach_measure_points, compute_front_right_tire_points

def assign_overtake(run_id: int) -> int:
    """
    自転車と自動車のペアが追い越しを行った瞬間のみ自転車側にフラグを付与し、
    `overtake_by` に追い越した車両グループID、`overtake_by_second` に自転車自身のグループIDを保存する。
    戻り値: 生成されたスナップショット枚数
    """
    car_aliases = _resolve_aliases("OVERTAKE_CAR_CLASSES", "car,truck,bus")
    bicycle_aliases = _resolve_aliases("OVERTAKE_BICYCLE_CLASSES", "bicycle")

    if not car_aliases or not bicycle_aliases:
        print("[assign_overtake] 追い越し対象クラスが設定されていないためスキップします。")
        return 0, []

    video_filename: Optional[str] = None
    source_path: Optional[str] = None
    output_folder: Optional[str] = None
    folder_alias: Optional[str] = None
    calibration_profile: Optional[str] = None

    calibration_data: Optional[dict] = None

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        ensure_detection_distance_columns()
        ensure_overtake_event_columns(conn)
        conn.execute(
            """
            UPDATE Detection
            SET overtake = 0,
                overtake_after = 0,
                overtake_window_offset = NULL,
                overtake_by = NULL,
                overtake_by_second = NULL
            WHERE run_id = ?
            """,
            (run_id,),
        )

        meta_sql = (
            "SELECT v.fps, v.filename, v.source_path, p.output_folder, p.folder_alias, p.calibration_profile "
            "FROM Video v JOIN ProcessLog p ON v.video_id = p.video_id WHERE p.run_id = ?"
        )
        meta_row = conn.execute(meta_sql, (run_id,)).fetchone()
        if meta_row:
            (
                fps,
                video_filename,
                source_path,
                output_folder,
                folder_alias,
                calibration_profile,
            ) = meta_row
            fps = fps or 30.0
        else:
            fps = 30.0

        try:
            calibration_data, _ = load_calibration_json(run_id, calibration_profile)
        except FileNotFoundError:
            calibration_data = None
        except Exception as exc:  # noqa: BLE001
            calibration_data = None
            print(f"[assign_overtake] キャリブレーション読込に失敗したためホモグラフィを利用できません: {exc}")
        
        from .manual_metrics import load_white_lines
        lane_lines = load_white_lines(calibration_data)
        left_line, right_line, center_line = lane_lines

        # Load Vehicles (Cars/Bikes)
        df = pd.read_sql_query(
            """
            SELECT d.auto_id, d.frame_num, d.group_id, d.model_name,
                   d.x1, d.y1, d.x2, d.y2,
                   d.speed_km_h, 
                   d.travel_direction,
                   d.class_id,
                   c.class_name,
                   d.l_line_cross_m, d.r_line_cross_m
            FROM Detection AS d
            JOIN Class AS c ON d.class_id = c.class_id
            WHERE d.run_id = ?
              AND d.group_id IS NOT NULL
              AND d.model_name != 'best' -- Exclude tires from main vehicle list
            ORDER BY d.group_id, d.frame_num
            """,
            conn,
            params=(run_id,),
        )
        
        # Load Tires separately
        df_tires = pd.read_sql_query(
            """
            SELECT d.auto_id, d.frame_num, d.group_id, d.x1, d.y1, d.x2, d.y2,
                   d.travel_direction, d.class_id, c.class_name
            FROM Detection AS d
            JOIN Class AS c ON d.class_id = c.class_id
            WHERE d.run_id = ? 
              AND d.model_name = 'best'
            """,
            conn,
            params=(run_id,),
        )

    if df.empty or len(df['group_id'].unique()) < 2:
        print("追い越し相手判定スキップ: 比較対象の車両が2台未満です。")
        return 0, []
        
    # Recalculate measure points using correct logic
    tyre_points = compute_front_right_tire_points(
        df_tires,
        left_line,
        right_line,
    )
    
    # Attach points (handling bicycles with center logic due to recent updates in measure_points.py)
    df = attach_measure_points(
        df,
        tyre_points,
        left_line=left_line,
        right_line=right_line,
    )

    df['class_name'] = df['class_name'].str.lower()
    valid_classes = car_aliases.union(bicycle_aliases)

    # フィルタリング前の状況を確認するために保存
    found_stats = df.groupby(['class_name', 'class_id']).size().reset_index(name='count')
    found_stats = found_stats.sort_values('count', ascending=False)
    
    df_filtered = df[df['class_name'].isin(valid_classes)].copy()

    if df_filtered.empty:
        print(f"[assign_overtake] 指定クラス {sorted(list(valid_classes))} の検出が存在しないためスキップします。")
        if not found_stats.empty:
            print("  [検出されたクラスごとの件数 (Top 10)]")
            for _, row in found_stats.head(10).iterrows():
                print(f"    - {row['class_name']} (ID {row['class_id']}): {row['count']}件")
        else:
            print("  (検出自体が0件です)")
        return 0, []
    
    df_filtered['center_y'] = (df_filtered['y1'] + df_filtered['y2']) / 2
    df_filtered['center_x'] = (df_filtered['x1'] + df_filtered['x2']) / 2

    # Overtake Judgment Base: use Y2 (Bottom)
    # ユーザー要望: 追い越し判定は「グループIDの底辺のY座標」で行う
    df_filtered['relative_y'] = df_filtered['y2']

    df_filtered['direction_norm'] = (
        df_filtered['travel_direction']
        .fillna('')
        .astype(str)
        .str.strip()
        .str.upper()
    )
    df_filtered.loc[~df_filtered['direction_norm'].isin({'F', 'B'}), 'direction_norm'] = ''
    
    # Use the filtered dataframe
    df = df_filtered

    unique_group_ids = df['group_id'].unique()
    group_class_map = (
        df.groupby('group_id')['class_name']
        .agg(_select_representative_class)
        .to_dict()
    )
    group_direction_map = (
        df.groupby('group_id')['direction_norm']
        .agg(_select_representative_class)
        .to_dict()
    )

    skip_logs = []
    bike_groups = [
        int(gid)
        for gid, cls in group_class_map.items()
        if cls in bicycle_aliases
    ]
    for bike_gid in bike_groups:
        bike_rows = df[df["group_id"] == bike_gid]
        if bike_rows.empty:
            continue
        frame_min = int(bike_rows["frame_num"].min())
        frame_max = int(bike_rows["frame_num"].max())
        direction = group_direction_map.get(bike_gid, "")
        skip_logs.append({
            "run_id": run_id,
            "car_group": "",
            "bike_group": bike_gid,
            "reason": _to_skip_reason_jp("Bike Detected"),
            "detail": f"フレーム:{frame_min}-{frame_max}, 方向:{direction or '-'}",
        })

    overtaker_event_updates: List[Tuple[int, int, int]] = []
    overtaken_event_updates: List[Tuple[int, int, int]] = []
    bike_after_auto_ids: set[int] = set()
    events_for_overtake_table: list[tuple] = []
    complex_events: list[dict] = [] # (event_tuple, stats_dict)
    overtake_offset_updates: dict[int, int] = {}
    max_frame_num = int(df['frame_num'].max())
    window_radius = 30
    snapshot_requests: List[dict] = []
    


    def _record_offset(auto_id: Optional[int], offset: int) -> None:
        if auto_id is None:
            return
        current = overtake_offset_updates.get(auto_id)
        if current is None or abs(offset) < abs(current):
            overtake_offset_updates[auto_id] = offset

    def _capture_offsets(
        traj: pd.DataFrame,
        event_frame: int,
        *,
        after_auto_ids: Optional[set[int]] = None,
    ) -> None:
        if traj.empty:
            return
        start_frame = event_frame - window_radius
        end_frame = event_frame + window_radius
        window_df = traj[(traj.index >= start_frame) & (traj.index <= end_frame)]
        if window_df.empty:
            return
        for frame_idx, row in window_df.iterrows():
            auto_val = row.get('auto_id')
            if pd.isna(auto_val):
                continue
            try:
                auto_id_val = int(auto_val)
            except (TypeError, ValueError):
                continue
            try:
                frame_index = int(frame_idx)
            except (TypeError, ValueError):
                frame_index = event_frame
            offset_val = frame_index - event_frame
            if -window_radius <= offset_val <= window_radius:
                _record_offset(auto_id_val, offset_val)
                if after_auto_ids is not None and offset_val > 0:
                    after_auto_ids.add(auto_id_val)

    
    # ユーザー指摘対応: 離隔距離計算にナンバープレートが使われるのを防ぐためフィルタリング
    if 'class_name' in df.columns:
        df = df[~df['class_name'].str.contains('plate', case=False, na=False)]

    for i in tqdm(range(len(unique_group_ids)), desc="追い越し相手判定中"):
        for j in range(i + 1, len(unique_group_ids)):
            id_a, id_b = unique_group_ids[i], unique_group_ids[j]
            traj_a = df[df['group_id'] == id_a].drop_duplicates(subset=['frame_num']).set_index('frame_num')
            traj_b = df[df['group_id'] == id_b].drop_duplicates(subset=['frame_num']).set_index('frame_num')

            common_frames = traj_a.index.intersection(traj_b.index)
            if len(common_frames) < 1:
                # No overlap
                continue
            
            class_a = group_class_map.get(id_a)
            class_b = group_class_map.get(id_b)

            # Determine Overtaker/Overtaken
            if class_a in car_aliases and class_b in bicycle_aliases:
                car_key, bike_key = 'A', 'B'
                car_group_id, bike_group_id = id_a, id_b
                car_traj, bike_traj = traj_a, traj_b
            elif class_b in car_aliases and class_a in bicycle_aliases:
                car_key, bike_key = 'B', 'A'
                car_group_id, bike_group_id = id_b, id_a
                car_traj, bike_traj = traj_b, traj_a
            else:
                # Not a Car-Bike Pair
                continue

            dir_a = group_direction_map.get(id_a, '')
            dir_b = group_direction_map.get(id_b, '')
            
            # Strict Direction Check: Ensure both are valid and IDENTICAL
            if not dir_a or not dir_b or dir_a != dir_b:
                skip_logs.append({
                    "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                    "reason": _to_skip_reason_jp("Direction Mismatch or Invalid"),
                    "detail": f"車:{dir_a or '-'}, 自転車:{dir_b or '-'}"
                })
                continue
            
            # Additional Sanity Check: If vectors are truly opposite, even if labeled same?
            # (Skipped for now, assuming kinematics direction is generally correct if stripped)
            
            direction = dir_a # Representative direction

            merged_traj = pd.concat(
                [traj_a.loc[common_frames], traj_b.loc[common_frames]],
                axis=1,
                keys=['A', 'B'],
            )

            # 1. Global Behind Check (WITHOUT adjacency filter)
            # This ensures we don't drop "Behind" evidence just because they were far apart (e.g. approaching)
            
            y_diff_global = merged_traj[(car_key, 'relative_y')] - merged_traj[(bike_key, 'relative_y')]
            Y_MARGIN = 10.0
            
            has_behind_state = False
            first_behind_frame = None
            
            # New Direction Logic:
            # F (Bottom-to-Top / Upward): Start=Bottom(Large Y), End=Top(Small Y).
            #   Behind means closer to start => Larger Y. 
            #   Behind: Car > Bike => Diff > 0 (Positive).
            # B (Top-to-Bottom / Downward): Start=Top(Small Y), End=Bottom(Large Y).
            #   Behind means closer to start => Smaller Y.
            #   Behind: Car < Bike => Diff < 0 (Negative).

            if direction == 'F':
                # F: Behind = Car > Bike (Pos)
                frames_behind_global = y_diff_global[y_diff_global > Y_MARGIN].index
                has_behind_state = len(frames_behind_global) > 0
                if has_behind_state: first_behind_frame = frames_behind_global.min()
            elif direction == 'B':
                # B: Behind = Car < Bike (Neg)
                frames_behind_global = y_diff_global[y_diff_global < -Y_MARGIN].index
                has_behind_state = len(frames_behind_global) > 0
                if has_behind_state: first_behind_frame = frames_behind_global.min()

            # 2. Adjacency Check (Lateral) for Interaction Validtion
            # We still need them to be adjacent *at some point* to be considered an overtake on the same road section
            # But "Behind" state could be non-adjacent.
            
            car_width_series = merged_traj[(car_key, 'x2')] - merged_traj[(car_key, 'x1')]
            bike_width_series = merged_traj[(bike_key, 'x2')] - merged_traj[(bike_key, 'x1')]
            width_candidates = [val for val in [car_width_series.mean(), bike_width_series.mean()] if pd.notna(val)]
            
            lateral_distance_threshold = 200 # Default fallback
            if width_candidates:
                lateral_distance_threshold = max(width_candidates) * 2.0
            
            car_center_x = merged_traj[(car_key, 'center_x')]
            bike_center_x = merged_traj[(bike_key, 'center_x')]
            
            # Use raw adjacency for check
            is_adjacent_frames = (car_center_x - bike_center_x).abs() < lateral_distance_threshold
            
            # If they are NEVER adjacent, skip
            if not is_adjacent_frames.any():
                skip_logs.append({
                    "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                    "reason": _to_skip_reason_jp("Never Adjacent"),
                    "detail": f"後方状態検出: {'あり' if has_behind_state else 'なし'}"
                })
                continue

            # 3. Overtake Detection
            # We look for "Behind" (Global) -> "Ahead" (Global)
            # BUT, we might want to ensure "Ahead" is close enough? or just any Ahead?
            # User requirement: "If 'Behind' exists, output reason if skip".
            
            overtake_frames = []
            reason_for_skip = "Unknown"
            
            if not has_behind_state:
                skip_logs.append({
                    "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                    "reason": _to_skip_reason_jp("No Behind State Detected"),
                    "detail": "車が自転車の後方になったフレームがありません"
                })
                continue
                
            # Check Ahead State
            if direction == 'F':
                # Ahead = Car < Bike (Neg)
                frames_ahead = y_diff_global[y_diff_global < -Y_MARGIN].index
            elif direction == 'B':
                # Ahead = Car > Bike (Pos)
                frames_ahead = y_diff_global[y_diff_global > Y_MARGIN].index
            
            if len(frames_ahead) == 0:
                skip_logs.append({
                    "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                    "reason": _to_skip_reason_jp("No Ahead State Detected"),
                    "detail": "車が自転車の前方になったフレームがありません"
                })
                continue
                
            first_ahead = frames_ahead.min()
            
            # Verify Temporal Order: Was there a Behind frame BEFORE the First Ahead frame?
            if direction == 'F':
                 # Behind was Pos
                 candidates_behind = y_diff_global[(y_diff_global > Y_MARGIN) & (y_diff_global.index < first_ahead)]
            else:
                 # Behind was Neg
                 candidates_behind = y_diff_global[(y_diff_global < -Y_MARGIN) & (y_diff_global.index < first_ahead)]
            
            if candidates_behind.empty:
                skip_logs.append({
                    "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                    "reason": _to_skip_reason_jp("Order Invalid"),
                    "detail": f"前方フレーム {first_ahead} より前に後方状態がありません"
                })
                continue

            last_behind = candidates_behind.index.max()
            
            # Search for the *best* Crossing Frame (where Y diff is closest to 0)
            # Find closest zero-crossing between last_behind and first_ahead
            search_window = y_diff_global.loc[last_behind : first_ahead] 
            
            if search_window.empty:
                event_frame = first_ahead
                min_diff = abs(y_diff_global.loc[first_ahead])
            else:
                best_idx = search_window.abs().idxmin()
                event_frame = best_idx
                min_diff = abs(search_window.loc[best_idx])
            
            # ユーザー要望: "y軸 +-20pxを超えてしまった場所で...判定" (Avoid large gaps)
            CROSSING_THRESHOLD = 20.0
            
            if min_diff > CROSSING_THRESHOLD:
                skip_logs.append({
                    "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                    "reason": _to_skip_reason_jp("Crossing Gap Too Large"),
                    "detail": (
                        f"最適フレーム {event_frame} の差分 {min_diff:.1f}px "
                        f"(上限 {CROSSING_THRESHOLD:.1f}px)"
                    )
                })
                continue
            
            overtake_frames = [event_frame]


            if len(overtake_frames) == 0:
                # --- Ray-Cast Fallback Logic ---
                # 既存ロジックで追い越しが見つからなかった場合、レイキャスト（横線）判定を試行
                # 条件: 
                # 1. すでにこのペアの追い越しイベントが存在する場合はスキップ（既存優先）
                # 2. 自転車の底辺(y2)から横線を引き、車のBBOX(y1~y2)に含まれているフレームを探す
                # 3. その時点での離隔距離(approach_distance_px)が 30px 未満であること

                # Check for existing event priority
                already_exists = False
                for evt in events_for_overtake_table:
                    # evt format check: (run_id, frame, car_gid, bike_gid, ...)
                    if evt[2] == int(car_group_id) and evt[3] == int(bike_group_id):
                        already_exists = True
                        break
                
                if not already_exists:
                    # Target Y = Bike's y2 (relative_y)
                    # Car Range = Car's y1 ~ y2
                    # We need access to y1, so we look at merged_traj
                    
                    # merged_traj has (Car, x1/y1/x2/y2/relative_y...) and (Bike, ...)
                    # relative_y was set to y2
                    
                    # Ensure we have y1/y2 available in merged_traj
                    # merged_traj was created from traj_a and traj_b which are from df_filtered
                    # df_filtered has x1,y1,x2,y2. 
                    
                    car_y1 = merged_traj[(car_key, 'y1')]
                    car_y2 = merged_traj[(car_key, 'y2')]
                    bike_y2 = merged_traj[(bike_key, 'relative_y')] # = y2
                    
                    # Intersect Condition
                    # Bike Y2 is between Car Y1 and Car Y2
                    is_intersect_y = (bike_y2 >= car_y1) & (bike_y2 <= car_y2)
                    
                    # Lateral Distance Condition
                    # We can use the previously calculated 'is_adjacent_frames' logic but with stricter threshold
                    # OR we calculate specific distance.
                    # User said "butsukatta toki no approach distance ga 30px ijou dato... (if >= 30, no good)"
                    # So we want distance < 30.
                    
                    # Calculate center distance
                    c_x_Diff = (merged_traj[(car_key, 'center_x')] - merged_traj[(bike_key, 'center_x')]).abs()
                    # Approx lateral distance (edge to edge)
                    # dist = center_diff - (w1 + w2)/2
                    c_w = merged_traj[(car_key, 'x2')] - merged_traj[(car_key, 'x1')]
                    b_w = merged_traj[(bike_key, 'x2')] - merged_traj[(bike_key, 'x1')]
                    lat_dist = c_x_Diff - (c_w + b_w) / 2.0
                    
                    # Valid Frames
                    valid_ray_frames = idx = merged_traj.index[
                        is_intersect_y & (lat_dist < 30.0)
                    ]
                    
                    if not valid_ray_frames.empty:
                        # Find the frame with minimum lateral distance (closest contact)
                        # or just the first one? usually first or min dist.
                        # Let's use min lateral distance frame
                        
                        best_ray_frame_idx = lat_dist.loc[valid_ray_frames].idxmin()
                        overtake_frames = [best_ray_frame_idx]
                        
                        # Log it
                        print(f"[Ray-Cast] Detected Overtake! Frame={best_ray_frame_idx}, CarG={car_group_id}, BikeG={bike_group_id}, Dist={lat_dist.loc[best_ray_frame_idx]:.1f}px")
                    else:
                        # Log reason if intersections found but distance too large?
                        intersections = merged_traj.index[is_intersect_y]
                        if not intersections.empty:
                            min_dist = lat_dist.loc[intersections].min()
                            skip_logs.append({
                                "run_id": run_id, "car_group": car_group_id, "bike_group": bike_group_id,
                                "reason": _to_skip_reason_jp("Ray-Cast: Dist Too Large"),
                                "detail": f"最小距離 {min_dist:.1f}px (上限 30px)"
                            })

            if len(overtake_frames) == 0:
                continue
            
            # Process Valid Overtake (Take First Frame)
            car_traj_final = car_traj
            bike_traj_final = bike_traj

            
            for frame in overtake_frames:
                car_row = car_traj.loc[frame]
                bike_row = bike_traj.loc[frame]

                if isinstance(car_row, pd.DataFrame):
                    car_row = car_row.iloc[0]
                if isinstance(bike_row, pd.DataFrame):
                    bike_row = bike_row.iloc[0]

                event_frame = int(frame)
                car_auto_id = int(car_row['auto_id'])
                bike_auto_id = int(bike_row['auto_id'])

                # ユーザー要望: 追い越し判定は「車」に付与する (車が自転車を追い越した)
                # ターゲット: Car (car_auto_id)
                # Overtake By: Bike (bike_group_id)
                overtaker_event_updates.append(
                    (
                        int(car_group_id),
                        int(bike_group_id),
                        car_auto_id,
                    )
                )
                overtaken_event_updates.append(
                    (
                        int(car_group_id),
                        int(bike_group_id),
                        bike_auto_id,
                    )
                )
                _record_offset(bike_auto_id, 0)
                _capture_offsets(bike_traj, event_frame, after_auto_ids=bike_after_auto_ids)

                seconds = 5
                frame_window = int(seconds * fps)
                start_frame = max(0, event_frame - frame_window)
                end_frame = min(max_frame_num, event_frame + frame_window)

                speed_profile_df = car_traj[(car_traj.index >= start_frame) & (car_traj.index <= end_frame)]
                speed_profile_dict = {
                    f"{((idx - event_frame) / fps):.1f}s": (f"{row.speed_km_h:.1f}" if pd.notna(row.speed_km_h) else None)
                    for idx, row in speed_profile_df.iterrows()
                }

                speed_profile_json = json.dumps(speed_profile_dict)

                # ユーザー要望: 離隔距離は「接近距離」を使用する
                # そのため、OvertakeEventsテーブルの clearance カラムにも approach の値をセットする
                approach_px = _safe_float(bike_row.get("approach_distance_px"))
                approach_m = _safe_float(bike_row.get("approach_distance_m"))
                
                # cm換算
                approach_cm = None
                if approach_m is not None:
                     approach_cm = approach_m * 100.0

                events_for_overtake_table.append(
                    (
                        run_id,
                        event_frame,
                        int(car_group_id),
                        int(bike_group_id),
                        car_auto_id,
                        bike_auto_id,
                        approach_px,          # approach_distance_px
                        approach_m,           # approach_distance_m
                        approach_px,          # clearance_distance_px <- Use Approach
                        approach_m,           # clearance_distance_m  <- Use Approach
                        approach_cm,          # clearance_distance_cm <- Use Approach
                        _safe_float(bike_row.get("l_line_distance")),
                        _safe_float(bike_row.get("l_line_distance_m")),
                        _safe_float(bike_row.get("l_line_distance_cm")),
                        _safe_float(bike_row.get("r_line_distance")),
                        _safe_float(bike_row.get("r_line_distance_m")),
                        _safe_float(bike_row.get("r_line_distance_cm")),
                        _safe_float(bike_row.get("line_distance")),
                        _safe_float(bike_row.get("line_distance_m")),
                        _safe_float(bike_row.get("line_distance_cm")),
                        speed_profile_json,
                        _safe_float(car_row.get("l_line_cross_m")),
                        _safe_float(car_row.get("r_line_cross_m")),
                        _safe_float(bike_row.get("l_line_cross_m")),
                        _safe_float(bike_row.get("r_line_cross_m")),
                    )
                    )

                # --- Statistics Calculation ---
                # Determine "Crossing" duration and area
                # Direction F: Right is Center. B: Left is Center.
                target_cross_col = 'r_line_cross_m' if direction == 'F' else 'l_line_cross_m'
                
                # Filter frames where car is crossing
                # Using 0.0 margin
                crossing_df = car_traj[car_traj[target_cross_col] > 0]
                
                duration_s = 0.0
                area_m2 = 0.0
                is_out_of_bounds = 0
                traj_image_path = None
                
                start_cross_frame = -1
                end_cross_frame = -1

                if not crossing_df.empty:
                    start_cross_frame = crossing_df.index.min()
                    end_cross_frame = crossing_df.index.max()
                    
                    frame_count = len(crossing_df)
                    duration_s = frame_count / fps
                    
                    # Area: Sum (CrossDist * (Speed * TimePerFrame))
                    # Speed is km/h -> m/s
                    # TimePerFrame = 1/fps
                    # DistDelta = (Speed / 3.6) * (1/fps)
                    for _, c_row in crossing_df.iterrows():
                        cross_m = c_row.get(target_cross_col, 0)
                        speed_k = c_row.get('speed_km_h', 0) or 0
                        if pd.isna(speed_k): speed_k = 0
                        if speed_k < 0: speed_k = 0 # Avoid negative speed
                        dist_delta = (speed_k / 3.6) * (1.0 / fps)
                        if dist_delta < 0: dist_delta = 0 # Avoid negative area
                        area_m2 += cross_m * dist_delta
                        
                    # Out of bounds check
                    # If start_cross_frame is the FIRST frame of car_traj -> Started before tracking
                    # If end_cross_frame is the LAST frame of car_traj -> Ended after tracking
                    traj_start = car_traj.index.min()
                    traj_end = car_traj.index.max()
                    
                    if start_cross_frame <= traj_start or end_cross_frame >= traj_end:
                        is_out_of_bounds = 1
                
                # Generate Image
                # Reuse video capture if possible, or Open new
                # We need one frame (event_frame)
                # Note: 'cap' is not open here! We are in a loop without cap. 
                # assign_overtake opens cap locally for snapshots but that is later.
                # We should open cap momentarily or defer image generation?
                # Deferring is better. Store requests.
                
                stats_payload = {
                    "duration_s": duration_s,
                    "is_out_of_bounds": is_out_of_bounds,
                    "area_m2": area_m2,
                    # For image gen later
                    "car_traj": car_traj,
                    "bike_traj": bike_traj,
                    "start_cross_frame": start_cross_frame,
                    "end_cross_frame": end_cross_frame,
                    "target_cross_col": target_cross_col,
                    "car_gid": int(car_group_id),
                    "bike_gid": int(bike_group_id),
                    "event_frame": event_frame
                }

                complex_events.append({
                    "tuple": events_for_overtake_table[-1],
                    "stats": stats_payload
                })

    created_count = _export_overtake_snapshots(
        run_id,
        snapshot_requests,
        output_folder=output_folder,
        video_filename=video_filename,
        source_path=source_path,
        folder_alias=folder_alias,
        calibration_profile=calibration_profile,
        calibration_data=calibration_data,
    )
    return created_count, skip_logs


def summarize_run_overtakes(run_id: int) -> dict:
    """Runの追い越しイベント統計とスナップショット一覧を取得する。"""
    import glob
    
    summary = {
        "total": 0,
        "inner": 0,
        "outer": 0,
        "images": [],
    }
    
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        
        # Count Total
        cursor = conn.execute("SELECT COUNT(*) FROM OvertakeEvents WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            summary["total"] = row[0]
            
        if summary["total"] > 0:
            # Count Inner/Outer (using Detection's lane_position_flag for the bicycle)
            query = """
                SELECT d.lane_position_flag
                FROM OvertakeEvents o
                JOIN Detection d ON o.run_id = d.run_id AND o.overtaken_auto_id = d.auto_id
                WHERE o.run_id = ?
            """
            cursor = conn.execute(query, (run_id,))
            for (flag,) in cursor:
                if flag == '+':
                    summary["inner"] += 1
                elif flag == '-':
                    summary["outer"] += 1
            
            # Avg Overtake Speed (Speed of Overtaker)
            query_speed = """
                SELECT AVG(d.speed_km_h)
                FROM OvertakeEvents o
                JOIN Detection d ON o.run_id = d.run_id AND o.overtaker_auto_id = d.auto_id AND o.event_frame_num = d.frame_num
                WHERE o.run_id = ? AND d.speed_km_h > 0
            """
            cursor = conn.execute(query_speed, (run_id,))
            s_row = cursor.fetchone()
            if s_row and s_row[0] is not None:
                 summary["avg_overtake_speed"] = round(s_row[0], 2)

        # Avg Speed (All detections in Run)
        cursor = conn.execute("SELECT AVG(speed_km_h) FROM Detection WHERE run_id = ? AND speed_km_h > 0", (run_id,))
        row = cursor.fetchone()
        if row and row[0] is not None:
            summary["avg_speed"] = round(row[0], 2)

        # Get Images
        cursor = conn.execute("SELECT output_folder FROM ProcessLog WHERE run_id = ?", (run_id,))
        out_row = cursor.fetchone()
        if out_row and out_row[0]:
            out_folder = out_row[0]
            snapshot_dir = os.path.join(out_folder, "overtake_snapshots")
            if os.path.exists(snapshot_dir):
                # Search for png
                files = glob.glob(os.path.join(snapshot_dir, "*.png"))
                
                # Convert to relative path from OPT_FILES_PATH (output root)
                opt_root = os.getenv("Opt_files", "output").strip('"')
                abs_opt = os.path.abspath(opt_root)
                
                for f in files:
                    abs_f = os.path.abspath(f)
                    if abs_f.startswith(abs_opt):
                        # Make it relative to 'output' so it can be served via /results/
                        rel = os.path.relpath(abs_f, abs_opt).replace(os.path.sep, '/')
                        summary["images"].append(rel)

    summary["images"].sort()
    return summary
