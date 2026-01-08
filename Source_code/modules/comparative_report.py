"""
比較分析レポート生成モジュール

年度別・道路タイプ別の追い越しイベントを比較分析し、
統計検定とグラフを含むレポートを生成する。
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import io
import pandas as pd
import numpy as np
from scipy import stats

from .db_manager import MAIN_DB_PATH, configure_connection


@dataclass
class OvertakeMetrics:
    """追い越しイベントの指標を格納するデータクラス"""
    
    # 白線距離（メートル）
    line_distances: List[float] = field(default_factory=list)
    overtaker_line_distances: List[float] = field(default_factory=list)
    overtaken_line_distances: List[float] = field(default_factory=list)
    
    # 離隔距離（メートル）
    clearance_distances: List[float] = field(default_factory=list)
    
    # 速度（km/h）
    overtake_speeds: List[float] = field(default_factory=list)
    
    # 加速度（m/s²）
    accelerations_before: List[float] = field(default_factory=list)
    accelerations_after: List[float] = field(default_factory=list)
    
    # イベント数
    total_events: int = 0
    
    # 動画数（ユニーク）
    unique_videos: int = 0
    
    # 内側・外側追い越しのカウント
    inner_overtakes: int = 0
    outer_overtakes: int = 0


@dataclass
class GroupStatistics:
    """グループの統計量"""
    
    count: int
    mean: float
    median: float
    std: float
    min: float
    max: float
    q1: float  # 第1四分位数（25%）
    q3: float  # 第3四分位数（75%）
    
    @classmethod
    def from_data(cls, data: Sequence[float]) -> Optional["GroupStatistics"]:
        """データから統計量を計算"""
        if not data:
            return None
        
        arr = np.array(data)
        return cls(
            count=len(arr),
            mean=float(np.mean(arr)),
            median=float(np.median(arr)),
            std=float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            min=float(np.min(arr)),
            max=float(np.max(arr)),
            q1=float(np.percentile(arr, 25)),
            q3=float(np.percentile(arr, 75)),
        )


def remove_outliers(data: Sequence[float]) -> List[float]:
    """
    IQR法を用いて外れ値を除去する
    Q1 - 1.5*IQR <= x <= Q3 + 1.5*IQR の範囲外を除外
    """
    if len(data) < 4:
        return list(data)
    
    arr = np.array(data)
    q1 = np.percentile(arr, 25)
    q3 = np.percentile(arr, 75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    
    return [x for x in data if lower <= x <= upper]


class ComparativeAnalyzer:
    """比較分析エンジン"""
    
    def __init__(self, db_path: str = MAIN_DB_PATH):
        self.db_path = db_path
        self.data: Dict[Tuple[str, int], OvertakeMetrics] = {}
        self.metadata: Dict[str, Any] = {}
        self.raw_records: List[Dict[str, Any]] = []
        self.loaded_run_ids: set = set()
    
    def load_overtake_data(
        self,
        run_ids: Optional[Sequence[int]] = None,
        collection_years: Optional[Sequence[int]] = None,
        road_types: Optional[Sequence[str]] = None,
        directions: Optional[Sequence[str]] = None,
    ) -> None:
        """
        追い越しイベントデータをロードし、道路タイプと年度でグループ化
        
        Args:
            run_ids: 分析対象のRun ID（Noneの場合は全て）
            collection_years: 収集年度のリスト（Noneの場合は全て）
            road_types: 道路タイプのリスト（Noneの場合は全て）
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        configure_connection(conn, mode="read")
        cursor = conn.cursor()
        
        try:
            # クエリ構築
            where_clauses = []
            params = []
            
            if run_ids:
                placeholders = ",".join("?" * len(run_ids))
                where_clauses.append(f"p.run_id IN ({placeholders})")
                params.extend(run_ids)
            
            if collection_years:
                placeholders = ",".join("?" * len(collection_years))
                where_clauses.append(f"v.collection_year IN ({placeholders})")
                params.extend(collection_years)
            
            if road_types:
                placeholders = ",".join("?" * len(road_types))
                where_clauses.append(f"v.road_type IN ({placeholders})")
                params.extend(road_types)
            
            if directions:
                placeholders = ",".join("?" * len(directions))
                where_clauses.append(f"d.travel_direction IN ({placeholders})")
                params.extend(directions)
            
            # road_typeとcollection_yearが設定されているもののみを対象
            where_clauses.append("v.road_type IS NOT NULL")
            where_clauses.append("v.collection_year IS NOT NULL")
            
            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            
            query = f"""
            SELECT 
                v.road_type,
                v.collection_year,
                v.video_id,
                p.run_id,
                e.overtake_event_id,
                e.event_frame_num,
                e.line_distance_m,
                e.clearance_distance_m,
                e.speed_profile_json,
                e.l_line_distance_m,
                e.r_line_distance_m
            FROM OvertakeEvents e
            JOIN ProcessLog p ON e.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
            JOIN Detection d ON e.run_id = d.run_id 
                 AND e.event_frame_num = d.frame_num 
                 AND e.overtaker_auto_id = d.auto_id
            {where_sql}
            ORDER BY v.collection_year, v.road_type, e.run_id, e.event_frame_num
            """
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # グループごとにメトリクスを集計
            grouped_data: Dict[Tuple[str, int], OvertakeMetrics] = defaultdict(OvertakeMetrics)
            video_counts: Dict[Tuple[str, int], set] = defaultdict(set)
            self.raw_records = []
            self.loaded_run_ids = set()
            
            
            for row in rows:
                # 離隔距離が10m以上の場合は外れ値（追い越しなし）として除外
                if row["clearance_distance_m"] is not None and row["clearance_distance_m"] >= 10.0:
                    continue

                road_type = row["road_type"]
                year = row["collection_year"]
                key = (road_type, year)
                
                metrics = grouped_data[key]
                metrics.total_events += 1
                
                # Run IDを記録
                self.loaded_run_ids.add(row["run_id"])

                # 動画をカウント
                video_counts[key].add(row["video_id"])
                
                # 白線距離
                if row["line_distance_m"] is not None:
                    metrics.line_distances.append(row["line_distance_m"])
                
                # 左右の白線距離から内側・外側を判定
                l_dist = row["l_line_distance_m"]
                r_dist = row["r_line_distance_m"]
                if l_dist is not None and r_dist is not None:
                    if l_dist < r_dist:
                        metrics.inner_overtakes += 1
                    else:
                        metrics.outer_overtakes += 1
                
                # 離隔距離
                if row["clearance_distance_m"] is not None:
                    metrics.clearance_distances.append(row["clearance_distance_m"])
                
                # 速度プロファイルから追い越し時の速度と加速度を抽出
                if row["speed_profile_json"]:
                    try:
                        speed_profile = json.loads(row["speed_profile_json"])
                        
                        # 追い越し瞬間（offset=0）の速度
                        if "0.0" in speed_profile and speed_profile["0.0"] is not None:
                            metrics.overtake_speeds.append(speed_profile["0.0"])
                        
                        # 加速度計算（前後1秒の速度差）
                        # 前: -1.0秒, 後: +1.0秒
                        speed_before = speed_profile.get("-1.0")
                        speed_at = speed_profile.get("0.0")
                        speed_after = speed_profile.get("1.0")
                        
                        if speed_before is not None and speed_at is not None:
                            # km/h -> m/s に変換してから加速度計算
                            v_before = speed_before / 3.6
                            v_at = speed_at / 3.6
                            acc_before = (v_at - v_before) / 1.0  # m/s²
                            metrics.accelerations_before.append(acc_before)
                        
                        if speed_at is not None and speed_after is not None:
                            v_at = speed_at / 3.6
                            v_after = speed_after / 3.6
                            acc_after = (v_after - v_at) / 1.0  # m/s²
                            metrics.accelerations_after.append(acc_after)
                        
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass

                # Raw Record 追加
                self.raw_records.append({
                    "Video_ID": row["video_id"],
                    "Run_ID": row["run_id"],
                    "Event_ID": row["overtake_event_id"],
                    "Year": year,
                    "Road_Type": "Widened" if road_type == "widened" else "Non-Widened" if road_type == "non_widened" else road_type,
                    "Line_Distance_m": row["line_distance_m"],
                    "Clearance_Distance_m": row["clearance_distance_m"],
                    "Overtake_Speed_kmh": speed_at if 'speed_at' in locals() and speed_at is not None else None,
                    "Accel_Before_ms2": acc_before if 'acc_before' in locals() and acc_before is not None else None,
                    "Accel_After_ms2": acc_after if 'acc_after' in locals() and acc_after is not None else None,
                    "Inner_Overtake": 1 if l_dist is not None and r_dist is not None and l_dist < r_dist else 0,
                    "Outer_Overtake": 1 if l_dist is not None and r_dist is not None and l_dist >= r_dist else 0,
                })
                
                # ローカル変数のクリーンアップ (ループ内での誤用防止)
                if 'speed_at' in locals(): del speed_at
                if 'acc_before' in locals(): del acc_before
                if 'acc_after' in locals(): del acc_after
            
            # 動画数をカウント
            for key, metrics in grouped_data.items():
                metrics.unique_videos = len(video_counts[key])
            
            self.data = dict(grouped_data)
            
            # メタデータを保存
            all_years = sorted(set(year for _, year in self.data.keys()))
            all_road_types = sorted(set(road_type for road_type, _ in self.data.keys()))
            
            self.metadata = {
                "total_events": sum(m.total_events for m in self.data.values()),
                "total_videos": sum(m.unique_videos for m in self.data.values()),
                "years": all_years,
                "road_types": all_road_types,
                "groups": len(self.data),
                "run_ids": sorted(list(self.loaded_run_ids)),
            }
            
        finally:
            cursor.close()
            conn.close()
    



    def compute_statistics(
        self, metric_name: str = "line_distances", exclude_outliers: bool = False
    ) -> Dict[Tuple[str, int], Optional[GroupStatistics]]:
        """
        指定した指標の統計量を計算
        
        Args:
            metric_name: 指標名（line_distances, clearance_distances, overtake_speeds等）
            exclude_outliers: Trueの場合、IQR法で外れ値を除去してから統計量を計算
        
        Returns:
            グループごとの統計量
        """
        stats = {}
        for key, metrics in self.data.items():
            data = getattr(metrics, metric_name, [])
            if exclude_outliers:
                data = remove_outliers(data)
            stats[key] = GroupStatistics.from_data(data)
        return stats
    
    def get_summary(self) -> Dict[str, Any]:
        """
        サマリー情報を取得
        
        Returns:
            サマリー辞書
        """
        summary = {
            "metadata": self.metadata.copy(),
            "groups": {}
        }
        
        for (road_type, year), metrics in self.data.items():
            key = f"{road_type}_{year}"
            summary["groups"][key] = {
                "road_type": road_type,
                "year": year,
                "total_events": metrics.total_events,
                "unique_videos": metrics.unique_videos,
                "inner_overtakes": metrics.inner_overtakes,
                "outer_overtakes": metrics.outer_overtakes,
                "overtake_frequency": (
                    metrics.total_events / metrics.unique_videos
                    if metrics.unique_videos > 0
                    else 0
                ),
            }
        
        return summary

    def generate_excel_bytes(self, metrics: List[str]) -> bytes:
        """
        現在の分析結果、統計、RawデータをExcelファイル(bytes)として生成する
        """
        output = io.BytesIO()
        
        # カラム名の日本語マッピング
        raw_col_map = {
            "Video_ID": "動画ID",
            "Run_ID": "Run ID",
            "Event_ID": "イベントID",
            "Year": "年度",
            "Road_Type": "道路タイプ",
            "Line_Distance_m": "白線距離(m)",
            "Clearance_Distance_m": "離隔距離(m)",
            "Overtake_Speed_kmh": "追い越し速度(km/h)",
            "Accel_Before_ms2": "加速度(追い越し前)(m/s²)",
            "Accel_After_ms2": "加速度(追い越し後)(m/s²)",
            "Inner_Overtake": "内側追い越し",
            "Outer_Overtake": "外側追い越し",
        }
        
        stats_col_map = {
            "Metric": "指標",
            "Road_Type": "道路タイプ",
            "Year": "年度",
            "Count": "件数",
            "Mean": "平均",
            "Median": "中央値",
            "Std_Dev": "標準偏差",
            "Min": "最小値",
            "Max": "最大値",
            "Q1": "第1四分位数",
            "Q3": "第3四分位数",
        }
        
        tests_col_map = {
            "Metric": "指標",
            "Test_Type": "検定手法",
            "P_Value": "p値",
            "Statistic": "統計量",
            "Significant": "有意差あり",
            "Interpretation": "解釈",
            "Groups_Compared": "比較グループ",
        }

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # 1. Raw Data Sheet (Analysis Result)
            if self.raw_records:
                df_raw = pd.DataFrame(self.raw_records)
                df_raw = df_raw.rename(columns=raw_col_map)
                df_raw.to_excel(writer, sheet_name='分析用データ', index=False)
            
            # 2. Statistics Sheet
            stats_data = []
            for metric in metrics:
                group_stats = self.compute_statistics(metric)
                for (rt, yr), st in group_stats.items():
                    if st:
                        row = {
                            "Metric": metric,
                            "Road_Type": "拡幅" if rt == "widened" else "未拡幅" if rt == "non_widened" else rt,
                            "Year": yr,
                            "Count": st.count,
                            "Mean": st.mean,
                            "Median": st.median,
                            "Std_Dev": st.std,
                            "Min": st.min,
                            "Max": st.max,
                            "Q1": st.q1,
                            "Q3": st.q3
                        }
                        stats_data.append(row)
            
            if stats_data:
                df_stats = pd.DataFrame(stats_data)
                df_stats = df_stats.rename(columns=stats_col_map)
                df_stats.to_excel(writer, sheet_name='基本統計量', index=False)

            # 3. Test Results Sheet
            test_results = []
            from .comparative_report import compare_two_groups, compare_multiple_groups 
            
            for metric in metrics:
                groups_data = {}
                for (rt, yr), metrics_obj in self.data.items():
                    val = getattr(metrics_obj, metric, [])
                    if val:
                        label = f"{'拡幅' if rt == 'widened' else '未拡幅' if rt == 'non_widened' else rt}_{yr}"
                        groups_data[label] = val
                
                if len(groups_data) >= 2:
                    result = None
                    if len(groups_data) == 2:
                        keys = list(groups_data.keys())
                        result = compare_two_groups(groups_data[keys[0]], groups_data[keys[1]], keys[0], keys[1])
                    else:
                        result = compare_multiple_groups(groups_data)
                    
                    if result:
                        test_results.append({
                            "Metric": metric,
                            "Test_Type": result.test_type,
                            "P_Value": result.p_value,
                            "Statistic": result.statistic,
                            "Significant": "はい" if result.significant else "いいえ",
                            "Interpretation": result.interpretation,
                            "Groups_Compared": ", ".join(result.groups_compared)
                        })

            if test_results:
                df_tests = pd.DataFrame(test_results)
                df_tests = df_tests.rename(columns=tests_col_map)
                df_tests.to_excel(writer, sheet_name='検定結果', index=False)

            # 4. Raw DB Tables Export
            if self.loaded_run_ids:
                run_ids_list = list(self.loaded_run_ids)
                
                # DB接続
                conn = sqlite3.connect(self.db_path)
                try:
                    # DB_ProcessLog
                    placeholders = ",".join("?" * len(run_ids_list))
                    
                    df_pl = pd.read_sql_query(
                       f"SELECT * FROM ProcessLog WHERE run_id IN ({placeholders})",
                       conn,
                       params=run_ids_list
                    )
                    df_pl.to_excel(writer, sheet_name='DB_ProcessLog', index=False)
                    
                    # DB_OvertakeEvents
                    df_oe = pd.read_sql_query(
                       f"SELECT * FROM OvertakeEvents WHERE run_id IN ({placeholders})",
                       conn,
                       params=run_ids_list
                    )
                    df_oe.to_excel(writer, sheet_name='DB_OvertakeEvents', index=False)
                    
                    # DB_Video
                    # ProcessLogからvideo_idを取得してフィルタリング
                    video_ids = df_pl['video_id'].unique().tolist()
                    if video_ids:
                        v_placeholders = ",".join("?" * len(video_ids))
                        df_v = pd.read_sql_query(
                            f"SELECT * FROM Video WHERE video_id IN ({v_placeholders})",
                            conn,
                            params=video_ids
                        )
                        df_v.to_excel(writer, sheet_name='DB_Video', index=False)
                        
                finally:
                    conn.close()
        
        return output.getvalue()

