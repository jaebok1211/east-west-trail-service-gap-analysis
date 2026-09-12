from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


def minmax(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    span = values.max() - values.min()
    if not np.isfinite(span) or span == 0:
        return pd.Series(0.0, index=values.index)
    return (values - values.min()) / span


def run(inputs_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    monthly = pd.read_csv(inputs_dir / "region_tourism_monthly_clean.csv")
    shares = pd.read_csv(inputs_dir / "tourism_category_shares.csv")
    required = ["기준연월", "방문자수", "전년동월방문자수", "방문자수증감률", "순 방문자수", "숙박자 비율", "평균 숙박일수", "체류시간(분)", "외지인관광소비(천원)", "지역"]
    missing = [c for c in required if c not in monthly.columns]
    if missing:
        raise KeyError(f"관광 월별 통합자료 필수 열 누락: {missing}")
    monthly.to_csv(output_dir / "09_region_tourism_monthly.csv", index=False, encoding="utf-8-sig")
    summary = monthly.groupby("지역", as_index=False).agg(
        기간=("기준연월", lambda s: f"{str(int(s.min()))[:4]}-{str(int(s.min()))[4:]}~{str(int(s.max()))[:4]}-{str(int(s.max()))[4:]}"),
        방문자수_연인원_합계=("방문자수", "sum"),
        순방문자수_월합계=("순 방문자수", "sum"),
        숙박방문자비율_월평균=("숙박자 비율", "mean"),
        평균숙박일수_월평균=("평균 숙박일수", "mean"),
        평균체류시간_월평균=("체류시간(분)", "mean"),
        외지인관광소비_합계=("외지인관광소비(천원)", "sum"),
    )
    # 전년동기 증감률은 월별 방문자수를 가중치로 둔 평균
    weighted_growth = monthly.groupby("지역").apply(
        lambda g: np.average(g["방문자수증감률"], weights=g["전년동월방문자수"], axis=0),
        include_groups=False,
    )
    summary["방문자수_전년동기증감률_가중평균(%)"] = summary["지역"].map(weighted_growth)
    summary = summary.merge(shares, on="지역", how="left")
    summary["외지인숙박업소비_합계(천원)"] = summary["외지인관광소비_합계"] * summary["외지인숙박업비중"]
    summary["외지인식음료업소비_합계(천원)"] = summary["외지인관광소비_합계"] * summary["외지인식음료업비중"]
    metric_cols = ["방문자수_연인원_합계", "숙박방문자비율_월평균", "평균체류시간_월평균", "외지인관광소비_합계"]
    for col in metric_cols:
        summary[col + "_정규화"] = minmax(summary[col])
    summary["지역체류시장여건지수"] = summary[[c + "_정규화" for c in metric_cols]].mean(axis=1) * 100
    rename = {
        "숙박방문자비율_월평균": "숙박방문자비율_월평균(%)",
        "평균체류시간_월평균": "평균체류시간_월평균(분)",
        "외지인관광소비_합계": "외지인관광소비_합계(천원)",
        "방문자수_연인원_합계_정규화": "방문자수_연인원_합계_정규화",
        "숙박방문자비율_월평균_정규화": "숙박방문자비율_월평균(%)_정규화",
        "평균체류시간_월평균_정규화": "평균체류시간_월평균(분)_정규화",
        "외지인관광소비_합계_정규화": "외지인관광소비_합계(천원)_정규화",
    }
    summary = summary.rename(columns=rename)
    cols = [
        "지역", "기간", "방문자수_연인원_합계", "순방문자수_월합계", "숙박방문자비율_월평균(%)", "평균숙박일수_월평균", "평균체류시간_월평균(분)",
        "외지인관광소비_합계(천원)", "외지인숙박업소비_합계(천원)", "외지인식음료업소비_합계(천원)", "방문자수_전년동기증감률_가중평균(%)",
        "방문자수_연인원_합계_정규화", "숙박방문자비율_월평균(%)_정규화", "평균체류시간_월평균(분)_정규화", "외지인관광소비_합계(천원)_정규화", "지역체류시장여건지수",
    ]
    summary[cols].to_csv(output_dir / "08_region_tourism_summary.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.inputs_dir, args.output_dir)

