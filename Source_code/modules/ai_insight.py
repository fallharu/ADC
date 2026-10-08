import os
import json
import logging
import math
import re
from collections import defaultdict
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


METRIC_LABELS = {
    "line_distances": "白線距離 (m)",
    "clearance_distances": "離隔距離 (m)",
    "overtake_speeds": "追い越し速度 (km/h)",
    "accelerations_before": "加速度（追い越し前）(m/s2)",
    "accelerations_after": "加速度（追い越し後）(m/s2)",
}


def _load_gemini_model():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set in environment variables.")

    try:
        import google.generativeai as genai
    except ImportError as e:
        import sys
        import pprint
        path_str = pprint.pformat(sys.path)
        raise RuntimeError(
            "Google Generative AI library is not installed. "
            f"Details: {str(e)}\nExecutable: {sys.executable}\nPath: {path_str}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to import AI library. Details: {str(e)}") from e

    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


def _round_number(value: Any, digits: int = 3) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _road_type_label(road_type: str) -> str:
    if road_type == "widened":
        return "拡幅"
    if road_type == "non_widened":
        return "未拡幅"
    return road_type or "-"


def _group_label(group_key: str, groups: Dict[str, Any]) -> str:
    group = groups.get(group_key) or {}
    year = group.get("year")
    road_type = group.get("road_type")
    if year or road_type:
        return f"{year or ''} {_road_type_label(road_type)}".strip()
    return group_key


