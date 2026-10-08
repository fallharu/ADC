"""Publication/export figures from anonymous derived tables only."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd


def main():
    ap=argparse.ArgumentParser();ap.add_argument('run',type=Path);a=ap.parse_args()
    tracks=pd.read_csv(a.run/'tables/track_summary.csv')
    plt.rcParams.update({'font.family':'Meiryo','font.size':12,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(10,5.5))
    groups=[('YOLO','video-A'),('CVAT','video-A'),('YOLO','video-B'),('CVAT','video-B')]
    values=[tracks[(tracks.method==m)&(tracks.source_id==s)&(tracks.label=='car')].speed_km_h.to_numpy() for m,s in groups]
    boxes=ax.boxplot(values,tick_labels=[f'{m}\n{s} / n={len(v)}' for (m,s),v in zip(groups,values)],patch_artist=True,whis=1.5)
    for b,c in zip(boxes['boxes'],['#D95F02','#1B7F79']*2):b.set_facecolor(c);b.set_alpha(.3)
    for i,v in enumerate(values,1):ax.scatter([i]*len(v),v,color=['#D95F02','#1B7F79'][(i-1)%2],s=22,zorder=3)
    ax.set_ylabel('車両トラックの速度中央値 (km/h)');ax.set_title('同じ路面校正による速度分布')
    ax.grid(axis='y',alpha=.2)
    fig.text(.1,.02,'A: 未拡幅 / B: 拡幅。各群は別標本、対応する車両の誤差比較ではない。ひげ: 1.5×IQR。',fontsize=10)
    fig.tight_layout(rect=[0,.07,1,1])
    for ext in ['png','svg']:fig.savefig(a.run/'figures'/f'speed_boxplot.{ext}',dpi=200)
    plt.close(fig)
    clearance=pd.read_csv(a.run/'tables/clearance_encounters.csv')
    fig,ax=plt.subplots(figsize=(8,4.5))
    for i,method in enumerate(['YOLO','CVAT']):
        vals=clearance[clearance.method==method].clearance_m
        ax.scatter([i]*len(vals),vals,s=80,color=['#D95F02','#1B7F79'][i])
        for v in vals:ax.annotate(f'{v:.2f} m',(i,v),xytext=(12,0),textcoords='offset points')
    ax.set_xticks([0,1],['YOLO / video-A (n=1)','CVAT / video-A (n=1)']);ax.set_xlim(-.5,1.5);ax.set_ylim(0,2.2)
    ax.set_ylabel('並走時の測定点間の横距離 (m)');ax.set_title('離隔距離の参考値');ax.grid(axis='y',alpha=.2)
    fig.text(.1,.02,'video-B: 校正範囲内の同時観測がなく0件。1件ずつのため箱ひげ・道路差を評価できない。',fontsize=10)
    fig.tight_layout(rect=[0,.09,1,1])
    for ext in ['png','svg']:fig.savefig(a.run/'figures'/f'clearance_observations.{ext}',dpi=200)
    plt.close(fig)


if __name__=='__main__':main()
