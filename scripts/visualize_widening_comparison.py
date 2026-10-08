"""Video.road_type を使い、拡幅・未拡幅の安全性と処理品質を比較する。"""

from __future__ import annotations

import argparse, base64, sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

TYPES = ["拡幅", "未拡幅"]
COLORS = {"拡幅": "#2878b5", "未拡幅": "#e07a2d"}


def arr(c, sql, params=()):
    return np.asarray(c.execute(sql, params).fetchall(), dtype=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="db/my_app_data.db")
    ap.add_argument("--output", default="output/database_visualization")
    a = ap.parse_args()
    db, out = Path(a.db).resolve(), Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)

    summary = {}
    for road in TYPES:
        summary[road] = c.execute("""
          SELECT COUNT(DISTINCT v.video_id), COUNT(DISTINCT p.run_id), COUNT(d.raw_detection_id),
                 AVG(d.confidence)
          FROM Video v JOIN ProcessLog p ON p.video_id=v.video_id
          LEFT JOIN DetectionRaw d ON d.run_id=p.run_id WHERE v.road_type=?
        """, (road,)).fetchone()
    clear = {r: arr(c, """
      SELECT d.clearance_distance_m FROM Detection d JOIN ProcessLog p ON p.run_id=d.run_id
      JOIN Video v ON v.video_id=p.video_id
      WHERE v.road_type=? AND d.clearance_distance_m BETWEEN .05 AND 10
    """, (r,)).ravel() for r in TYPES}
    prox = {r: arr(c, """
      SELECT d.front_distance_m,d.approach_distance_m FROM Detection d
      JOIN ProcessLog p ON p.run_id=d.run_id JOIN Video v ON v.video_id=p.video_id
      WHERE v.road_type=? AND d.front_distance_m BETWEEN .05 AND 50
        AND d.approach_distance_m BETWEEN .05 AND 50
    """, (r,)) for r in TYPES}
    class_quality = c.execute("""
      SELECT v.road_type,d.class_name,COUNT(*),AVG(d.confidence)
      FROM DetectionRaw d JOIN ProcessLog p ON p.run_id=d.run_id JOIN Video v ON v.video_id=p.video_id
      WHERE v.road_type IN ('拡幅','未拡幅') GROUP BY v.road_type,d.class_name
    """).fetchall()
    run_quality = {r: arr(c, """
      SELECT d.run_id,COUNT(*),AVG(d.confidence) FROM DetectionRaw d
      JOIN ProcessLog p ON p.run_id=d.run_id JOIN Video v ON v.video_id=p.video_id
      WHERE v.road_type=? GROUP BY d.run_id HAVING COUNT(*)>=100
    """, (r,)) for r in TYPES}
    event_counts = {r: c.execute("""
      SELECT COUNT(*) FROM OvertakeEvents o JOIN ProcessLog p ON p.run_id=o.run_id
      JOIN Video v ON v.video_id=p.video_id WHERE v.road_type=?
    """, (r,)).fetchone()[0] for r in TYPES}
    c.close()

    installed = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"] = next((x for x in ["Yu Gothic","Meiryo","Noto Sans CJK JP"] if x in installed), "DejaVu Sans")
    plt.rcParams["axes.unicode_minus"] = False
    fig = plt.figure(figsize=(17, 12), facecolor="#f3f6fa")
    gs = fig.add_gridspec(3, 2, hspace=.38, wspace=.27)
    fig.suptitle("拡幅・未拡幅道路の安全性／処理品質比較", fontsize=23, fontweight="bold", y=.985)

    ax = fig.add_subplot(gs[0,0])
    bp = ax.boxplot([clear[r] for r in TYPES], tick_labels=TYPES, patch_artist=True, showmeans=True,
                    meanprops=dict(marker="D", markerfacecolor="white", markeredgecolor="#222"))
    for patch,r in zip(bp["boxes"],TYPES): patch.set_facecolor(COLORS[r]); patch.set_alpha(.72)
    ax.axhspan(0,1.0,color="#d73027",alpha=.08); ax.axhspan(1,1.5,color="#fdae61",alpha=.10)
    ax.set(title="追越し離隔距離の分布", ylabel="離隔距離 [m]"); ax.grid(axis="y",alpha=.2)
    for i,r in enumerate(TYPES,1):
        ax.text(i, ax.get_ylim()[1]*.94, f"n={len(clear[r])}\n平均={np.mean(clear[r]):.2f}m", ha="center", va="top", fontsize=9)

    ax = fig.add_subplot(gs[0,1])
    rates=[event_counts[r]/summary[r][1] for r in TYPES]
    bars=ax.bar(TYPES,rates,color=[COLORS[r] for r in TYPES],alpha=.85)
    ax.set(title="追越しイベント率（Run数で正規化）",ylabel="イベント数 / Run"); ax.grid(axis="y",alpha=.2)
    for b,r in zip(bars,TYPES): ax.text(b.get_x()+b.get_width()/2,b.get_height(),f"{b.get_height():.3f}\n({event_counts[r]}件)",ha="center",va="bottom")

    vmax=1
    hists={}
    for r in TYPES:
        if prox[r].size:
            hists[r],_,_=np.histogram2d(prox[r][:,0],prox[r][:,1],bins=35,range=[[0,50],[0,50]])
            hists[r]=hists[r]/max(hists[r].sum(),1)*100
            vmax=max(vmax,np.percentile(hists[r][hists[r]>0],99))
    for col,r in enumerate(TYPES):
        ax=fig.add_subplot(gs[1,col])
        im=ax.imshow(hists[r].T,origin="lower",extent=(0,50,0,50),aspect="auto",cmap="YlOrRd",vmin=0,vmax=vmax)
        ax.set(title=f"{r}: 前方距離 × 接近距離",xlabel="前方距離 [m]",ylabel="接近距離 [m]")
        fig.colorbar(im,ax=ax,label="群内構成比 [% / bin]")

    ax=fig.add_subplot(gs[2,0])
    classes=sorted({x[1] for x in class_quality})
    x=np.arange(len(classes)); width=.36
    for offset,r in [(-width/2,"拡幅"),(width/2,"未拡幅")]:
        lookup={row[1]:row[3] for row in class_quality if row[0]==r}
        ax.bar(x+offset,[lookup.get(k,np.nan) for k in classes],width,label=r,color=COLORS[r])
    ax.set_xticks(x,classes,rotation=20); ax.set_ylim(.3,.75)
    ax.set(title="クラス別・平均検出信頼度",ylabel="平均信頼度"); ax.legend(); ax.grid(axis="y",alpha=.2)

    ax=fig.add_subplot(gs[2,1])
    for r in TYPES:
        q=run_quality[r]
        ax.scatter(q[:,1],q[:,2],s=np.clip(np.sqrt(q[:,1])*1.7,12,120),alpha=.58,label=r,color=COLORS[r],edgecolor="white",linewidth=.3)
    ax.set_xscale("log"); ax.set_ylim(.28,.9)
    ax.set(title="Run別 検出数 × 平均信頼度",xlabel="検出レコード数（対数）",ylabel="平均信頼度"); ax.legend(); ax.grid(alpha=.2)

    s=" / ".join(f"{r}: 動画{summary[r][0]}・Run{summary[r][1]}・検出{summary[r][2]:,}・平均信頼度{summary[r][3]:.3f}" for r in TYPES)
    fig.text(.012,.012,"比較母数: "+s+"。未設定3動画は除外。信頼度は正解率ではなく処理品質の代理指標。",fontsize=9,color="#5b7083")
    png=out/"widened_vs_unwidened_dashboard.png"; fig.savefig(png,dpi=150,bbox_inches="tight",facecolor=fig.get_facecolor()); plt.close(fig)
    b64=base64.b64encode(png.read_bytes()).decode()
    page=out/"widened_vs_unwidened_dashboard.html"
    page.write_text(f"""<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>拡幅・未拡幅比較</title><style>body{{margin:0;background:#edf2f7;font-family:system-ui,'Yu Gothic',sans-serif;color:#17324d}}main{{max-width:1600px;margin:24px auto;padding:0 20px}}.panel{{background:white;padding:18px;border-radius:16px;box-shadow:0 8px 30px #17324d18}}img{{display:block;width:100%}}p{{color:#5b7083}}</style></head><body><main><h1>拡幅・未拡幅道路 比較ダッシュボード</h1><p>生成日時: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z} ／ Video.road_typeで分類</p><div class=panel><img src='data:image/png;base64,{b64}'></div></main></body></html>""",encoding="utf-8")
    print(png); print(page)

if __name__=="__main__": main()
