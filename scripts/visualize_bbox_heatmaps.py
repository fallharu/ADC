"""バウンディングボックス中心の検出集中位置を正規化ヒートマップで表示する。"""

from __future__ import annotations

import argparse, base64, sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="db/my_app_data.db")
    ap.add_argument("--output", default="output/database_visualization")
    a = ap.parse_args(); db = Path(a.db).resolve(); out = Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    # 各Runの最大検出座標を画面寸法の代理値とし、中心座標を0～1へ正規化する。
    query = """
      WITH bounds AS (
        SELECT run_id, MAX(x2) width, MAX(y2) height FROM DetectionRaw
        WHERE x2>0 AND y2>0 GROUP BY run_id
      )
      SELECT d.class_name, v.road_type,
             ((d.x1+d.x2)/2.0)/b.width nx,
             ((d.y1+d.y2)/2.0)/b.height ny
      FROM DetectionRaw d JOIN bounds b ON b.run_id=d.run_id
      JOIN ProcessLog p ON p.run_id=d.run_id JOIN Video v ON v.video_id=p.video_id
      WHERE b.width>0 AND b.height>0 AND d.x2>d.x1 AND d.y2>d.y1
        AND d.raw_detection_id % 5=0
    """
    rows = c.execute(query).fetchall(); c.close()
    cls=np.array([r[0] or "" for r in rows], dtype=object); road=np.array([r[1] or "" for r in rows], dtype=object)
    xy=np.asarray([[r[2],r[3]] for r in rows],float)
    valid=np.isfinite(xy).all(axis=1)&(xy[:,0]>=0)&(xy[:,0]<=1.05)&(xy[:,1]>=0)&(xy[:,1]<=1.05)
    cls,road,xy=cls[valid],road[valid],xy[valid]
    panels=[
      ("全検出",np.ones(len(xy),bool)),
      ("拡幅",road=="拡幅"),("未拡幅",road=="未拡幅"),
      ("車（car）",cls=="car"),("自転車（bicycle）",cls=="bicycle"),
      ("大型車（truck + bus）",np.isin(cls,["truck","bus"]))]
    hist=[]
    for _,m in panels:
        h,_,_=np.histogram2d(xy[m,0],xy[m,1],bins=(50,34),range=((0,1),(0,1)))
        hist.append(h/max(h.sum(),1)*100)
    positives=np.concatenate([h[h>0] for h in hist if np.any(h>0)])
    vmax=np.percentile(positives,99.5)

    installed={f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"]=next((x for x in ["Yu Gothic","Meiryo","Noto Sans CJK JP"] if x in installed),"DejaVu Sans")
    fig,axes=plt.subplots(3,2,figsize=(15,13),facecolor="#f3f6fa",sharex=True,sharey=True)
    fig.suptitle("バウンディングボックス検出位置ヒートマップ",fontsize=22,fontweight="bold",y=.98)
    for ax,(title,m),h in zip(axes.flat,panels,hist):
        im=ax.imshow(h.T,origin="upper",extent=(0,100,100,0),aspect="auto",cmap="turbo",vmin=0,vmax=vmax)
        ax.set_title(f"{title}（抽出 n={m.sum():,}）",fontweight="bold")
        ax.set_xlabel("画面の横位置 [%]"); ax.set_ylabel("画面の縦位置 [%]")
        ax.axvline(50,color="white",alpha=.35,lw=.8); ax.axhline(50,color="white",alpha=.35,lw=.8)
        cb=fig.colorbar(im,ax=ax,pad=.02); cb.set_label("群内の検出構成比 [% / bin]")
    fig.text(.012,.012,"中心点=(x1+x2)/2,(y1+y2)/2。各Runの最大検出座標で正規化。描画はDBの1/5抽出、色は各群内構成比。Tire系は全検出に含み、車種別パネルから除外。",fontsize=9,color="#5b7083")
    fig.subplots_adjust(top=.93,bottom=.06,hspace=.33,wspace=.22)
    png=out/"bbox_detection_heatmaps.png"; fig.savefig(png,dpi=150,bbox_inches="tight",facecolor=fig.get_facecolor()); plt.close(fig)
    b64=base64.b64encode(png.read_bytes()).decode(); page=out/"bbox_detection_heatmaps.html"
    page.write_text(f"""<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>BBox検出位置ヒートマップ</title><style>body{{margin:0;background:#edf2f7;font-family:system-ui,'Yu Gothic',sans-serif;color:#17324d}}main{{max-width:1500px;margin:24px auto;padding:0 20px}}.panel{{background:white;padding:18px;border-radius:16px;box-shadow:0 8px 30px #17324d18}}img{{width:100%;display:block}}p{{color:#5b7083}}</style></head><body><main><h1>バウンディングボックス検出位置ヒートマップ</h1><p>生成日時: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z} ／ DB読み取り専用</p><div class=panel><img src='data:image/png;base64,{b64}'></div></main></body></html>""",encoding="utf-8")
    print(png); print(page)

if __name__=="__main__": main()
