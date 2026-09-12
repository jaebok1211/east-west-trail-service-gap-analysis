from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
from matplotlib import font_manager, rcParams
import numpy as np
import pandas as pd
from pyproj import Transformer

from common import find_file, parse_combined_gpx

TRACK_INDEX = {**{n:n-1 for n in range(1,13)}, **{n:12+(n-47) for n in range(47,56)}}
WEST=[1,2,3,4,9,10,11,12]
EAST=[47,48,49,50,51,52,53,54,55]


def configure_font() -> None:
    available={f.name for f in font_manager.fontManager.ttflist}
    for name in ["Noto Sans CJK KR","NanumGothic","NanumBarunGothic","UnDotum"]:
        if name in available:
            rcParams["font.family"]=name; break
    rcParams["axes.unicode_minus"]=False
    rcParams["figure.dpi"]=200


def scalebar(ax, length_km: float=5, xfrac: float=.06, yfrac: float=.06) -> None:
    xmin,xmax=ax.get_xlim(); ymin,ymax=ax.get_ylim()
    x=xmin+(xmax-xmin)*xfrac; y=ymin+(ymax-ymin)*yfrac
    length=length_km*1000
    ax.plot([x,x+length],[y,y],color="#333",lw=2)
    ax.plot([x,x],[y-150,y+150],color="#333",lw=1)
    ax.plot([x+length,x+length],[y-150,y+150],color="#333",lw=1)
    ax.text(x+length/2,y+250,f"{length_km:g} km",ha="center",va="bottom",fontsize=7.5)


def north_arrow(ax) -> None:
    ax.annotate("N",xy=(.95,.92),xytext=(.95,.80),xycoords="axes fraction",textcoords="axes fraction",
                ha="center",va="center",fontsize=9,fontweight="bold",
                arrowprops=dict(arrowstyle="-|>",color="#333",lw=1.3))


def load_route_xy(raw_root: Path, route: pd.DataFrame) -> dict[int,np.ndarray]:
    gpx=find_file(raw_root,["1~12","47~55","전체구간"],".gpx")
    tracks=parse_combined_gpx(gpx)
    transformer=Transformer.from_crs("EPSG:4326","EPSG:5174",always_xy=True)
    result={}
    for _,r in route.iterrows():
        sec=int(r["구간번호"]); pts=tracks[TRACK_INDEX[sec]]
        if str(r["GPX방향보정"]).strip()=="역순보정": pts=list(reversed(pts))
        lon=np.array([p[0] for p in pts]); lat=np.array([p[1] for p in pts])
        x,y=transformer.transform(lon,lat)
        result[sec]=np.c_[x,y]
    return result


def activity_figure(csv_dir: Path, fig_dir: Path) -> None:
    d=pd.read_csv(csv_dir/"04_activity_prevalence_day_vs_overnight.csv")
    names=["하이킹(산책)","등산","자연풍경감상","로프체험(짚라인 등)","래프팅, 계곡물놀이 등 수상활동","야영(캠핑)"]
    d=d[d["활동명"].isin(names)].set_index("활동명").loc[names].reset_index()
    fig,ax=plt.subplots(figsize=(9.2,5.0))
    y=np.arange(len(d))
    ax.hlines(y,d["당일형참여자_경험비율(%)"],d["숙박형참여자_경험비율(%)"],color="#BFC5C9",lw=2.4)
    ax.scatter(d["당일형참여자_경험비율(%)"],y,color="#4477AA",s=70,label="당일형")
    ax.scatter(d["숙박형참여자_경험비율(%)"],y,color="#EE7733",s=70,label="숙박형")
    for i,r in d.iterrows():
        ax.text(r["당일형참여자_경험비율(%)"]-1.0,i,f"{r['당일형참여자_경험비율(%)']:.1f}",ha="right",va="center",fontsize=8,color="#315A84")
        ax.text(r["숙박형참여자_경험비율(%)"]+1.0,i,f"{r['숙박형참여자_경험비율(%)']:.1f}",ha="left",va="center",fontsize=8,color="#A94E1B")
    ax.set_yticks(y); ax.set_yticklabels(d["활동명"]); ax.invert_yaxis()
    ax.set_xlim(0,max(d[["당일형참여자_경험비율(%)","숙박형참여자_경험비율(%)"]].max())+10)
    ax.set_xlabel("활동 경험 비율(%)"); ax.grid(axis="x",alpha=.18)
    ax.spines[["top","right","left"]].set_visible(False); ax.tick_params(axis="y",length=0)
    ax.legend(frameon=False,ncol=2,loc="lower right")
    ax.set_title("숙박형 산림활동은 일반 걷기보다 캠핑·체험과 결합되는 경향이 강하다",loc="left",fontsize=13,fontweight="bold")
    fig.tight_layout(); fig.savefig(fig_dir/"figure1_activity_comparison.png",bbox_inches="tight"); plt.close(fig)