def _compact_stats(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not stats:
        return None
    return {
        "count": int(stats.get("count") or 0),
        "mean": _round_number(stats.get("mean")),
        "median": _round_number(stats.get("median")),
        "std": _round_number(stats.get("std")),
        "min": _round_number(stats.get("min")),
        "q1": _round_number(stats.get("q1")),
        "q3": _round_number(stats.get("q3")),
        "max": _round_number(stats.get("max")),
    }


def _metric_group_stats(statistics: Dict[str, Any], groups: Dict[str, Any]) -> Dict[str, Any]:
    compact = {}
    for metric, group_stats in (statistics or {}).items():
        compact[METRIC_LABELS.get(metric, metric)] = {
            _group_label(group_key, groups): _compact_stats(stats)
            for group_key, stats in (group_stats or {}).items()
            if stats
        }
    return compact


def _trend_context(statistics: Dict[str, Any], groups: Dict[str, Any]) -> Dict[str, Any]:
    trends = {}
    for metric, group_stats in (statistics or {}).items():
        metric_label = METRIC_LABELS.get(metric, metric)
        rows = []
        for group_key, stats in (group_stats or {}).items():
            group = groups.get(group_key) or {}
            if not stats:
                continue
            rows.append({
                "year": group.get("year"),
                "road_type": _road_type_label(group.get("road_type")),
                "median": _round_number(stats.get("median")),
                "mean": _round_number(stats.get("mean")),
            })
        trends[metric_label] = sorted(rows, key=lambda row: (row.get("year") or 0, row.get("road_type") or ""))
    return trends


def _sample_count_context(statistics: Dict[str, Any], groups: Dict[str, Any]) -> Dict[str, Any]:
    counts = {}
    for metric, group_stats in (statistics or {}).items():
        counts[METRIC_LABELS.get(metric, metric)] = {
            _group_label(group_key, groups): int((stats or {}).get("count") or 0)
            for group_key, stats in (group_stats or {}).items()
            if stats
        }
    return counts


def _overtake_composition_context(groups: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for group_key, group in (groups or {}).items():
        total = int(group.get("total_events") or 0)
        inner = int(group.get("inner_overtakes") or 0)
        outer = int(group.get("outer_overtakes") or 0)
        rows.append({
            "group": _group_label(group_key, groups),
            "total_events": total,
            "inner_overtakes": inner,
            "outer_overtakes": outer,
            "inner_ratio": round(inner / total, 3) if total else None,
            "outer_ratio": round(outer / total, 3) if total else None,
        })
    return sorted(rows, key=lambda row: row["group"])


def _speed_clearance_context(statistics: Dict[str, Any], groups: Dict[str, Any]) -> List[Dict[str, Any]]:
    speed_stats = statistics.get("overtake_speeds") or {}
    clearance_stats = statistics.get("clearance_distances") or {}
    rows = []
    for group_key, speed in speed_stats.items():
        clearance = clearance_stats.get(group_key)
        if not speed or not clearance:
            continue
        rows.append({
            "group": _group_label(group_key, groups),
            "speed_mean_kmh": _round_number(speed.get("mean")),
            "clearance_mean_m": _round_number(clearance.get("mean")),
            "count": int(clearance.get("count") or speed.get("count") or 0),
        })
    return rows


def _correlation(points: List[Dict[str, Any]]) -> Optional[float]:
    pairs = [
        (_round_number(point.get("x"), 6), _round_number(point.get("y"), 6))
        for point in points
    ]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    x_denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
    y_denominator = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
    if x_denominator == 0 or y_denominator == 0:
        return None
    return round(numerator / (x_denominator * y_denominator), 3)


def _scatter_context(scatter_points: Dict[str, Any], groups: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for key, definition in (scatter_points or {}).items():
        points = definition.get("points") or []
        by_group = defaultdict(list)
        for point in points:
            by_group[point.get("group_key") or "unknown"].append(point)

        group_rows = []
        for group_key, group_points in by_group.items():
            x_values = [_round_number(point.get("x"), 6) for point in group_points]
            y_values = [_round_number(point.get("y"), 6) for point in group_points]
            x_values = [value for value in x_values if value is not None]
            y_values = [value for value in y_values if value is not None]
            group_rows.append({
                "group": _group_label(group_key, groups),
                "count": len(group_points),
                "x_mean": round(sum(x_values) / len(x_values), 3) if x_values else None,
                "y_mean": round(sum(y_values) / len(y_values), 3) if y_values else None,
                "x_min": min(x_values) if x_values else None,
                "x_max": max(x_values) if x_values else None,
                "y_min": min(y_values) if y_values else None,
                "y_max": max(y_values) if y_values else None,
                "correlation": _correlation(group_points),
            })

        result.append({
            "pair_key": key,
            "label": definition.get("label"),
            "x_label": definition.get("x_label"),
            "y_label": definition.get("y_label"),
            "total_count": definition.get("total_count"),
            "filtered_count": definition.get("filtered_count"),
            "shown_count": len(points),
            "sampled": bool(definition.get("sampled")),
            "overall_correlation": _correlation(points),
            "groups": sorted(group_rows, key=lambda row: row["group"]),
        })
    return result


def _tests_context(tests: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for metric, result in (tests or {}).items():
        rows.append({
            "metric": METRIC_LABELS.get(metric, metric),
            "p_value": _round_number(result.get("p_value"), 5),
            "significant": bool(result.get("significant")),
            "test_type": result.get("test_type"),
            "interpretation": result.get("interpretation"),
        })
    return rows


def _delta_context(statistics: Dict[str, Any], groups: Dict[str, Any]) -> Dict[str, Any]:
    years = sorted({
        group.get("year")
        for group in (groups or {}).values()
        if group.get("year") is not None
    })
    deltas = {}
    for metric, group_stats in (statistics or {}).items():
        rows = {}
        for year in years:
            widened = (group_stats or {}).get(f"widened_{year}") or {}
            non_widened = (group_stats or {}).get(f"non_widened_{year}") or {}
            widened_mean = _round_number(widened.get("mean"))
            non_widened_mean = _round_number(non_widened.get("mean"))
            if widened_mean is None or non_widened_mean is None:
                rows[str(year)] = None
            else:
                rows[str(year)] = round(widened_mean - non_widened_mean, 3)
        deltas[METRIC_LABELS.get(metric, metric)] = rows
    return deltas


def _build_chart_contexts(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    summary = report_data.get("summary") or {}
    groups = summary.get("groups") or {}
    statistics = report_data.get("statistics") or {}
    tests = report_data.get("tests") or {}
    scatter_points = report_data.get("scatter_points") or {}

    return [
        {
            "chart_id": "metricMeanChart",
            "title": "選択指標の平均比較",
            "focus": "平均値の群間差を読み取るグラフ",
            "data": _metric_group_stats(statistics, groups),
        },
        {
            "chart_id": "metricTrendChart",
            "title": "中央値の年度推移",
            "focus": "年度変化と道路タイプ別の方向性を読むグラフ",
            "data": _trend_context(statistics, groups),
        },
        {
            "chart_id": "metricRangeChart",
            "title": "ばらつきレンジ",
            "focus": "最小・四分位・中央値・最大から分布幅を読むグラフ",
            "data": _metric_group_stats(statistics, groups),
        },
        {
            "chart_id": "metricCountChart",
            "title": "サンプル数",
            "focus": "各指標・群の件数差と信頼性を読むグラフ",
            "data": _sample_count_context(statistics, groups),
        },
        {
            "chart_id": "overtakeCompositionChart",
            "title": "内側/外側追い越し比率",
            "focus": "追い越し方向の構成差を読むグラフ",
            "data": _overtake_composition_context(groups),
        },
        {
            "chart_id": "speedClearanceChart",
            "title": "速度と離隔距離の関係",
            "focus": "平均速度と平均離隔距離の組み合わせからリスク傾向を読むグラフ",
            "data": _speed_clearance_context(statistics, groups),
        },
        {
            "chart_id": "eventScatterChart",
            "title": "分布分析（イベント単位の散布図）",
            "focus": "イベント単位の相関・ばらつき・外れ傾向を読むグラフ",
            "data": _scatter_context(scatter_points, groups),
        },
        {
            "chart_id": "testPValueChart",
            "title": "検定結果（p値）",
            "focus": "統計的有意差の有無と解釈上の注意を読むグラフ",
            "data": _tests_context(tests),
        },
        {
            "chart_id": "heatmapCharts",
            "title": "ヒートマップ",
            "focus": "年度・道路タイプ・指標横断の濃淡、差分、p値を読む表現",
            "data": {
                "group_statistics": _metric_group_stats(statistics, groups),
                "widened_minus_non_widened_mean_delta": _delta_context(statistics, groups),
                "tests": _tests_context(tests),
            },
        },
    ]


def _parse_chart_insight_json(text: str) -> List[Dict[str, Any]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(raw[start:end + 1])

    insights = parsed.get("insights") if isinstance(parsed, dict) else parsed
    if not isinstance(insights, list):
        raise ValueError("Gemini response did not contain an insights list.")

    normalized = []
    for item in insights:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "chart_id": str(item.get("chart_id") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "insight": str(item.get("insight") or "").strip(),
            "watch_points": [
                str(point).strip()
                for point in (item.get("watch_points") or [])
                if str(point).strip()
            ],
            "action": str(item.get("action") or "").strip(),
        })
    return normalized


def generate_report_insight(report_data: Dict[str, Any]) -> str:
    """
    Generate professional traffic safety insight based on the comparative report data.
    
    Args:
        report_data: JSON dictionary containing summary, statistics, and tests from the report.
        
    Returns:
        A Markdown formatted string with the AI's analysis.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Error: GOOGLE_API_KEY is not set in environment variables."

    try:
        import google.generativeai as genai
    except ImportError as e:
        import sys
        import pprint
        path_str = pprint.pformat(sys.path)
        return f"Error: Google Generative AI library is not installed. Details: {str(e)}\nExecutable: {sys.executable}\nPath: {path_str}"
    except Exception as e:
        return f"Error: Failed to import AI library. Details: {str(e)}"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Construct a concise prompt
        metadata = report_data.get("summary", {}).get("metadata", {})
        groups = report_data.get("summary", {}).get("groups", {})
        stats = report_data.get("statistics", {})
        tests = report_data.get("tests", {})
        
        # Convert complex objects to simple string representation for prompt
        prompt_context = f"""
        # Analysis Data
        Total Events: {metadata.get('total_events')}
        Total Videos: {metadata.get('total_videos')}
        
        # Group Summaries
        {json.dumps(groups, ensure_ascii=False, indent=2)}
        
        # Statistical Tests Results (Significant Only)
        {json.dumps({k:v for k,v in tests.items() if v.get('significant')}, ensure_ascii=False, indent=2)}
        
        # Key Statistics
        {json.dumps(stats, ensure_ascii=False, indent=2)}
        """

        prompt = f"""
        You are an expert Traffic Safety Data Analyst. 
        Analyze the following comparative data between road types (e.g., widened vs non-widened) and/or years.
        
        Data:
        {prompt_context}
        
        Please provide a professional, insightful analysis in Japanese. Use Markdown formatting.
        Structure your response as follows:
        1. **Overview (概要)**: Brief summary of the data scope.
        2. **Key Findings (主な発見事項)**: Highlight significant differences in overtake behaviors (distance, speed, risk).
        3. **Safety Implications (安全性への示唆)**: diverse specific road types (widened vs non-widened) affect cyclist safety based on the metrics (clearance distance, etc.).
        4. **Conclusion (結論)**: Final verdict on the observed changes.

        Keep it concise but detailed enough for a technical report.
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        logger.error(f"AI Generation failed: {e}")
        return f"Error generating insight: {str(e)}"


def generate_chart_insights(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate Gemini insight cards for each chart in the comparative report."""
    model = _load_gemini_model()
    chart_contexts = _build_chart_contexts(report_data)

    prompt_context = json.dumps(chart_contexts, ensure_ascii=False, indent=2)
    prompt = f"""
You are a traffic safety data analyst. Analyze each chart context below and return chart-specific observations in Japanese.

Rules:
- Return ONLY valid JSON, no Markdown fences, no prose outside JSON.
- Use this exact shape:
  {{"insights":[{{"chart_id":"...", "title":"...", "insight":"...", "watch_points":["..."], "action":"..."}}]}}
- Produce one item for every chart_id in the input.
- Keep each insight to 2 concise Japanese sentences.
- watch_points must contain 1 to 3 short Japanese bullets.
- action must be one practical next check or interpretation caution.
- Do not invent causes that are not supported by the data.
- If data volume is small or missing, explicitly say that interpretation is limited.

Chart contexts:
{prompt_context}
"""

    response = model.generate_content(prompt)
    insights = _parse_chart_insight_json(response.text)

    known_titles = {item["chart_id"]: item["title"] for item in chart_contexts}
    known_ids = set(known_titles)
    cleaned = []
    seen = set()
    for item in insights:
        chart_id = item.get("chart_id")
        if chart_id not in known_ids or chart_id in seen:
            continue
        seen.add(chart_id)
        cleaned.append({
            "chart_id": chart_id,
            "title": item.get("title") or known_titles[chart_id],
            "insight": item.get("insight") or "見解を生成できませんでした。",
            "watch_points": item.get("watch_points") or [],
            "action": item.get("action") or "",
        })

    missing = known_ids - seen
    for chart_id in chart_contexts:
        if chart_id["chart_id"] in missing:
            cleaned.append({
                "chart_id": chart_id["chart_id"],
                "title": chart_id["title"],
                "insight": "このグラフの見解はGemini応答に含まれませんでした。",
                "watch_points": ["データと表示条件を確認してください。"],
                "action": "再生成を試してください。",
            })

    return cleaned
