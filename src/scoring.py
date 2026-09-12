from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from common import find_file, geodesic_track_length_km, parse_combined_gpx

ANALYSIS_SECTIONS = [1,2,3,4,9,10,11,12,47,48,49,50,51,52,53,54,55]
TRACK_INDEX = {**{n:n-1 for n in range(1,13)}, **{n:12+(n-47) for n in range(47,56)}}


def access_grade_presence(n1: float, n3: float) -> float:
    if n1 > 0: return 1.0
    if n3 > 0: return 0.5
    return 0.0


def access_grade_food(n1: float, n3: float) -> float:
    if n1 >= 3: return 1.0
    if n1 >= 1: return 0.75
    if n3 >= 3: return 0.5
    if n3 >= 1: return 0.25
    return 0.0


def run(raw_root: Path, inputs_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    route = pd.read_csv(inputs_dir / "route_metadata_official.csv")
    route = route[route["구간번호"].isin(ANALYSIS_SECTIONS)].copy().sort_values("구간번호")
    gpx = find_file(raw_root, ["1~12", "47~55", "전체구간"], ".gpx")
    tracks = parse_combined_gpx(gpx)
    gpx_lengths=[]; starts=[]; ends=[]
    for _, r in route.iterrows():
        sec=int(r["구간번호"]); pts=tracks[TRACK_INDEX[sec]]
        if str(r["GPX방향보정"]).strip()=="역순보정": pts=list(reversed(pts))
        gpx_lengths.append(geodesic_track_length_km(pts)); starts.append(pts[0]); ends.append(pts[-1])
    route["GPX거리_km"] = gpx_lengths
    route["시작경도"]=[x[0] for x in starts]; route["시작위도"]=[x[1] for x in starts]
    route["종료경도"]=[x[0] for x in ends]; route["종료위도"]=[x[1] for x in ends]
    route["거리부담_백분위"] = route["공식거리_km"].rank(pct=True)*100
    route["시간부담_백분위"] = route["공식소요시간_hr"].rank(pct=True)*100
    route["난이도부담_점수"] = (route["공식난이도_대표값"]-1)/4*100
    route["체류보급필요도"] = route[["거리부담_백분위","시간부담_백분위","난이도부담_점수"]].mean(axis=1,skipna=True)
    route["난이도부담_보수점수"] = route.get("난이도부담_보수점수", route["난이도부담_점수"])
    route["체류보급필요도_보수"] = route[["거리부담_백분위","시간부담_백분위","난이도부담_보수점수"]].mean(axis=1,skipna=True)
    route.to_csv(output_dir / "10_route_metadata_final.csv", index=False, encoding="utf-8-sig")

    ep = pd.read_csv(output_dir / "11_endpoint_accessibility_final.csv")
    # 접근성 열을 원자료 개수에서 재생성해 reviewed 값과 동일한 규칙인지 확인
    ep["숙박전체_접근성_재계산"]=[access_grade_presence(a,b) for a,b in zip(ep["숙박전체_1km수"],ep["숙박전체_3km수"])]
    ep["보급_접근성_재계산"]=[access_grade_presence(a,b) for a,b in zip(ep["보급_1km수"],ep["보급_3km수"])]
    ep["버스_접근성_재계산"]=[access_grade_presence(a,b) for a,b in zip(ep["버스_1km수"],ep["버스_3km수"])]
    ep["식음_접근성_재계산"]=[access_grade_food(a,b) for a,b in zip(ep["식음_1km수"],ep["식음_3km수"])]
    ep["식음보급_접근성_재계산"] = ep[["식음_접근성_재계산","보급_접근성_재계산"]].min(axis=1)
    checks=[]
    for c in ["숙박전체_접근성","보급_접근성","버스_접근성","식음_접근성","식음보급_접근성"]:
        checks.append({"변수":c,"최대절대차":float((ep[c]-ep[c+"_재계산"]).abs().max())})
    pd.DataFrame(checks).to_csv(output_dir / "accessibility_rule_check.csv",index=False,encoding="utf-8-sig")

    agg_rows=[]
    for sec,g in ep.groupby("구간번호"):
        row={"구간번호":sec}
        for base in ["농어촌민박","일반숙박","숙박전체","야영장","식음","보급","버스"]:
            idx=g[f"{base}_접근성"].idxmin() if f"{base}_접근성" in g else g[f"{base}_최근접km"].idxmax()
            v=g.loc[idx]
            row[f"{base}_1km_취약지점수"]=v[f"{base}_1km수"]
            row[f"{base}_3km_취약지점수"]=v[f"{base}_3km수"]
            row[f"{base}_최근접km_취약지점"]=v[f"{base}_최근접km"]
        row["숙박전체_접근성"]=g["숙박전체_접근성"].min()
        row["야영장_접근성"]=g["야영장_접근성"].min()
        row["식음_접근성"]=g["식음_접근성"].min()
        row["보급_접근성"]=g["보급_접근성"].min()
        row["버스_접근성"]=g["버스_접근성"].min()
        row["식음보급_접근성"]=g["식음보급_접근성"].min()
        agg_rows.append(row)
    section_access=pd.DataFrame(agg_rows)
    shelter=pd.read_csv(inputs_dir/"backpacking_support_reviewed.csv")
    transport=pd.read_csv(inputs_dir/"transport_verification_reviewed.csv")
    region=pd.read_csv(output_dir/"08_region_tourism_summary.csv")
    region_index=dict(zip(region["지역"],region["지역체류시장여건지수"]))
    result=route.merge(section_access,on="구간번호",how="left").merge(shelter,on="구간번호",how="left").merge(transport[["구간번호","2025운영형태","운행정보판정"]],on="구간번호",how="left")
    result["숙박서비스공백"] = result["체류보급필요도"]*(1-result["숙박전체_접근성"])
    result["식음보급공백"] = result["체류보급필요도"]*(1-result["식음보급_접근성"])
    result["교통위치공백"] = result["체류보급필요도"]*(1-result["버스_접근성"])
    # 야영은 핵심 우선순위에서 제외하고 보조정보로만 보존
    result["등록야영장공백_보조"] = result["체류보급필요도"]*(1-result["야영장_접근성"])
    result["지역체류시장여건지수_보조"] = result["시군구"].astype(str).apply(lambda x: np.nanmean([region_index.get(k,np.nan) for k in region_index if k.replace('군','') in x or k.replace('시','') in x]))
    gap_cols=["숙박서비스공백","식음보급공백","교통위치공백"]
    result["최대공백점수"] = result[gap_cols].max(axis=1)
    result["가장큰공백"] = result[gap_cols].idxmax(axis=1).map({"숙박서비스공백":"숙박","식음보급공백":"식음·보급","교통위치공백":"교통"})
    result["고공백기능수"]=(result[gap_cols]>=30).sum(axis=1)
    def typology(r):
        if r["최대공백점수"] < 20: return "기본관리·기존자원연계형"
        if r["가장큰공백"]=="숙박": return "상업숙박·마을서비스 전환형"
        if r["가장큰공백"]=="교통" and r["2025운영형태"]=="자율트레킹": return "교통회수 추가확인 후보형"
        return "보급지원형"
    result["추천운영유형"] = result.apply(typology,axis=1)
    # 51은 식음·보급이 최대이고 교통은 추가확인 후보라는 해석을 유지
    result.loc[result["구간번호"].eq(51),"추천운영유형"]="보급지원형"
    result["교통해석상태"] = result["운행정보판정"]
    # 동일 공백점수는 구간번호 오름차순으로 정렬해 0점 구간의 순위를 과도하게 해석하지 않도록 한다.
    result=result.sort_values(["최대공백점수","구간번호"],ascending=[False,True]).reset_index(drop=True)
    result["보완우선순위"]=np.arange(1,len(result)+1)
    result.to_csv(output_dir/"12_section_gap_scores_final.csv",index=False,encoding="utf-8-sig")
    result.to_csv(output_dir/"section_operation_model_final.csv",index=False,encoding="utf-8-sig")
    priority_cols=["보완우선순위","구간번호","시작점명","종료점명","시군구","공식거리_km","공식소요시간_hr","공식난이도_대표값","체류보급필요도","숙박전체_접근성","식음보급_접근성","버스_접근성","숙박서비스공백","식음보급공백","교통위치공백","공식백패킹기반","추천운영유형","가장큰공백","최대공백점수","2025운영형태","교통해석상태"]
    result[priority_cols].to_csv(output_dir/"14_priority_table_final.csv",index=False,encoding="utf-8-sig")
    shelter.to_csv(output_dir/"13_official_backpacking_support_final.csv",index=False,encoding="utf-8-sig")
    transport.to_csv(output_dir/"16_transport_verification.csv",index=False,encoding="utf-8-sig")
    # 난이도 민감도: 보수 필요도로 동일 공백 재계산
    sens=result[["구간번호","체류보급필요도","체류보급필요도_보수","숙박전체_접근성","식음보급_접근성","버스_접근성"]].copy()
    for prefix,need in [("대표값","체류보급필요도"),("보수값","체류보급필요도_보수")]:
        s=np.maximum.reduce([sens[need]*(1-sens[c]) for c in ["숙박전체_접근성","식음보급_접근성","버스_접근성"]])
        sens[prefix+"_최대공백"]=s
        sens[prefix+"_순위"]=pd.Series(s).rank(method="min",ascending=False).astype(int)
    sens.to_csv(output_dir/"18_priority_sensitivity.csv",index=False,encoding="utf-8-sig")


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--raw-root",type=Path,required=True); p.add_argument("--inputs-dir",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args(); run(a.raw_root,a.inputs_dir,a.output_dir)