def get_available_years_and_road_types() -> Dict[str, Any]:
    """
    データベースから利用可能な年度と道路タイプのリストを取得
    
    Returns:
        {
            "years": [2023, 2024, ...],
            "road_types": ["widened", "non_widened"],
            "combinations": [(road_type, year), ...],
            "counts": {(road_type, year): count, ...}
        }
    """
    conn = sqlite3.connect(MAIN_DB_PATH)
    conn.row_factory = sqlite3.Row
    configure_connection(conn, mode="read")
    cursor = conn.cursor()
    
    try:
        query = """
        SELECT 
            v.road_type,
            v.collection_year,
            COUNT(DISTINCT e.overtake_event_id) as event_count,
            COUNT(DISTINCT v.video_id) as video_count
        FROM Video v
        JOIN ProcessLog p ON v.video_id = p.video_id
        JOIN OvertakeEvents e ON p.run_id = e.run_id
        WHERE v.road_type IS NOT NULL 
          AND v.collection_year IS NOT NULL
        GROUP BY v.road_type, v.collection_year
        ORDER BY v.collection_year, v.road_type
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()

        # 方向ごとのカウントも取得
        query_dir = """
        SELECT 
            d.travel_direction,
            COUNT(DISTINCT e.overtake_event_id) as event_count
        FROM OvertakeEvents e
        JOIN Detection d ON e.run_id = d.run_id 
             AND e.event_frame_num = d.frame_num 
             AND e.overtaker_auto_id = d.auto_id
        WHERE d.travel_direction IS NOT NULL
        GROUP BY d.travel_direction
        """
        cursor.execute(query_dir)
        dir_rows = cursor.fetchall()
        direction_counts = {row["travel_direction"]: row["event_count"] for row in dir_rows}
        
        
        years = set()
        road_types = set()
        combinations = []
        counts = {}
        
        for row in rows:
            road_type = row["road_type"]
            year = row["collection_year"]
            years.add(year)
            road_types.add(road_type)
            combinations.append((road_type, year))
            counts[(road_type, year)] = {
                "events": row["event_count"],
                "videos": row["video_count"],
            }
        
        return {
            "years": sorted(years),
            "road_types": sorted(road_types),
            "combinations": combinations,
            "counts": counts,
            "direction_counts": direction_counts
        }
    
    finally:
        cursor.close()
        conn.close()


# ==================== 統計検定関数 ====================

@dataclass
class StatisticalTestResult:
    """統計検定の結果"""
    
    test_type: str  # "t_test", "mann_whitney", "anova", "kruskal_wallis"
    p_value: float
    statistic: float
    effect_size: Optional[float] = None
    significant: bool = False  # α=0.05
    interpretation: str = ""
    groups_compared: List[str] = field(default_factory=list)
    sample_sizes: Dict[str, int] = field(default_factory=dict)


def test_normality(data: Sequence[float], alpha: float = 0.05) -> Tuple[bool, float]:
    """
    Shapiro-Wilk検定で正規性を検定
    
    Args:
        data: データ
        alpha: 有意水準
    
    Returns:
        (is_normal, p_value)
    """
    if len(data) < 3:
        return False, 1.0
    
    try:
        stat, p_value = stats.shapiro(data)
        return p_value > alpha, p_value
    except Exception:
        return False, 0.0


def cohens_d(group1: Sequence[float], group2: Sequence[float]) -> float:
    """
    Cohen's d（効果量）を計算
    
    小: 0.2, 中: 0.5, 大: 0.8
    """
    arr1 = np.array(group1)
    arr2 = np.array(group2)
    
    n1, n2 = len(arr1), len(arr2)
    var1, var2 = np.var(arr1, ddof=1), np.var(arr2, ddof=1)
    
    # プールされた標準偏差
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    
    if pooled_std == 0:
        return 0.0
    
    return (np.mean(arr1) - np.mean(arr2)) / pooled_std


def eta_squared(groups: List[Sequence[float]]) -> float:
    """
    η² (eta squared)を計算（ANOVA用の効果量）
    
    小: 0.01, 中: 0.06, 大: 0.14
    """
    all_data = np.concatenate([np.array(g) for g in groups])
    grand_mean = np.mean(all_data)
    
    # SSB (between-group sum of squares)
    ssb = sum(len(g) * (np.mean(g) - grand_mean) ** 2 for g in groups)
    
    # SST (total sum of squares)
    sst = np.sum((all_data - grand_mean) ** 2)
    
    if sst == 0:
        return 0.0
    
    return ssb / sst


def compare_two_groups(
    group1: Sequence[float],
    group2: Sequence[float],
    group1_name: str = "Group 1",
    group2_name: str = "Group 2",
    alpha: float = 0.05,
) -> StatisticalTestResult:
    """
    2群の比較検定を実行（正規性に基づいてt検定またはMann-Whitney U検定を選択）
    
    Args:
        group1: グループ1のデータ
        group2: グループ2のデータ
        group1_name: グループ1の名前
        group2_name: グループ2の名前
        alpha: 有意水準
    
    Returns:
        統計検定結果
    """
    if len(group1) < 2 or len(group2) < 2:
        return StatisticalTestResult(
            test_type="insufficient_data",
            p_value=1.0,
            statistic=0.0,
            significant=False,
            interpretation="データが不足しています",
            groups_compared=[group1_name, group2_name],
            sample_sizes={group1_name: len(group1), group2_name: len(group2)},
        )
    
    # 正規性検定
    normal1, p1 = test_normality(group1, alpha)
    normal2, p2 = test_normality(group2, alpha)
    
    mean1, mean2 = np.mean(group1), np.mean(group2)
    
    if normal1 and normal2:
        # 両方正規分布 → t検定
        stat, p_value = stats.ttest_ind(group1, group2)
        test_type = "t_test"
        effect = cohens_d(group1, group2)
        
        if p_value < alpha:
            direction = "大きい" if mean1 > mean2 else "小さい"
            interpretation = f"{group1_name}は{group2_name}よりも有意に{direction}（p={p_value:.4f}, Cohen's d={effect:.2f}）"
        else:
            interpretation = f"{group1_name}と{group2_name}に有意な差は認められません（p={p_value:.4f}）"
    else:
        # どちらかが非正規 → Mann-Whitney U検定
        stat, p_value = stats.mannwhitneyu(group1, group2, alternative="two-sided")
        test_type = "mann_whitney"
        effect = None
        
        if p_value < alpha:
            direction = "大きい" if np.median(group1) > np.median(group2) else "小さい"
            interpretation = f"{group1_name}は{group2_name}よりも有意に{direction}（p={p_value:.4f}, Mann-Whitney U）"
        else:
            interpretation = f"{group1_name}と{group2_name}に有意な差は認められません（p={p_value:.4f}）"
    
    return StatisticalTestResult(
        test_type=test_type,
        p_value=float(p_value),
        statistic=float(stat),
        effect_size=float(effect) if effect is not None else None,
        significant=bool(p_value < alpha),
        interpretation=interpretation,
        groups_compared=[group1_name, group2_name],
        sample_sizes={group1_name: len(group1), group2_name: len(group2)},
    )


def compare_multiple_groups(
    groups: Dict[str, Sequence[float]],
    alpha: float = 0.05,
) -> StatisticalTestResult:
    """
    3群以上の比較検定を実行（正規性に基づいてANOVAまたはKruskal-Wallis検定を選択）
    
    Args:
        groups: {グループ名: データ}の辞書
        alpha: 有意水準
    
    Returns:
        統計検定結果
    """
    group_names = list(groups.keys())
    group_data = [groups[name] for name in group_names]
    
    # データ不足チェック
    valid_groups = [g for g in group_data if len(g) >= 2]
    if len(valid_groups) < 2:
        return StatisticalTestResult(
            test_type="insufficient_data",
            p_value=1.0,
            statistic=0.0,
            significant=False,
            interpretation="有効なデータを持つグループが2つ未満です",
            groups_compared=group_names,
            sample_sizes={name: len(groups[name]) for name in group_names},
        )
    
    # 正規性検定
    all_normal = all(test_normality(g, alpha)[0] for g in group_data if len(g) >= 3)
    
    if all_normal:
        # ANOVA
        stat, p_value = stats.f_oneway(*group_data)
        test_type = "anova"
        effect = eta_squared(group_data)
        
        if p_value < alpha:
            interpretation = f"グループ間に有意な差があります（p={p_value:.4f}, η²={effect:.3f}）"
        else:
            interpretation = f"グループ間に有意な差は認められません（p={p_value:.4f}）"
    else:
        # Kruskal-Wallis検定
        stat, p_value = stats.kruskal(*group_data)
        test_type = "kruskal_wallis"
        effect = None
        
        if p_value < alpha:
            interpretation = f"グループ間に有意な差があります（p={p_value:.4f}, Kruskal-Wallis）"
        else:
            interpretation = f"グループ間に有意な差は認められません（p={p_value:.4f}）"
    
    return StatisticalTestResult(
        test_type=test_type,
        p_value=float(p_value),
        statistic=float(stat),
        effect_size=float(effect) if effect is not None else None,
        significant=bool(p_value < alpha),
        interpretation=interpretation,
        groups_compared=group_names,
        sample_sizes={name: len(groups[name]) for name in group_names},
    )

