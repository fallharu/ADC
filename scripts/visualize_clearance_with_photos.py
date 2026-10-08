"""離隔距離の代表写真と拡幅・未拡幅比較ヒートマップを生成する。"""
from __future__ import annotations
import argparse, base64, sqlite3
from datetime import datetime
from pathlib import Path
import cv2
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap

ROADS=["拡幅","未拡幅"]

def event_rows(c,road):
    return c.execute("""SELECT d.run_id,d.frame_num,d.measure_x,d.measure_y,d.x1,d.y1,d.x2,d.y2,
      d.clearance_distance_m,d.approach_partner_group_id,v.filename,v.source_path
      FROM Detection d JOIN ProcessLog p ON p.run_id=d.run_id JOIN Video v ON v.video_id=p.video_id
      WHERE v.road_type=? AND d.clearance_distance_m BETWEEN .05 AND 10 AND d.travel_direction='B'
      ORDER BY d.clearance_distance_m""",(road,)).fetchall()

def representative(c,road):
    rows=event_rows(c,road); chosen=rows[len(rows)//2]
    run,frame,x,y,x1,y1,x2,y2,dist,partner,name,path=chosen
    cap=cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_FRAMES,int(frame)); ok,img=cap.read(); cap.release()
    if not ok: raise RuntimeError(path)
    partner_row=c.execute("""SELECT measure_x,measure_y,x1,y1,x2,y2,class_name FROM Detection
      WHERE run_id=? AND frame_num=? AND group_id=? ORDER BY confidence DESC LIMIT 1""",(run,frame,partner)).fetchone()
    return dict(road=road,run=run,frame=frame,x=x,y=y,box=(x1,y1,x2,y2),dist=dist,
                partner=partner_row,name=name,image=cv2.cvtColor(img,cv2.COLOR_BGR2RGB),values=np.array([r[8] for r in rows]))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default='db/my_app_data.db'); ap.add_argument('--output',default='output/database_visualization')
    a=ap.parse_args(); out=Path(a.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(f"file:{Path(a.db).resolve().as_posix()}?mode=ro",uri=True)
    reps=[representative(c,r) for r in ROADS]; c.close()
    installed={f.name for f in font_manager.fontManager.ttflist}; plt.rcParams['font.family']=next((x for x in ['Yu Gothic','Meiryo','Noto Sans CJK JP'] if x in installed),'DejaVu Sans')
    cmap=LinearSegmentedColormap.from_list('safety',['#d7191c','#fdae61','#ffffbf','#1a9641'])
    fig=plt.figure(figsize=(18,12),facecolor='#f3f6fa'); gs=fig.add_gridspec(2,2,height_ratios=[1.45,1],hspace=.33,wspace=.22)
    fig.suptitle('離隔距離 × 代表写真・安全性ヒートマップ',fontsize=23,fontweight='bold',y=.985)
    for col,g in enumerate(reps):
        ax=fig.add_subplot(gs[0,col]); img=g['image']; h,w=img.shape[:2]; ax.imshow(img,extent=(0,w,h,0))
        # 計測位置を中心とする半透明の安全度ヒート領域。
        yy,xx=np.mgrid[0:h:220j,0:w:360j]; sigma=max(w,h)*.085
        heat=np.exp(-((xx-g['x'])**2+(yy-g['y'])**2)/(2*sigma**2)); heat=np.ma.masked_where(heat<.08,heat)
        color_value=np.clip((g['dist']-.8)/(2.5-.8),0,1)
        rgba=np.zeros((*heat.shape,4)); rgba[...,:3]=cmap(color_value)[:3]; rgba[...,3]=np.where(heat.mask,0,np.asarray(heat)*.78)
        ax.imshow(rgba,extent=(0,w,h,0),interpolation='bilinear')
        x1,y1,x2,y2=g['box']; ax.add_patch(plt.Rectangle((x1,y1),x2-x1,y2-y1,fill=False,color='white',lw=2))
        if g['partner']:
            px,py,px1,py1,px2,py2,pclass=g['partner']; ax.plot([g['x'],px],[g['y'],py],color='white',lw=3)
            ax.scatter([g['x'],px],[g['y'],py],s=70,color=['#ff3b30','#29b6f6'],edgecolor='white',zorder=5)
            ax.add_patch(plt.Rectangle((px1,py1),px2-px1,py2-py1,fill=False,color='#29b6f6',lw=2))
        label_color=cmap(color_value)
        ax.text(.03,.94,f"離隔距離 {g['dist']:.2f} m",transform=ax.transAxes,ha='left',va='top',fontsize=17,fontweight='bold',color='white',bbox=dict(facecolor=label_color,alpha=.9,pad=6))
        ax.set(title=f"{g['road']}｜Run {g['run']}｜Frame {g['frame']:,}\n{g['name']}",xlabel='X [px]',ylabel='Y [px]',xlim=(0,w),ylim=(h,0))

    bins=np.array([1.0,1.25,1.5,1.75,2.0,2.5,3.0,5.0,10.0]); labels=['1.0–1.25','1.25–1.5','1.5–1.75','1.75–2.0','2.0–2.5','2.5–3.0','3.0–5.0','5.0–10']
    matrix=[]
    for g in reps:
        counts,_=np.histogram(g['values'],bins=bins); matrix.append(counts/max(counts.sum(),1)*100)
    matrix=np.asarray(matrix)
    ax=fig.add_subplot(gs[1,0]); im=ax.imshow(matrix,aspect='auto',cmap='YlOrRd',vmin=0,vmax=max(25,matrix.max()))
    ax.set_xticks(range(len(labels)),labels,rotation=35,ha='right'); ax.set_yticks([0,1],ROADS); ax.set(title='道路区分 × 離隔距離帯ヒートマップ',xlabel='離隔距離 [m]',ylabel='道路区分')
    for i in range(2):
        for j in range(len(labels)):
            if matrix[i,j]>0: ax.text(j,i,f'{matrix[i,j]:.0f}%',ha='center',va='center',fontsize=9)
    fig.colorbar(im,ax=ax,label='区分内構成比 [%]')

    ax=fig.add_subplot(gs[1,1]); colors=['#2878b5','#e07a2d']
    bp=ax.boxplot([g['values'] for g in reps],tick_labels=ROADS,patch_artist=True,showmeans=True,meanprops=dict(marker='D',markerfacecolor='white',markeredgecolor='black'))
    for p,color in zip(bp['boxes'],colors):p.set_facecolor(color);p.set_alpha(.75)
    for i,g in enumerate(reps,1):
        jitter=np.linspace(-.11,.11,len(g['values'])); ax.scatter(i+jitter,g['values'],s=30,color=colors[i-1],alpha=.7,edgecolor='white')
        ax.text(i,ax.get_ylim()[1]*.96,f"n={len(g['values'])}\n平均={g['values'].mean():.2f}m",ha='center',va='top')
    ax.axhspan(0,1.5,color='#d7191c',alpha=.08); ax.set(title='離隔距離の全データ分布',ylabel='離隔距離 [m]');ax.grid(axis='y',alpha=.2)
    fig.text(.012,.012,'写真は各区分の中央値に近い実イベント。赤系ほど離隔が小さく、緑系ほど大きい。全43件は上→下方向。色帯は比較表示であり法的判定ではありません。',fontsize=9,color='#5b7083')
    png=out/'clearance_heatmap_with_photos.png';fig.savefig(png,dpi=150,bbox_inches='tight',facecolor=fig.get_facecolor());plt.close(fig)
    b64=base64.b64encode(png.read_bytes()).decode();html=out/'clearance_heatmap_with_photos.html'
    html.write_text(f"""<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>離隔距離と写真</title><style>body{{margin:0;background:#edf2f7;font-family:system-ui,'Yu Gothic',sans-serif;color:#17324d}}main{{max-width:1800px;margin:24px auto;padding:0 20px}}.panel{{background:white;padding:18px;border-radius:16px;box-shadow:0 8px 30px #17324d18}}img{{width:100%;display:block}}p{{color:#5b7083}}</style></head><body><main><h1>離隔距離 × 代表写真・ヒートマップ</h1><p>生成日時: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}</p><div class=panel><img src='data:image/png;base64,{b64}'></div></main></body></html>""",encoding='utf-8')
    print(png);print(html)

if __name__=='__main__':main()
