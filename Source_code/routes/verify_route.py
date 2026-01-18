from flask import Blueprint, request, jsonify, send_from_directory, current_app, render_template
import os
import json
import cv2
import urllib.parse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg') # Backend for saving files without UI

# ADC_08 specific imports
from ..modules.db_manager import get_db_connection, get_run_video_info
from ..modules.white_line import get_line_x_at_y, calculate_metric_x_from_lines

# Blueprint definition
verify_bp = Blueprint('verify', __name__)

@verify_bp.route('/verify', methods=['GET'])
def page():
    from ..modules.db_manager import get_all_process_logs
    logs = get_all_process_logs()
    
    # Sort logs by Run ID desc for convenience
    logs = sorted(logs, key=lambda x: x['run_id'], reverse=True)
    
    return render_template('verify_calibration.html', logs=logs)

def get_calibration_json_path(profile_name):
    if not profile_name:
        return None
    # Use env or default like export_routes.py
    opt_files = os.getenv("Opt_files", "./output")
    opt_files = opt_files.strip('"').strip("'")
    calib_dir = os.path.join(opt_files, 'calibrations')
    path = os.path.join(calib_dir, f"{profile_name}.json")
    if os.path.exists(path):
        return path
    return None

@verify_bp.route('/api/verify_calibration', methods=['POST'])
def verify_calibration():
    try:
        data = request.json or {}
        run_id = data.get('run_id')
        
        if not run_id:
            return jsonify({"error": "Run ID is required"}), 400
            
        print(f"Starting verification for Run ID: {run_id} (ADC_08)")
            
        # 1. Get Video Information
        video_info = get_run_video_info(run_id)
        if not video_info:
             return jsonify({"error": f"Run ID {run_id} not found"}), 404
             
        video_path = video_info.get_path() if hasattr(video_info, 'get_path') else video_info.get('path')
        if not video_path or not os.path.exists(video_path):
            return jsonify({"error": f"Video file not found. Path: {video_path}"}), 404
            
        # 2. Get Calibration Profile
        # Query ProcessLog for calibration_profile
        calibration_profile = None
        output_folder = None # For saving result if needed, but we use verification folder
        
        with get_db_connection() as conn:
            conn.row_factory = None # precise control
            c = conn.cursor()
            row = c.execute("SELECT calibration_profile, output_folder FROM ProcessLog WHERE run_id = ?", (run_id,)).fetchone()
            if row:
                calibration_profile = row[0]
                output_folder = row[1] # Keep for reference
        
        if not calibration_profile:
             return jsonify({"error": "No calibration profile assigned to this Run"}), 400
             
        calib_path = get_calibration_json_path(calibration_profile)
        if not calib_path:
             return jsonify({"error": f"Calibration file not found for profile: {calibration_profile}"}), 404
            
        # 3. Load Calibration Data
        try:
            with open(calib_path, 'r', encoding='utf-8') as f:
                calib_data = json.load(f)
        except Exception as e:
            return jsonify({"error": f"Failed to load calibration JSON: {e}"}), 500
            
        # Support nested structure like {"lines": {"left_white_line": ...}}
        lines_data = calib_data.get('lines', calib_data)
            
        left_line = lines_data.get('left_white_line')
        center_line = lines_data.get('center_line')
        right_line = lines_data.get('right_white_line')
        
        if not center_line:
             # Fallback or error? For now error but with clear message
             # If strictly left/right exist, we could calc center, but let's stick to error for now unless user asks
             return jsonify({"error": "Calibration data missing 'center_line' (checked top-level and 'lines' key)"}), 400
             
        # 4. Extract Frame (120 or 0)
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
             return jsonify({"error": "Failed to open video"}), 500
             
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target_frame_idx = 120
        if total_frames <= 120:
            target_frame_idx = 0
            
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return jsonify({"error": f"Failed to read frame {target_frame_idx}"}), 500
            
        # 5. Draw Lines & Grid
        img_h, img_w = frame.shape[:2]
        draw_img = frame.copy()
        
        # colors (BGR)
        color_left = (255, 0, 0) # Blue
        color_center = (0, 0, 255) # Red
        color_right = (0, 255, 0) # Green
        color_grid = (0, 255, 255) # Yellow
        
        def draw_poly(points, color, thickness=2):
            if points and len(points) > 1:
                pts = np.array(points, np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(draw_img, [pts], False, color, thickness)
                
        draw_poly(left_line, color_left, 2)
        draw_poly(center_line, color_center, 2)
        draw_poly(right_line, color_right, 2)
        
        # Grid Drawing
        y_step = 40
        y_values = []
        width_left_vals = []
        width_right_vals = []
        scales = [] # Store scale (m/px)
        m_192_vals = [] # Store m per 192px
        lane_width_m = 3.5 

        # Determine Y Range:
        # Start: Top of Left Line (Min Y)
        # End: Diagonal line connecting Bottom of Left and Bottom of Right
        
        y_start = 0
        img_h = frame.shape[0]
        
        # Find start Y (Left Top)
        if left_line:
            y_start = min(p[1] for p in left_line)
        y_start = max(0, y_start)
        
        # Find connection line for bottom limit
        # Get point with max Y for left and right
        p_l_bottom = max(left_line, key=lambda p: p[1]) if left_line else None
        p_r_bottom = max(right_line, key=lambda p: p[1]) if right_line else None
        
        # Calculate cutoff line parameters (y = mx + b)
        cutoff_slope = None
        cutoff_intercept = None
        
        if p_l_bottom and p_r_bottom:
             x1, y1 = p_l_bottom
             x2, y2 = p_r_bottom
             
             if x2 != x1:
                 cutoff_slope = (y2 - y1) / (x2 - x1)
                 cutoff_intercept = y1 - cutoff_slope * x1
                 
                 # Draw the cutoff line for visuals (optional, but requested to "connect with points")
                 # Let's draw it in red or something distinctive
                 cv2.line(draw_img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
        
        # Loop until bottom of image, but we will break early
        y_idx = 0 # Counter for vertical interval control
        for y in range(y_start, img_h, y_step):
            cx = get_line_x_at_y(y, center_line)
            if cx is None: continue

            # Check Cutoff
            if cutoff_slope is not None:
                limit_y = cutoff_slope * cx + cutoff_intercept
                # If current y is 'below' (greater than) the limit line
                # Note: y increases downwards.
                # If y > limit_y, we are below the line.
                if y > limit_y:
                    break

            lx = get_line_x_at_y(y, left_line)
            rx = get_line_x_at_y(y, right_line) if right_line else None
            
            scale_left = None
            scale_right = None
            
            if lx is not None:
                w_l = abs(cx - lx)
                if w_l > 1: scale_left = lane_width_m / w_l
                
            if rx is not None:
                w_r = abs(rx - cx)
                if w_r > 1: scale_right = lane_width_m / w_r
            
            if scale_right is None and scale_left: scale_right = scale_left
            if scale_left is None and scale_right: scale_left = scale_right
            
            if scale_left is None: continue 
            
            y_values.append(y)
            width_left_vals.append(abs(cx - lx) if lx else 0)
            width_right_vals.append(abs(rx - cx) if rx else 0)
            scales.append(scale_left)
            m_192_vals.append(scale_left * 192)

            # Draw grid points: 6 points on each side from center (1m interval)
            # Range: -6m to +6m (covers 3.5m + 2m request)
            for m in range(-6, 7):
                target_scale = scale_left if m < 0 else scale_right
                if target_scale:
                    px_offset = m / target_scale
                    target_x = cx + px_offset
                    
                    if 0 <= target_x < img_w:
                        cv2.circle(draw_img, (int(target_x), y), 3, color_grid, -1)

            # Draw 3.5m points (Red) with double vertical interval
            # User request: "これだけ点の間隔を2倍に" -> "Double the vertical interval for these points only"
            if y_idx % 2 == 0:
                color_35m = (0, 0, 255) # Red
                for m in [-3.5, 3.5]:
                     target_scale = scale_left if m < 0 else scale_right
                     if target_scale:
                        px_offset = m / target_scale
                        target_x = cx + px_offset
                        
                        if 0 <= target_x < img_w:
                            cv2.circle(draw_img, (int(target_x), y), 4, color_35m, -1)

            y_idx += 1

        # 6. Save Outputs
        opt_folder = os.environ.get("Opt_files", "output")
        verify_dir = os.path.join(opt_folder, "verification", f"run_{run_id}")
        os.makedirs(verify_dir, exist_ok=True)
        
        frame_filename = "frame_120_grid.jpg"
        graph_filename = "lane_width_graph.png"
        scale_graph_filename = "scale_graph.png"
        
        frame_path_abs = os.path.abspath(os.path.join(verify_dir, frame_filename))
        graph_path_abs = os.path.abspath(os.path.join(verify_dir, graph_filename))
        scale_graph_path_abs = os.path.abspath(os.path.join(verify_dir, scale_graph_filename))
        
        cv2.imwrite(frame_path_abs, draw_img)
        
        # Original Graph (Width px vs Y)
        plt.figure(figsize=(10, 6))
        plt.plot(y_values, width_left_vals, label='Left Lane Width (px)', color='blue')
        if right_line:
             plt.plot(y_values, width_right_vals, label='Right Lane Width (px)', color='green')
             
        plt.title(f"Lane Width (px) vs Y-coordinate for Run {run_id}")
        plt.xlabel("Y Coordinate (px)")
        plt.ylabel("Lane Width (px)")
        plt.legend()
        plt.grid(True)
        plt.savefig(graph_path_abs)
        plt.close()
        
        # Scale Graph (Meters per 192px vs Y) - Renamed/Updated
        plt.figure(figsize=(10, 8)) # Taller for Y axis
        plt.plot(m_192_vals, y_values, label='1m Scale (192px)', color='purple', marker='o')
        plt.title(f"1m Scale (192px) vs Y-coordinate")
        plt.xlabel("1m Scale (192px)") # Horizontal m/192px
        plt.ylabel("Y Coordinate (px)") # Vertical px
        
        # User Request: Horizontal axis up to 11m
        plt.xlim(0, 11)
        
        # User Request: Vertical axis only where data exists (no whitespace)
        if y_values:
            # Add a small padding? Or strict? "Display only where data exists" implies strict or near-strict.
            # Y data is pixels. Small padding (e.g. +/- 10) likely looks better than cutting dots in half.
            y_min = min(y_values)
            y_max = max(y_values)
            plt.ylim(y_min - 5, y_max + 5)
            
        plt.grid(True)
        plt.savefig(scale_graph_path_abs)
        plt.close()
        
        return jsonify({
            "success": True,
            "frame_path": frame_path_abs,
            "graph_path": graph_path_abs,
            "scale_graph_path": scale_graph_path_abs,
            "verify_dir": verify_dir,
            "frame_url": f"/api/verify_image?path={urllib.parse.quote(frame_path_abs)}",
            "graph_url": f"/api/verify_image?path={urllib.parse.quote(graph_path_abs)}",
            "scale_graph_url": f"/api/verify_image?path={urllib.parse.quote(scale_graph_path_abs)}"
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@verify_bp.route('/api/verify_image', methods=['GET'])
def verify_image():
    path = request.args.get('path')
    if not path:
        return "Path required", 400
    
    if "output" not in path:
        return "Invalid path", 403
        
    directory = os.path.dirname(path)
    filename = os.path.basename(path)
    return send_from_directory(directory, filename)
