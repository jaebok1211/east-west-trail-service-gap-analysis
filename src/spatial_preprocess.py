from __future__ import annotations

import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

from common import find_file, haversine_km, normalize_key, read_csv_robust

TARGET_CITIES = {"태안군", "서산시", "당진시", "예산군", "홍성군", "봉화군", "울진군"}


def active_only(df: pd.DataFrame) -> pd.DataFrame:
    state = df.get("영업상태명", pd.Series("", index=df.index)).astype(str)
    detail = df.get("상세영업상태명", pd.Series("", index=df.index)).astype(str)
    active = state.str.contains("영업/정상|정상", na=False) | detail.str.fullmatch("정상", na=False)
    return df.loc[active].copy()


def transform_culture(df: pd.DataFrame, facility_type: str) -> pd.DataFrame:
    df = active_only(df)
    address = df.get("도로명주소", pd.Series(index=df.index, dtype=object)).fillna(df.get("지번주소", ""))
    x = pd.to_numeric(df.get("좌표정보(X)"), errors="coerce")
    y = pd.to_numeric(df.get("좌표정보(Y)"), errors="coerce")
    valid = x.notna() & y.notna()
    df = df.loc[valid].copy(); x=x.loc[valid]; y=y.loc[valid]
    transformer = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x.to_numpy(), y.to_numpy())
    out = pd.DataFrame({
        "시설유형": facility_type,
        "시설명": df["사업장명"].astype(str).to_numpy(),
        "주소": address.loc[valid].astype(str).to_numpy(),
        "lon": lon, "lat": lat,
    })
    out = out[out["lon"].between(124,132) & out["lat"].between(33,39)].copy()
    out["name_key"] = out["시설명"].map(normalize_key)
    out["addr_key"] = out["주소"].map(normalize_key)
    return out.drop_duplicates(["시설유형","name_key","addr_key"]).reset_index(drop=True)


def load_shops(zip_path: Path) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    usecols = ["상호명","상권업종대분류명","상권업종중분류명","상권업종소분류명","시군구명","지번주소","도로명주소","경도","위도"]
    with zipfile.ZipFile(zip_path) as z:
        relevant=[n for n in z.namelist() if ("충남" in unicodedata.normalize("NFC",n) or "경북" in unicodedata.normalize("NFC",n)) and n.endswith(".csv")]
        if not relevant:
            raise FileNotFoundError("상가정보 ZIP에서 충남·경북 CSV를 찾지 못했습니다.")
        for name in relevant:
            with z.open(name) as handle:
                for chunk in pd.read_csv(handle,encoding="utf-8-sig",usecols=usecols,chunksize=100_000,low_memory=False):
                    chunk=chunk[chunk["시군구명"].isin(TARGET_CITIES)].copy()
                    if not chunk.empty: chunks.append(chunk)
    shops=pd.concat(chunks,ignore_index=True)
    address=shops["도로명주소"].fillna(shops["지번주소"])
    base=pd.DataFrame({
        "시설명":shops["상호명"].astype(str),"주소":address.astype(str),
        "lon":pd.to_numeric(shops["경도"],errors="coerce"),"lat":pd.to_numeric(shops["위도"],errors="coerce"),
        "대분류":shops["상권업종대분류명"].astype(str),"중분류":shops["상권업종중분류명"].astype(str),"소분류":shops["상권업종소분류명"].astype(str),
    }).dropna(subset=["lon","lat"])
    # 원자료 후보군: 식음은 음식 대분류, 보급은 실제 보행 중 구매 가능한 소매·카페 범주.
    food=base[base["대분류"].eq("음식")].copy(); food["시설유형"]="식음"
    supply_mask=(base["소분류"].str.contains("편의점|슈퍼마켓|식료품|제과|빵|커피|음료",na=False)
                 | base["중분류"].str.contains("종합 소매|식료품 소매|비알코올",na=False))
    supply=base[supply_mask].copy(); supply["시설유형"]="보급"
    out=pd.concat([food,supply],ignore_index=True)
    out["name_key"]=out["시설명"].map(normalize_key); out["addr_key"]=out["주소"].map(normalize_key)
    return out[["시설유형","시설명","주소","lon","lat","name_key","addr_key"]].drop_duplicates(["시설유형","name_key","addr_key"])


