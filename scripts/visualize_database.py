"""SQLite の交通解析データを集計し、静的ダッシュボードを生成する。"""

from __future__ import annotations

import argparse
import base64
import html
import sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager


def rows(conn: sqlite3.Connection, sql: str):
    return conn.execute(sql).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="db/my_app_data.db")
    parser.add_argument("--output", default="output/database_visualization")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    class_counts = rows(conn, """
        SELECT class_name, COUNT(*) FROM DetectionRaw
        GROUP BY class_name ORDER BY COUNT(*) DESC
    """)
    statuses = rows(conn, """
        SELECT status, COUNT(*) FROM ProcessLog
        GROUP BY status ORDER BY COUNT(*) DESC
    """)
    traffic = rows(conn, """
        SELECT direction, SUM(count) FROM TrafficCount
        GROUP BY direction ORDER BY SUM(count) DESC
    """)
    top_runs = rows(conn, """
        SELECT run_id, COUNT(*) AS n FROM DetectionRaw
        GROUP BY run_id ORDER BY n DESC LIMIT 10
    """)
    overtake_runs = rows(conn, """
        SELECT run_id, COUNT(*) AS n FROM OvertakeEvents
        GROUP BY run_id ORDER BY n DESC, run_id LIMIT 10
    """)
    totals = {
        "detections": conn.execute("SELECT COUNT(*) FROM DetectionRaw").fetchone()[0],
        "videos": conn.execute("SELECT COUNT(*) FROM Video").fetchone()[0],
        "runs": conn.execute("SELECT COUNT(*) FROM ProcessLog").fetchone()[0],
        "overtakes": conn.execute("SELECT COUNT(*) FROM OvertakeEvents").fetchone()[0],
    }
    conn.close()

    candidates = ["Yu Gothic", "Meiryo", "Noto Sans CJK JP"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"] = next((f for f in candidates if f in installed), "DejaVu Sans")
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(16, 10), facecolor="#f4f7fb")
    grid = fig.add_gridspec(3, 4, height_ratios=[0.55, 2.2, 2.2], hspace=0.55, wspace=0.45)
    fig.suptitle("交通映像解析データベース・ダッシュボード", fontsize=22, fontweight="bold", y=0.98)

    cards = [("検出レコード", totals["detections"]), ("動画", totals["videos"]),
             ("処理Run", totals["runs"]), ("追越しイベント", totals["overtakes"])]
    for i, (label, value) in enumerate(cards):
        ax = fig.add_subplot(grid[0, i])
        ax.set_facecolor("white")
        ax.text(0.5, 0.66, f"{value:,}", ha="center", va="center", fontsize=23,
                fontweight="bold", color="#17324d")
        ax.text(0.5, 0.22, label, ha="center", va="center", fontsize=11, color="#5d7285")
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values(): spine.set_visible(False)

    ax = fig.add_subplot(grid[1, :2])
    labels = [x[0] for x in class_counts][::-1]
    values = [x[1] for x in class_counts][::-1]
    ax.barh(labels, values, color="#2c7fb8")
    ax.set_title("検出クラス別レコード数", loc="left", fontweight="bold")
    ax.grid(axis="x", alpha=.2); ax.set_axisbelow(True)
    ax.ticklabel_format(axis="x", style="plain")
    for y, v in enumerate(values): ax.text(v, y, f" {v:,}", va="center", fontsize=9)

    ax = fig.add_subplot(grid[1, 2])
    status_colors = {"completed": "#2ca25f", "error": "#de2d26", "processing": "#f0a202"}
    wedges, _ = ax.pie([x[1] for x in statuses], startangle=90,
           colors=[status_colors.get(x[0], "#8da0cb") for x in statuses],
           wedgeprops={"width": .42, "edgecolor": "white"})
    ax.text(0, 0, f"{sum(x[1] for x in statuses):,}\nRun", ha="center", va="center",
            fontsize=15, fontweight="bold", color="#17324d")
    ax.legend(wedges, [f"{name}: {count}" for name, count in statuses],
              loc="lower center", bbox_to_anchor=(.5, -0.18), frameon=False, fontsize=9)
    ax.set_title("処理状態", fontweight="bold")

    ax = fig.add_subplot(grid[1, 3])
    ax.bar([x[0] for x in traffic], [x[1] for x in traffic], color=["#7b6fd0", "#54a9a1"])
    ax.set_title("交通カウント（方向別）", fontweight="bold")
    ax.grid(axis="y", alpha=.2); ax.set_axisbelow(True)
    for i, (_, v) in enumerate(traffic): ax.text(i, v, f"{v:,}", ha="center", va="bottom")

    ax = fig.add_subplot(grid[2, :2])
    run_labels = [str(x[0]) for x in top_runs][::-1]
    run_values = [x[1] for x in top_runs][::-1]
    ax.barh(run_labels, run_values, color="#41ab5d")
    ax.set_title("検出レコード数 上位10 Run", loc="left", fontweight="bold")
    ax.set_xlabel("レコード数"); ax.grid(axis="x", alpha=.2); ax.set_axisbelow(True)
    for y, v in enumerate(run_values): ax.text(v, y, f" {v:,}", va="center", fontsize=9)

    ax = fig.add_subplot(grid[2, 2:])
    ot_labels = [str(x[0]) for x in overtake_runs][::-1]
    ot_values = [x[1] for x in overtake_runs][::-1]
    ax.barh(ot_labels, ot_values, color="#f28e2b")
    ax.set_title("追越しイベント数 上位Run", loc="left", fontweight="bold")
    ax.set_xlabel("イベント数"); ax.grid(axis="x", alpha=.2); ax.set_axisbelow(True)
    for y, v in enumerate(ot_values): ax.text(v, y, f" {v:,}", va="center", fontsize=9)

    fig.text(.01, .012, "注: Tire / Bicycle_Tires は物体本体とは別のタイヤ検出クラス。集計元: SQLite（読み取り専用）",
             fontsize=9, color="#5d7285")
    png_path = output_dir / "database_dashboard.png"
    fig.savefig(png_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    img64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    html_path = output_dir / "database_dashboard.html"
    html_path.write_text(f"""<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>DB可視化</title>
<style>body{{margin:0;background:#eef3f8;color:#17324d;font-family:system-ui,'Yu Gothic',sans-serif}}
main{{max-width:1500px;margin:24px auto;padding:0 20px}}.panel{{background:white;border-radius:16px;padding:18px;box-shadow:0 8px 28px #19355018}}
img{{display:block;width:100%;height:auto}}p{{color:#5d7285}}code{{background:#edf2f7;padding:2px 6px;border-radius:5px}}</style></head>
<body><main><h1>交通映像解析データベース・ダッシュボード</h1>
<p>生成日時: {html.escape(generated)} ／ データソース: <code>{html.escape(str(db_path))}</code></p>
<div class=\"panel\"><img alt=\"データベース集計ダッシュボード\" src=\"data:image/png;base64,{img64}\"></div>
</main></body></html>""", encoding="utf-8")
    print(png_path)
    print(html_path)


if __name__ == "__main__":
    main()
