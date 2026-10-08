import cv2
import os
from typing import Optional, Dict, Any

def probe_video(video_path: str) -> Dict[str, Any]:
    """動画ファイルの基本情報を取得する。"""
    if not os.path.exists(video_path):
        return {}
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {}
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    cap.release()
    
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": frame_count,
        "duration_s": frame_count / fps if fps > 0 else 0
    }

def load_video_frame(video_path: str, frame_num: int) -> Optional["cv2.Mat"]:
    """指定フレームの画像を読み込む。"""
    if not os.path.exists(video_path):
        return None
        
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
        
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        return None
        
    return frame