def load_bus(path: Path) -> pd.DataFrame:
    df=read_csv_robust(path)
    out=pd.DataFrame({"시설유형":"버스","시설명":df["정류장명"].astype(str),"주소":df["도시명"].astype(str),
                      "lon":pd.to_numeric(df["경도"],errors="coerce"),"lat":pd.to_numeric(df["위도"],errors="coerce")}).dropna(subset=["lon","lat"])
    out["name_key"]=out["시설명"].map(normalize_key); out["addr_key"]=out["주소"].map(normalize_key)
    return out.drop_duplicates(["시설유형","name_key","lon","lat"])


def nearest_stats(endpoint: pd.Series, points: pd.DataFrame) -> tuple[int,int,float]:
    if points.empty: return 0,0,float("nan")
    d=haversine_km(endpoint["lon"],endpoint["lat"],points["lon"].to_numpy(),points["lat"].to_numpy())
    return int((d<=1).sum()),int((d<=3).sum()),float(d.min())


def access_grade_presence(n1: float,n3: float) -> float:
    return 1.0 if n1>0 else (0.5 if n3>0 else 0.0)


def access_grade_food(n1: float,n3: float) -> float:
    if n1>=3: return 1.0
    if n1>=1: return 0.75
    if n3>=3: return 0.5
    if n3>=1: return 0.25
    return 0.0


