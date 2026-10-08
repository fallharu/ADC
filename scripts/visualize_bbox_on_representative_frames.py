"""拡幅・未拡幅の代表フレームへBBox検出密度を重ねる。"""

from __future__ import annotations

import argparse, base64, os, sqlite3
from datetime import datetime
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import PowerNorm


def choose_video(c, road):
    candidates=c.execute("""
      SELECT v.filename,v.source_path,p.run_id,COUNT(d.raw_detection_id) n
      FROM Video v JOIN ProcessLog p ON p.video_id=v.video_id
      LEFT JOIN DetectionRaw d ON d.run_id=p.run_id
      WHERE v.road_type=? GROUP BY v.video_id,p.run_id ORDER BY n DESC
    """,(road,)).fetchall()
    for name,path,run,n in candidates:
        if path and os.path.exists(path) and Path(path).suffix.lower() in {".mp4",".m4v",".avi"}:
            return name,path,run,n
    raise RuntimeError(f"{road}の読込可能な代表動画がありません")


def load_group(c, road):
    name,path,run,n=choose_video(c,road)
    frame_num=c.execute("""
      SELECT frame_num FROM DetectionRaw WHERE run_id=?
      GROUP BY frame_num ORDER BY COUNT(*) DESC,frame_num LIMIT 1
    """,(run,)).fetchone()[0]
    point_rows=c.execute("""
      SELECT class_name,track_id,frame_num,(x1+x2)/2.0,(y1+y2)/2.0 FROM DetectionRaw
      WHERE run_id=? AND x2>x1 AND y2>y1
    """,(run,)).fetchall()
    classes=np.asarray([r[0] or "" for r in point_rows],dtype=object)
    tracks=np.asarray([f"{r[0]}:{r[1]}" if r[1] is not None else "" for r in point_rows],dtype=object)
    frames=np.asarray([r[2] for r in point_rows],dtype=int)
    points=np.asarray([[r[3],r[4]] for r in point_rows],float)
    # 各トラックの先頭から末尾へYが増えるものだけを「上→下」と判定する。
    downward=np.zeros(len(point_rows),dtype=bool)
    for track in np.unique(tracks[tracks!=""]):
        idx=np.flatnonzero(tracks==track)
        if len(idx)<3:
            continue
        ordered=idx[np.argsort(frames[idx])]
        if points[ordered[-1],1]-points[ordered[0],1]>10:
            downward[idx]=True
    cap=cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_FRAMES,int(frame_num))
    ok,frame=cap.read(); cap.release()
    if not ok: raise RuntimeError(f"代表フレームを読み込めません: {path}")
    return dict(road=road,name=name,path=path,run=run,n=n,frame_num=frame_num,
                image=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),points=points,classes=classes,downward=downward)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--db",default="db/my_app_data.db"); ap.add_argument("--output",default="output/database_visualization")
    a=ap.parse_args(); db=Path(a.db).resolve(); out=Path(a.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(f"file:{db.as_posix()}?mode=ro",uri=True)
    groups=[load_group(c,"拡幅"),load_group(c,"未拡幅")]; c.close()
    installed={f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"]=next((x for x in ["Yu Gothic","Meiryo","Noto Sans CJK JP"] if x in installed),"DejaVu Sans")
    fig,axes=plt.subplots(2,2,figsize=(18,12),facecolor="#f3f6fa")
    fig.suptitle("代表動画フレーム × BBox検出密度",fontsize=23,fontweight="bold",y=.98)
    panels=[(groups[0],"car","car"),(groups[0],"bicycle","bicycle"),
            (groups[1],"car","car"),(groups[1],"bicycle","bicycle")]
    for ax,(g,class_name,class_label) in zip(axes.flat,panels):
        direction_mask=g["downward"] & (g["classes"]==class_name)
        img=g["image"]; h,w=img.shape[:2]; pts=g["points"][direction_mask]
        valid=(pts[:,0]>=0)&(pts[:,0]<=w)&(pts[:,1]>=0)&(pts[:,1]<=h); pts=pts[valid]
        hist,xe,ye=np.histogram2d(pts[:,0],pts[:,1],bins=(54,30),range=((0,w),(0,h)))
        smooth=cv2.GaussianBlur(hist.T.astype(np.float32),(0,0),sigmaX=1.25,sigmaY=1.25)
        relative=smooth/max(float(smooth.max()),1.0)*100.0
        masked=np.ma.masked_where(relative<2.0,relative)
        ax.imshow(img,extent=(0,w,h,0))
        im=ax.imshow(masked,extent=(0,w,h,0),cmap="turbo",alpha=.72,interpolation="bilinear",
                     norm=PowerNorm(gamma=.65,vmin=2,vmax=100))
        ax.set_title(f"{g['road']}｜Run {g['run']}｜Frame {g['frame_num']:,}\n{g['name']}",fontsize=12,fontweight="bold")
        ax.text(.02,.96,class_label+"  上→下",transform=ax.transAxes,ha="left",va="top",fontsize=13,
                fontweight="bold",color="white",bbox=dict(facecolor="black",alpha=.58,pad=4))
        ax.set_xlim(0,w); ax.set_ylim(h,0); ax.set_xlabel("X [px]"); ax.set_ylabel("Y [px]")
        cb=fig.colorbar(im,ax=ax,pad=.015,fraction=.035,ticks=[2,20,40,60,80,100])
        cb.set_label("相対検出密度 [%]（各パネル最大=100）")
    fig.text(.012,.018,"代表選定: 読込可能なMP4のうち検出レコード最多。背景: そのRunでBBox数が最多のフレーム。重ね色: Run全体のBBox中心密度（低密度域は透明）。",fontsize=9,color="#5b7083")
    fig.subplots_adjust(top=.90,bottom=.07,hspace=.25,wspace=.14)
    png=out/"bbox_heatmap_car_vs_bicycle.png"; fig.savefig(png,dpi=150,bbox_inches="tight",facecolor=fig.get_facecolor()); plt.close(fig)
    b64=base64.b64encode(png.read_bytes()).decode(); page=out/"bbox_heatmap_car_vs_bicycle.html"
    page.write_text(f"""<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>代表写真とBBoxヒートマップ</title><style>body{{margin:0;background:#edf2f7;font-family:system-ui,'Yu Gothic',sans-serif;color:#17324d}}main{{max-width:1800px;margin:24px auto;padding:0 20px}}.panel{{background:white;padding:18px;border-radius:16px;box-shadow:0 8px 30px #17324d18}}img{{width:100%;display:block}}p{{color:#5b7083}}</style></head><body><main><h1>拡幅・未拡幅 代表写真 × BBox検出密度</h1><p>生成日時: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}</p><div class=panel><img src='data:image/png;base64,{b64}'></div></main></body></html>""",encoding="utf-8")
    print(png); print(page)
    for g in groups: print(g["road"],g["run"],g["frame_num"],g["name"])

if __name__=="__main__": main()