def region_figure(csv_dir: Path, fig_dir: Path) -> None:
    d=pd.read_csv(csv_dir/"08_region_tourism_summary.csv").sort_values("지역체류시장여건지수")
    fig,ax=plt.subplots(figsize=(9.0,4.6))
    y=np.arange(len(d)); vals=d["지역체류시장여건지수"]
    ax.barh(y,vals,color="#6BAED6",height=.55)
    for i,(v,name) in enumerate(zip(vals,d["지역"])):
        ax.text(v+1,i,f"{v:.1f}",va="center",fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(d["지역"]); ax.set_xlim(0,100)
    ax.set_xlabel("체류시장 여건 보조지수(0~100)")
    ax.grid(axis="x",alpha=.18); ax.spines[["top","right","left"]].set_visible(False); ax.tick_params(axis="y",length=0)
    ax.set_title("지역여건은 구간 순위가 아니라 보완 방식의 현실성을 판단하는 보조지표다",loc="left",fontsize=13,fontweight="bold")
    fig.tight_layout(); fig.savefig(fig_dir/"figure2_region_context.png",bbox_inches="tight"); plt.close(fig)


def overview_map(raw_root: Path, csv_dir: Path, fig_dir: Path) -> None:
    route=pd.read_csv(csv_dir/"10_route_metadata_final.csv"); pri=pd.read_csv(csv_dir/"14_priority_table_final.csv")
    tracks=load_route_xy(raw_root,route); ranks=dict(zip(pri["구간번호"].astype(int),pri["보완우선순위"].astype(int)))
    fig,(a1,a2)=plt.subplots(1,2,figsize=(12.8,5.5),gridspec_kw={"wspace":.08})
    for ax,secs,subtitle in [(a1,WEST,"서부권: 태안·예산·홍성"),(a2,EAST,"동부권: 봉화·울진")]:
        for sec in secs:
            xy=tracks[sec]; rank=ranks[sec]
            if rank<=5: color,lw="#D73027",3.5
            elif rank<=8: color,lw="#2C7BB6",3.0
            else: color,lw="#A7A9AC",2.2
            ax.plot(xy[:,0],xy[:,1],color=color,lw=lw,zorder=2)
            mid=xy[len(xy)//2]
            ax.text(mid[0],mid[1],str(sec),fontsize=7.5,ha="center",va="center",zorder=3,
                    bbox=dict(boxstyle="round,pad=.15",fc="white",ec=color,lw=.8))
            if rank<=5:
                ax.scatter([xy[0,0],xy[-1,0]],[xy[0,1],xy[-1,1]],s=22,color="#111",zorder=4)
        allxy=np.vstack([tracks[s] for s in secs]); padx=(allxy[:,0].max()-allxy[:,0].min())*.07; pady=(allxy[:,1].max()-allxy[:,1].min())*.08
        ax.set_xlim(allxy[:,0].min()-padx,allxy[:,0].max()+padx); ax.set_ylim(allxy[:,1].min()-pady,allxy[:,1].max()+pady)
        ax.set_aspect("equal"); ax.axis("off"); ax.set_title(subtitle,loc="left",fontsize=10.5,fontweight="bold")
        north_arrow(ax); scalebar(ax,5 if secs==WEST else 10)
    legend=[Line2D([0],[0],color="#D73027",lw=3,label="우선보완 1~5위"),Line2D([0],[0],color="#2C7BB6",lw=3,label="6~8위·비교구간"),Line2D([0],[0],color="#A7A9AC",lw=3,label="그 외 구간"),Line2D([0],[0],marker="o",color="none",markerfacecolor="#111",markersize=5,label="상위구간 시·종점")]
    fig.legend(handles=legend,loc="lower center",ncol=4,frameon=False,bbox_to_anchor=(.5,-.01),fontsize=8)
    fig.suptitle("우선보완 구간은 동부권에 집중되며, 서부권에서는 12구간의 숙박 공백이 확인됐다",x=.03,y=.99,ha="left",fontsize=14,fontweight="bold")
    fig.tight_layout(rect=[0,.04,1,.94]); fig.savefig(fig_dir/"figure3_overall_priority_map.png",bbox_inches="tight"); plt.close(fig)


def detail_maps(raw_root: Path, csv_dir: Path, fig_dir: Path) -> None:
    route=pd.read_csv(csv_dir/"10_route_metadata_final.csv"); pri=pd.read_csv(csv_dir/"14_priority_table_final.csv").set_index("구간번호")
    ep=pd.read_csv(csv_dir/"11_endpoint_accessibility_final.csv"); pts=pd.read_csv(csv_dir/"facility_points_for_maps.csv")
    tracks=load_route_xy(raw_root,route); transformer=Transformer.from_crs("EPSG:4326","EPSG:5174",always_xy=True)
    configs={54:"시작",53:"종료",51:"종료",12:"종료"}
    colors={"숙박전체":"#7B3294","일반숙박":"#7B3294","농어촌민박":"#C2A5CF","식음":"#E66101","보급":"#5E3C99","버스":"#1B9E77"}
    markers={"숙박전체":"s","일반숙박":"s","농어촌민박":"s","식음":"o","보급":"^","버스":"D"}
    fig,axs=plt.subplots(2,2,figsize=(12,9.4)); axs=axs.ravel()
    for ax,(sec,point_type) in zip(axs,configs.items()):
        xy=tracks[sec]; ax.plot(xy[:,0],xy[:,1],color="#2C7BB6",lw=2.8,zorder=2)
        g=ep[(ep["구간번호"].eq(sec)) & (ep["지점"].eq(point_type))].iloc[0]
        ex,ey=transformer.transform(float(g["lon"]),float(g["lat"]))
        ax.scatter([ex],[ey],s=65,color="#D73027",edgecolor="white",linewidth=.8,zorder=5)
        ax.add_patch(Circle((ex,ey),1000,fill=False,ec="#D73027",ls="--",lw=1.1,zorder=1))
        ax.add_patch(Circle((ex,ey),3000,fill=False,ec="#FDAE61",ls=":",lw=1.3,zorder=1))
        relevant=pts[(pts["구간번호"].eq(sec)) & (pts["지점"].eq(point_type)) & (pts["시설유형"].isin(["숙박전체","식음","보급","버스"])) & (pts["순위"].le(3))].copy()
        if not relevant.empty:
            px,py=transformer.transform(relevant["lon"].to_numpy(),relevant["lat"].to_numpy()); relevant["x"]=px; relevant["y"]=py
            for ftype,sub in relevant.groupby("시설유형"):
                ax.scatter(sub["x"],sub["y"],s=28,color=colors[ftype],marker=markers[ftype],alpha=.9,zorder=4)
        # Include nearest food even outside 3km and closest supply separately
        food=f"음식점 {int(g['식음_1km수'])}/{int(g['식음_3km수'])}개(1/3km), 최근접 {g['식음_최근접km']:.2f}km"
        supply=f"보급 {int(g['보급_1km수'])}/{int(g['보급_3km수'])}개(1/3km), 최근접 {g['보급_최근접km']:.2f}km"
        lodging=f"숙박 {int(g['숙박전체_1km수'])}/{int(g['숙박전체_3km수'])}개(1/3km), 최근접 {g['숙박전체_최근접km']:.2f}km"
        bus=f"버스 {int(g['버스_1km수'])}/{int(g['버스_3km수'])}개(1/3km), 최근접 {g['버스_최근접km']:.2f}km"
        if sec in [53,54]: key="식사 기능 공백"; lines=[food,supply]
        elif sec==51: key="종점 보급·교통 후보"; lines=[food,supply,bus]
        else: key="상업숙박 공백"; lines=[lodging,food,supply]
        text=f"취약지점: {g['지점명']}({point_type})\n핵심: {key}\n"+"\n".join(lines)
        ax.text(.02,.02,text,transform=ax.transAxes,ha="left",va="bottom",fontsize=7.3,bbox=dict(boxstyle="round,pad=.35",fc="white",ec="#CCCCCC",alpha=.95),zorder=10)
        # extent route + points + 3km circle, cap whitespace
        allx=list(xy[:,0])+[ex-3300,ex+3300]; ally=list(xy[:,1])+[ey-3300,ey+3300]
        if not relevant.empty: allx+=list(relevant["x"]); ally+=list(relevant["y"])
        padx=(max(allx)-min(allx))*.05; pady=(max(ally)-min(ally))*.05
        ax.set_xlim(min(allx)-padx,max(allx)+padx); ax.set_ylim(min(ally)-pady,max(ally)+pady); ax.set_aspect("equal"); ax.axis("off")
        ax.set_title(f"{sec}구간 | {pri.loc[sec,'추천운영유형']}",loc="left",fontsize=10.5,fontweight="bold")
        north_arrow(ax); scalebar(ax,2)
    handles=[Line2D([0],[0],color="#2C7BB6",lw=2.5,label="트레일"),Line2D([0],[0],marker="o",color="none",markerfacecolor="#D73027",markersize=7,label="취약 시·종점"),Line2D([0],[0],marker="s",color="none",markerfacecolor=colors["숙박전체"],label="숙박"),Line2D([0],[0],marker="o",color="none",markerfacecolor=colors["식음"],label="음식점"),Line2D([0],[0],marker="^",color="none",markerfacecolor=colors["보급"],label="보급"),Line2D([0],[0],marker="D",color="none",markerfacecolor=colors["버스"],label="버스정류장")]
    fig.legend(handles=handles,loc="lower center",ncol=6,frameon=False,bbox_to_anchor=(.5,-.01),fontsize=8)
    fig.suptitle("상위 4개 구간은 같은 상위권이라도 취약지점과 필요한 기능이 다르다",x=.03,y=.99,ha="left",fontsize=14,fontweight="bold")
    fig.tight_layout(rect=[0,.04,1,.95]); fig.savefig(fig_dir/"figure4_top4_detail_maps.png",bbox_inches="tight"); plt.close(fig)


def gap_figure(csv_dir: Path, fig_dir: Path) -> None:
    d=pd.read_csv(csv_dir/"14_priority_table_final.csv")
    show=list(d.head(6)["구간번호"].astype(int))+[55]
    d=d.set_index("구간번호").loc[show]
    fig=plt.figure(figsize=(11.5,5.5)); gs=fig.add_gridspec(1,3,width_ratios=[1.05,2.2,1.45],wspace=.18)
    ax0=fig.add_subplot(gs[0,0]); ax1=fig.add_subplot(gs[0,1]); ax2=fig.add_subplot(gs[0,2])
    y=np.arange(len(d)); need=d["체류보급필요도"].to_numpy()
    ax0.barh(y,need,color="#4C78A8",height=.58); ax0.set_yticks(y); ax0.set_yticklabels([f"{s}구간"+("(비교)" if s==55 else "") for s in show]); ax0.invert_yaxis(); ax0.set_xlim(0,100); ax0.set_xlabel("필요도")
    for i,v in enumerate(need): ax0.text(v+1,i,f"{v:.1f}",va="center",fontsize=7.5)
    ax0.grid(axis="x",alpha=.15); ax0.spines[["top","right","left"]].set_visible(False); ax0.tick_params(axis="y",length=0); ax0.set_title("이동부담 기반\n체류·보급 필요도",fontsize=10,fontweight="bold")
    vals=d[["숙박서비스공백","식음보급공백","교통위치공백"]].to_numpy()
    im=ax1.imshow(vals,aspect="auto",cmap="YlOrRd",vmin=0,vmax=max(70,vals.max()))
    ax1.set_xticks(range(3)); ax1.set_xticklabels(["숙박","식음·보급","교통"]); ax1.set_yticks([]); ax1.set_title("기능별 서비스 공백",fontsize=10,fontweight="bold")
    for i in range(vals.shape[0]):
        for j in range(vals.shape[1]): ax1.text(j,i,f"{vals[i,j]:.1f}",ha="center",va="center",fontsize=8,color="white" if vals[i,j]>42 else "#222")
    ax1.tick_params(length=0); [s.set_visible(False) for s in ax1.spines.values()]
    ax2.set_xlim(0,1); ax2.set_ylim(len(d)-.5,-.5); ax2.axis("off"); ax2.set_title("권장 운영유형",fontsize=10,fontweight="bold")
    for i,(sec,r) in enumerate(d.iterrows()):
        ax2.text(.02,i,str(r["추천운영유형"]),va="center",fontsize=8.4,fontweight="bold" if i<4 else "normal")
        if sec==51: ax2.text(.02,i+.28,"교통은 노선·배차 추가확인",va="center",fontsize=6.8,color="#555")
    cbar=fig.colorbar(im,ax=ax1,fraction=.035,pad=.03); cbar.set_label("공백점수")
    fig.suptitle("필요도가 높아도 서비스 기반이 있으면 우선순위는 낮아진다",x=.03,y=.99,ha="left",fontsize=14,fontweight="bold")
    fig.tight_layout(rect=[0,0,1,.94]); fig.savefig(fig_dir/"figure5_need_gap_typology.png",bbox_inches="tight"); plt.close(fig)


def run(raw_root: Path, csv_dir: Path, fig_dir: Path) -> None:
    fig_dir.mkdir(parents=True,exist_ok=True); configure_font()
    activity_figure(csv_dir,fig_dir); region_figure(csv_dir,fig_dir); overview_map(raw_root,csv_dir,fig_dir); detail_maps(raw_root,csv_dir,fig_dir); gap_figure(csv_dir,fig_dir)


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--raw-root",type=Path,required=True); p.add_argument("--csv-dir",type=Path,required=True); p.add_argument("--fig-dir",type=Path,required=True)
    a=p.parse_args(); run(a.raw_root,a.csv_dir,a.fig_dir)