def build_endpoints(route: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for _,r in route.iterrows():
        rows.append({"구간번호":int(r["구간번호"]),"지점":"시작","지점명":r["시작점명"],"lon":r["시작경도"],"lat":r["시작위도"]})
        rows.append({"구간번호":int(r["구간번호"]),"지점":"종료","지점명":r["종료점명"],"lon":r["종료경도"],"lat":r["종료위도"]})
    return pd.DataFrame(rows)


def join_reviewed_points(reviewed: pd.DataFrame, facilities: pd.DataFrame) -> pd.DataFrame:
    left=reviewed.copy().reset_index(names="review_id")
    left["name_key"]=left["시설명"].map(normalize_key); left["addr_key_review"]=left["주소"].map(normalize_key)
    expanded=[]
    for _,r in left.iterrows():
        cats=[str(r["시설유형"])]
        if str(r["시설유형"])=="숙박전체": cats=["농어촌민박","일반숙박"]
        for cat in cats:
            x=r.to_dict(); x["match_type"]=cat; expanded.append(x)
    exp=pd.DataFrame(expanded)
    fac=facilities.rename(columns={"시설유형":"match_type","주소":"주소_raw","시설명":"시설명_raw"})
    merged=exp.merge(fac[["match_type","name_key","addr_key","주소_raw","시설명_raw","lon","lat"]],on=["match_type","name_key"],how="left")
    merged["addr_exact"]=merged["addr_key_review"].ne("") & merged["addr_key_review"].eq(merged["addr_key"])
    merged["has_coord"]=merged["lon"].notna()
    merged=merged.sort_values(["review_id","addr_exact","has_coord"],ascending=[True,False,False]).drop_duplicates("review_id")
    merged=merged[merged["lon"].notna()].copy(); merged["좌표매칭"]=np.where(merged["addr_exact"],"시설명+주소","시설명")
    return merged[list(reviewed.columns)+["lon","lat","좌표매칭"]]


def run(raw_root: Path, inputs_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True,exist_ok=True)
    rural_path=find_file(raw_root,["문화","농어촌민박업"],".csv")
    lodging_path=find_file(raw_root,["문화","숙박업"],".csv")
    camp_path=find_file(raw_root,["문화","일반야영장업"],".csv")
    bus_path=find_file(raw_root,["전국","버스정류장","위치정보"],".csv")
    shop_zip=find_file(raw_root,["필독","파일열람방법"],".zip")

    cache_path=output_dir/"facility_points_clean.csv"
    if cache_path.exists():
        facilities=pd.read_csv(cache_path,low_memory=False)
    else:
        rural=transform_culture(read_csv_robust(rural_path),"농어촌민박")
        lodging=transform_culture(read_csv_robust(lodging_path),"일반숙박")
        camp=transform_culture(read_csv_robust(camp_path),"야영장")
        shops=load_shops(shop_zip); bus=load_bus(bus_path)
        facilities=pd.concat([rural,lodging,camp,shops,bus],ignore_index=True)
        facilities.to_csv(cache_path,index=False,encoding="utf-8-sig")

    route=pd.read_csv(inputs_dir/"route_metadata_official.csv")
    endpoints=build_endpoints(route)
    raw_rows=[]
    for _,ep in endpoints.iterrows():
        row=ep.to_dict()
        for category in ["농어촌민박","일반숙박","야영장","식음","보급","버스"]:
            n1,n3,near=nearest_stats(ep,facilities[facilities["시설유형"].eq(category)])
            row[f"{category}_1km수_후보"]=n1; row[f"{category}_3km수_후보"]=n3; row[f"{category}_최근접km_후보"]=near
        raw_rows.append(row)
    raw=pd.DataFrame(raw_rows)
    raw.to_csv(output_dir/"endpoint_accessibility_raw_candidate.csv",index=False,encoding="utf-8-sig")

    final=endpoints.copy()
    for base in ["농어촌민박","일반숙박","야영장","식음","보급","버스"]:
        for metric in ["1km수","3km수","최근접km"]:
            final[f"{base}_{metric}"]=raw[f"{base}_{metric}_후보"]
    # 음식점·보급시설은 상위구간 시설명과 업종을 수작업 재검토한 고정 검증표를 적용한다.
    reviewed=pd.read_csv(inputs_dir/"endpoint_food_supply_reviewed.csv")
    final=final.drop(columns=[c for c in final.columns if c.startswith("식음_") or c.startswith("보급_")]).merge(reviewed,on=["구간번호","지점","지점명"],how="left")
    final["숙박전체_1km수"]=final["농어촌민박_1km수"]+final["일반숙박_1km수"]
    final["숙박전체_3km수"]=final["농어촌민박_3km수"]+final["일반숙박_3km수"]
    final["숙박전체_최근접km"]=final[["농어촌민박_최근접km","일반숙박_최근접km"]].min(axis=1)
    for base in ["농어촌민박","일반숙박","숙박전체","야영장","보급","버스"]:
        final[f"{base}_접근성"]=[access_grade_presence(a,b) for a,b in zip(final[f"{base}_1km수"],final[f"{base}_3km수"])]
    final["식음_접근성"]=[access_grade_food(a,b) for a,b in zip(final["식음_1km수"],final["식음_3km수"])]
    final["식음보급_접근성"]=final[["식음_접근성","보급_접근성"]].min(axis=1)
    columns=["구간번호","지점","지점명","lon","lat",
             "농어촌민박_1km수","농어촌민박_3km수","농어촌민박_최근접km",
             "일반숙박_1km수","일반숙박_3km수","일반숙박_최근접km",
             "숙박전체_1km수","숙박전체_3km수","숙박전체_최근접km",
             "야영장_1km수","야영장_3km수","야영장_최근접km",
             "식음_1km수","식음_3km수","식음_최근접km",
             "보급_1km수","보급_3km수","보급_최근접km",
             "버스_1km수","버스_3km수","버스_최근접km",
             "농어촌민박_접근성","일반숙박_접근성","숙박전체_접근성","야영장_접근성","보급_접근성","버스_접근성","식음_접근성","식음보급_접근성"]
    final[columns].to_csv(output_dir/"11_endpoint_accessibility_final.csv",index=False,encoding="utf-8-sig")

    reviewed_named=pd.read_csv(inputs_dir/"named_facility_validation_reviewed.csv")
    reviewed_named.to_csv(output_dir/"15_top_endpoint_named_facility_validation.csv",index=False,encoding="utf-8-sig")
    matched=join_reviewed_points(reviewed_named,facilities)
    matched.to_csv(output_dir/"facility_points_for_maps.csv",index=False,encoding="utf-8-sig")


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--raw-root",type=Path,required=True); p.add_argument("--inputs-dir",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args(); run(a.raw_root,a.inputs_dir,a.output_dir)

