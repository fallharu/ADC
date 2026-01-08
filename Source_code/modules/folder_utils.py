import os
import re
from typing import List, Dict, Any, Tuple, Optional
from .file_utils import load_folder_settings
from .inference import collect_video_files

PATH_LINK_FILENAME = ".pathlink"

def resolve_registered_folder(upload_root: str, folder_name: str) -> Tuple[str, bool, bool, str]:
    """登録済みフォルダの実体パスと状態を返す。"""
    folder_dir = os.path.join(upload_root, folder_name)
    link_file = os.path.join(folder_dir, PATH_LINK_FILENAME)
    if os.path.isfile(link_file):
        raw_target = ""
        try:
            with open(link_file, "r", encoding="utf-8") as handle:
                raw_target = handle.read().strip()
        except OSError:
            raw_target = ""
        resolved = os.path.abspath(raw_target) if raw_target else raw_target
        exists = bool(resolved and os.path.isdir(resolved))
        return resolved or raw_target, True, exists, raw_target or resolved
    exists = os.path.isdir(folder_dir)
    return folder_dir, False, exists, folder_dir


def find_source_video_path(clip_folder_path: str, upload_root: str = "uploads", output_root: str = "output") -> Optional[str]:
    """クリップフォルダパスから元の動画ファイルパスを検索する。
    
    例: output/new_x/1_250802/VideoName_20251107_055412 -> uploads/new_x/1_250802/VideoName.mp4
    """
    if not clip_folder_path:
        return None

    norm_path = os.path.normpath(clip_folder_path)
    
    # 1. output root を uploads root に置換するための準備
    # パスが output_root で始まっているか確認し、始まっていれば置換
    # ただし、単純な文字列置換だと誤爆する可能性があるのでパスコンポーネントで処理推奨だが、
    # ここでは簡易的に絶対パス化または相対パスのプレフィックスを確認する。
    
    # まずパスをパーツに分解
    parts = norm_path.split(os.sep)
    
    # "output" (または output_root) というパスパーツを探して "uploads" に変える
    # 複数ある場合は最初のヒット、あるいは深い階層のヒットなど戦略が必要だが、
    # ADCの構造上、ルートに近い側にあるはず。
    
    # output_root が相対パス名 ("output") の場合
    target_root_name = os.path.basename(output_root)
    source_root_name = os.path.basename(upload_root)

    try:
        # 右側から探す（ネストした構造で誤爆しないように...いや、ADCはルート直下か）
        # 通常は <Root>/output/... なので、partsの中で target_root_name と一致するインデックスを探す
        # 大文字小文字を区別するかはOS依存だがWindowsは区別しない。一応小文字で比較。
        idx = -1
        for i, p in enumerate(parts):
            if p.lower() == target_root_name.lower():
                idx = i
                break
        
        if idx == -1:
            # outputが含まれていない場合は変換できない
            return None
            
        # uploads 側に置換
        parts[idx] = source_root_name
        
    except ValueError:
        return None

    # 2. 最終階層のフォルダ名（VideoName_Timestamp）からTimestampを除去
    clip_folder_name = parts[-1]
    
    # パターン: 末尾が _YYYYMMDD_HHMMSS
    # 厳密には inference.py の timestamp = start_dt.strftime("%Y%m%d_%H%M%S")
    # 正規表現: _\d{8}_\d{6}$
    
    match = re.search(r'_(\d{8}_\d{6})$', clip_folder_name)
    original_name_candidate = clip_folder_name
    if match:
        # マッチした部分を除去
        original_name_candidate = clip_folder_name[:match.start()]
    
    parts[-1] = original_name_candidate
    
    # 構成しなおしたディレクトリパス (ファイル名を含まない、その親ディレクトリ)
    # クリップフォルダ = 動画ファイル名_Timestamp なので、元の構造は
    # uploads/.../Parent/VideoName.mp4
    # output/.../Parent/VideoName_Timestamp/
    # つまり、parts[-1] (VideoName) はファイル名（拡張子なし）に相当するはず。
    # しかし uploads 側では VideoName.mp4 はフォルダではなくファイル。
    # なので、検索すべきディレクトリは parts[:-1] です。
    
    search_dir = os.sep.join(parts[:-1])
    target_filename_no_ext = parts[-1]
    
    if not os.path.isdir(search_dir):
        return None
        
    # 3. 拡張子違いの同名ファイルを検索
    # FOLDER_VIDEO_EXTENSIONS は inference.py にあるが、循環参照を避けるためここで定義または file_utils からあれば使う
    # ここでは一般的な動画拡張子を列挙
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".ts", ".m4v"}
    
    for filename in os.listdir(search_dir):
        base, ext = os.path.splitext(filename)
        if base == target_filename_no_ext and ext.lower() in video_exts:
            return os.path.join(search_dir, filename)
            
    return None

def _format_relative_path(target_path: str, base_path: str) -> str:
    """ベースフォルダを基準にした相対パスを表示用に整形する。"""
    if not target_path:
        return ""
    try:
        rel = os.path.relpath(target_path, base_path)
    except ValueError:
        return os.path.basename(target_path)

    if rel in (".", "") or rel.startswith(".."):
        return os.path.basename(target_path)

    return rel.replace(os.sep, "/")

def _gather_folder_summaries(upload_root: str, folder_names: List[str]) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for folder in folder_names:
        alias_dir = os.path.join(upload_root, folder)
        resolved_path, is_link, exists, source_path = resolve_registered_folder(upload_root, folder)
        video_paths: List[str] = []
        if exists:
            video_paths = collect_video_files(resolved_path, include_subdirectories=True)

        video_count = len(video_paths)
        total_bytes = 0
        sample_files: List[str] = []
        subdir_candidates: set[str] = set()
        for path in video_paths:
            display = _format_relative_path(path, resolved_path)
            if display and len(sample_files) < 5:
                sample_files.append(display)
            parent = os.path.dirname(display)
            if parent and parent not in {"", "."}:
                subdir_candidates.add(parent)
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass

        subdir_samples = sorted(subdir_candidates)[:5]

        settings = load_folder_settings(alias_dir)

        summaries.append(
            {
                "name": folder,
                "count": video_count,
                "size_mb": (total_bytes / (1024 * 1024)) if total_bytes else 0.0,
                "samples": sample_files,
                "subdir_count": len(subdir_candidates),
                "subdir_samples": subdir_samples,
                "is_link": is_link,
                "exists": exists,
                "source_path": source_path or resolved_path,
                "settings": settings,
            }
        )

    return summaries
