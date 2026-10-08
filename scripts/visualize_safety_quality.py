"""安全性・検出品質を散布図とヒートマップで可視化する。"""

from __future__ import annotations

import argparse
import base64
import sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


def array(conn: sqlite3.Connection, sql: str) -> np.ndarray:
    return np.asarray(conn.execute(sql).fetchall(), dtype=float)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="db/my_app_data.db")
    p.add_argument("--output", default="output/database_visualization")
    args = p.parse_args()
    db = Path(args.db).resolve()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    class_rows = conn.execute("""
        SELECT class_name, COUNT(*), AVG(confidence) FROM DetectionRaw
        GROUP BY class_name ORDER BY COUNT(*) DESC
    """).fetchall()
    confidence_hist = conn.execute("""
        SELECT class_name,
          SUM(confidence >= .30 AND confidence < .40),
          SUM(confidence >= .40 AND confidence < .50),
          SUM(confidence >= .50 AND confidence < .60),
          SUM(confidence >= .60 AND confidence < .70),
          SUM(confidence >= .70 AND confidence < .80),
          SUM(confidence >= .80 AND confidence < .90),
          SUM(confidence >= .90 AND confidence <= 1.0)
        FROM DetectionRaw GROUP BY class_name ORDER BY class_name
    """).fetchall()
    run_quality = array(conn, """
        SELECT run_id, COUNT(*), AVG(confidence) FROM DetectionRaw
        GROUP BY run_id HAVING COUNT(*) >= 100
    """)
    # 描画負荷を抑えつつ全期間から均等に抽出する。
    box_quality = array(conn, """
        SELECT confidence, (x2-x1)*(y2-y1) FROM DetectionRaw
        WHERE x2>x1 AND y2>y1 AND raw_detection_id % 20 = 0
          AND (x2-x1)*(y2-y1) BETWEEN 1 AND 500000
    """)
    spatial = array(conn, """
        SELECT measure_x, measure_y FROM Detection
        WHERE measure_x IS NOT NULL AND measure_y IS NOT NULL
          AND measure_x BETWEEN 0 AND 4000 AND measure_y BETWEEN 0 AND 2500
          AND auto_id % 10 = 0
    """)
    proximity = array(conn, """
        SELECT front_distance_m, approach_distance_m FROM Detection
        WHERE front_distance_m BETWEEN 0.05 AND 50
          AND approach_distance_m BETWEEN 0.05 AND 50
    """)
    clearance = array(conn, """
        SELECT row_number() OVER (ORDER BY run_id, frame_num), clearance_distance_m
        FROM Detection WHERE clearance_distance_m BETWEEN 0.05 AND 10
    """)
    zeros = conn.execute("""
        SELECT
          SUM(speed_km_h IS NOT NULL), SUM(speed_km_h = 0),
          SUM(ttc_s IS NOT NULL), SUM(ttc_s = 0)
        FROM Detection
    """).fetchone()
    conn.close()

    installed = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"] = next((x for x in ["Yu Gothic", "Meiryo", "Noto Sans CJK JP"] if x in installed), "DejaVu Sans")
    plt.rcParams["axes.unicode_minus"] = False
    fig = plt.figure(figsize=(17, 12), facecolor="#f3f6fa")
    gs = fig.add_gridspec(3, 2, hspace=.36, wspace=.25)
    fig.suptitle("安全性・処理品質 ダッシュボード", fontsize=23, fontweight="bold", y=.985)

    ax = fig.add_subplot(gs[0, 0])
    if clearance.size:
        ax.scatter(clearance[:, 0], clearance[:, 1], s=28, alpha=.75, color="#e76f51", edgecolor="white", linewidth=.4)
        ax.axhspan(0, 1.0, color="#d73027", alpha=.10, label="参考帯: 1.0m未満")
        ax.axhspan(1.0, 1.5, color="#fdae61", alpha=.12, label="参考帯: 1.0–1.5m")
    ax.set(title="追越し離隔距離（イベント順）", xlabel="離隔計測レコード順", ylabel="離隔距離 [m]")
    ax.legend(loc="upper right", fontsize=9); ax.grid(alpha=.2)

    ax = fig.add_subplot(gs[0, 1])
    if proximity.size:
        hb = ax.hexbin(proximity[:, 0], proximity[:, 1], gridsize=38, bins="log", mincnt=1, cmap="YlOrRd")
        fig.colorbar(hb, ax=ax, label="レコード密度（対数）")
    ax.set(title="前方距離 × 接近距離 ヒートマップ", xlabel="前方車両までの距離 [m]", ylabel="接近距離 [m]", xlim=(0, 50), ylim=(0, 50))
    ax.grid(alpha=.15)

    ax = fig.add_subplot(gs[1, 0])
    matrix = np.asarray([r[1:] for r in confidence_hist], dtype=float)
    matrix = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1) * 100
    im = ax.imshow(matrix, aspect="auto", cmap="Blues", vmin=0, vmax=max(50, matrix.max()))
    ax.set_xticks(range(7), [".30–.40", ".40–.50", ".50–.60", ".60–.70", ".70–.80", ".80–.90", ".90–1.0"])
    ax.set_yticks(range(len(confidence_hist)), [r[0] for r in confidence_hist])
    ax.set(title="クラス別・検出信頼度ヒートマップ", xlabel="信頼度帯", ylabel="検出クラス")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            if matrix[i, j] >= 2: ax.text(j, i, f"{matrix[i,j]:.0f}%", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="クラス内構成比 [%]")

    ax = fig.add_subplot(gs[1, 1])
    if box_quality.size:
        hb = ax.hexbin(box_quality[:, 1], box_quality[:, 0], gridsize=45, bins="log", mincnt=1, cmap="viridis")
        fig.colorbar(hb, ax=ax, label="検出密度（対数）")
    ax.set_xscale("log")
    ax.set(title="物体サイズ × 検出信頼度", xlabel="バウンディングボックス面積 [px²]（対数）", ylabel="検出信頼度", ylim=(.28, 1.0))
    ax.grid(alpha=.15)

    ax = fig.add_subplot(gs[2, 0])
    if spatial.size:
        hb = ax.hexbin(spatial[:, 0], spatial[:, 1], gridsize=55, bins="log", mincnt=1, cmap="magma")
        fig.colorbar(hb, ax=ax, label="検出密度（対数）")
        ax.invert_yaxis()
    ax.set(title="画面内の検出位置ヒートマップ", xlabel="計測点 X [px]", ylabel="計測点 Y [px]")

    ax = fig.add_subplot(gs[2, 1])
    if run_quality.size:
        sizes = np.clip(np.sqrt(run_quality[:, 1]) * 2, 15, 180)
        sc = ax.scatter(run_quality[:, 1], run_quality[:, 2], s=sizes, c=run_quality[:, 2], cmap="RdYlGn", vmin=.3, vmax=.9,
                        alpha=.72, edgecolor="white", linewidth=.4)
        fig.colorbar(sc, ax=ax, label="平均信頼度")
    ax.set_xscale("log")
    ax.set(title="Run別 検出数 × 平均信頼度", xlabel="検出レコード数（対数）", ylabel="平均信頼度", ylim=(.28, .9))
    ax.grid(alpha=.2)

    fig.text(.012, .012,
             f"品質注記: 信頼度はモデル自己評価であり、正解率ではありません。速度 {zeros[1]:,}/{zeros[0]:,}件、TTC {zeros[3]:,}/{zeros[2]:,}件が0のため評価対象外。距離帯は比較用の参考表示です。",
             fontsize=9, color="#5b7083")
    png = out / "safety_quality_dashboard.png"
    fig.savefig(png, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    encoded = base64.b64encode(png.read_bytes()).decode("ascii")
    html = out / "safety_quality_dashboard.html"
    html.write_text(f"""<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>安全性・処理品質ダッシュボード</title><style>body{{margin:0;background:#edf2f7;font-family:system-ui,'Yu Gothic',sans-serif;color:#17324d}}main{{max-width:1600px;margin:24px auto;padding:0 20px}}.panel{{background:#fff;padding:18px;border-radius:16px;box-shadow:0 8px 30px #17324d18}}img{{width:100%;display:block}}p{{color:#5b7083}}</style></head>
<body><main><h1>安全性・処理品質 ダッシュボード</h1><p>生成日時: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z} ／ DB読み取り専用集計</p><div class=panel><img src='data:image/png;base64,{encoded}' alt='安全性と処理品質の散布図・ヒートマップ'></div></main></body></html>""", encoding="utf-8")
    print(png); print(html)


if __name__ == "__main__":
    main()
