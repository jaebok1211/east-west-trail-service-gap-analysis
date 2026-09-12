from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.metrics import roc_auc_score

from common import find_file, read_csv_robust, weighted_mean, weighted_median

DAY_TYPE = "문1. 지난해 1년간 경험한 산림휴양·복지활동 유형_2"
OVERNIGHT_TYPE = "문1. 지난해 1년간 경험한 산림휴양·복지활동 유형_3"
WEIGHT = "가중치"


def load_codebook(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[int, str]]]:
    items = pd.read_excel(path, sheet_name="항목정보", header=2)
    codes = pd.read_excel(path, sheet_name="코드정보", header=1)
    items = items.dropna(subset=["항목명"]).copy()
    mappings: dict[str, dict[int, str]] = {}
    for _, row in items.iterrows():
        code_no = row.get("코드번호")
        if pd.isna(code_no):
            continue
        subset = codes[codes["코드번호"].eq(code_no)]
        mapping: dict[int, str] = {}
        for _, c in subset.iterrows():
            if pd.notna(c.get("코드")) and pd.notna(c.get("코드의미 및 단위")):
                try:
                    mapping[int(float(c["코드"]))] = str(c["코드의미 및 단위"]).strip()
                except Exception:
                    continue
        if mapping:
            mappings[str(row["항목명"]).strip()] = mapping
    return items, codes, mappings


def activity_mapping(mappings: dict[str, dict[int, str]]) -> dict[int, str]:
    key = "문10-1. 당일형 산림휴양·복지활동 경험 종류_1"
    if key not in mappings:
        raise KeyError(f"활동 코드 매핑이 없습니다: {key}")
    return mappings[key]


def build_activity_records(df: pd.DataFrame, prefix: str, kind: str, mappings: dict[str, dict[int, str]]) -> pd.DataFrame:
    item_prefix = "문11" if kind == "당일형" else "문12"
    rows: list[pd.DataFrame] = []
    for idx in range(1, 16):
        reason_col = f"{item_prefix}-4. 지역 선택 이유_{idx}"
        companion_col = f"{item_prefix}-6. 동반유형_{idx}"
        purpose_col = f"{item_prefix}-7. 방문목적_{idx}"
        spend_col = f"{item_prefix}-8. 1회 기준 1인 평균 소비금액_{idx}"
        required = [reason_col, companion_col, purpose_col, spend_col]
        if not all(c in df.columns for c in required):
            continue
        temp = df[[WEIGHT] + required].copy()
        temp = temp[temp[spend_col].notna() | temp[reason_col].notna() | temp[companion_col].notna() | temp[purpose_col].notna()]
        if temp.empty:
            continue
        temp = temp.rename(columns={reason_col: "지역선택이유코드", companion_col: "동반유형코드", purpose_col: "방문목적코드", spend_col: "소비금액_만원", WEIGHT: "가중치"})
        temp["유형"] = kind
        temp["기록번호"] = idx
        rows.append(temp)
    if not rows:
        return pd.DataFrame(columns=["가중치", "지역선택이유코드", "동반유형코드", "방문목적코드", "소비금액_만원", "유형", "기록번호"])
    return pd.concat(rows, ignore_index=True)


def run(raw_root: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = find_file(raw_root, ["2025_총괄_20260730_40682"], ".csv")
    codebook = find_file(raw_root, ["2025년_산림휴양복지활동조사_파일설계서"], ".xlsx")
    df = read_csv_robust(raw_csv)
    _, _, mappings = load_codebook(codebook)

    for col in (DAY_TYPE, OVERNIGHT_TYPE, WEIGHT):
        if col not in df.columns:
            raise KeyError(col)
    weights = pd.to_numeric(df[WEIGHT], errors="coerce")
    day = df[DAY_TYPE].notna()
    overnight = df[OVERNIGHT_TYPE].notna()

    overall_rows = [
        ["전체 응답자", len(df), 100.0],
        ["당일형만 경험", int((day & ~overnight).sum()), weighted_mean((day & ~overnight).astype(int), weights) * 100],
        ["숙박형 포함 경험", int(overnight.sum()), weighted_mean(overnight.astype(int), weights) * 100],
        ["당일·숙박 모두 경험", int((day & overnight).sum()), weighted_mean((day & overnight).astype(int), weights) * 100],
        ["당일형 경험 전체", int(day.sum()), weighted_mean(day.astype(int), weights) * 100],
        ["숙박형 경험 전체", int(overnight.sum()), weighted_mean(overnight.astype(int), weights) * 100],
    ]
    pd.DataFrame(overall_rows, columns=["구분", "표본수", "가중비율(%)"]).to_csv(output_dir / "01_survey_overall.csv", index=False, encoding="utf-8-sig")

    ana = df[day | overnight].copy()
    ana["숙박형포함"] = ana[OVERNIGHT_TYPE].notna().astype(int)
    ana["가중치_정규화"] = pd.to_numeric(ana[WEIGHT], errors="coerce")
    ana["가중치_정규화"] /= ana["가중치_정규화"].mean()

    maps = {
        "성별": ("성별", {1: "남", 2: "여"}),
        "연령": ("연령별", {1: "15-19세", 2: "20-29세", 3: "30-39세", 4: "40-49세", 5: "50-59세", 6: "60-69세", 7: "70세 이상"}),
        "가구원수": ("가구원 현황", {1: "1인 가구", 2: "2인 가구", 3: "3인 가구", 4: "4인 이상 가구"}),
        "혼인상태": ("혼인상태", {1: "미혼", 2: "기혼", 3: "사별/이혼/기타"}),
        "지역규모": ("지역규모", {1: "대도시", 2: "중소도시", 3: "읍면지역"}),
        "학력": ("학력별", {1: "초졸이하", 2: "중졸", 3: "고졸", 4: "대졸이상"}),
    }
    demo_rows: list[list[object]] = []
    for label, (col, mapping) in maps.items():
        ana[label] = pd.to_numeric(ana[col], errors="coerce").map(mapping)
        for category in mapping.values():
            group = ana[ana[label].eq(category)]
            if group.empty:
                continue
            rate = weighted_mean(group["숙박형포함"], group["가중치_정규화"]) * 100
            share = group["가중치_정규화"].sum() / ana["가중치_정규화"].sum() * 100
            demo_rows.append([label, category, len(group), int(group["숙박형포함"].sum()), rate, share])
    pd.DataFrame(demo_rows, columns=["변수", "범주", "표본수", "숙박형포함_표본수", "숙박형포함_가중비율(%)", "가중표본비중(%)"]).to_csv(output_dir / "02_survey_demographic_rates.csv", index=False, encoding="utf-8-sig")

    ana = ana.rename(columns={"성별": "gender", "연령": "age", "가구원수": "hh", "혼인상태": "marital", "지역규모": "region_size", "학력": "edu"})
    formula = (
        "숙박형포함 ~ C(gender, Treatment(reference='여')) + "
        "C(age, Treatment(reference='50-59세')) + "
        "C(hh, Treatment(reference='1인 가구')) + "
        "C(marital, Treatment(reference='기혼')) + "
        "C(region_size, Treatment(reference='대도시')) + "
        "C(edu, Treatment(reference='고졸'))"
    )
    model = smf.glm(formula, data=ana, family=sm.families.Binomial(), freq_weights=ana["가중치_정규화"]).fit(cov_type="HC1")
    ci = model.conf_int()
    ref = {"gender": "여", "age": "50-59세", "hh": "1인 가구", "marital": "기혼", "region_size": "대도시", "edu": "고졸"}
    label = {"gender": "성별", "age": "연령", "hh": "가구원수", "marital": "혼인상태", "region_size": "지역규모", "edu": "학력"}
    result_rows: list[list[object]] = []
    for term in model.params.index:
        if term == "Intercept":
            name, reference = "절편", np.nan
        else:
            m = re.match(r"C\(([^,]+),.*\)\[T\.(.*)\]", term)
            if not m:
                name, reference = term, np.nan
            else:
                var, category = m.group(1), m.group(2)
                name, reference = f"{label[var]}: {category}", ref[var]
        result_rows.append([name, float(np.exp(model.params[term])), float(np.exp(ci.loc[term, 0])), float(np.exp(ci.loc[term, 1])), float(model.pvalues[term]), reference])
    pd.DataFrame(result_rows, columns=["변수명", "오즈비", "95%CI_하한", "95%CI_상한", "p값", "기준범주"]).to_csv(output_dir / "03_logistic_odds_ratios.csv", index=False, encoding="utf-8-sig")
    pred = model.predict(ana)
    diagnostics = pd.DataFrame([{
        "모형표본수": int(model.nobs),
        "AIC": float(model.aic),
        "McFadden_pseudo_R2": float(1 - model.llf / model.llnull),
        "AUC": float(roc_auc_score(ana["숙박형포함"], pred, sample_weight=ana["가중치_정규화"])),
        "가중치적용": "평균 1 정규화 freq_weights",
        "표준오차": "HC1 강건표준오차",
    }])
    diagnostics.to_csv(output_dir / "03b_logistic_diagnostics.csv", index=False, encoding="utf-8-sig")

    act_map = activity_mapping(mappings)
    activity_rows: list[list[object]] = []
    for code, act_name in act_map.items():
        day_col = f"문10-1. 당일형 산림휴양·복지활동 경험 종류_{code}"
        ov_col = f"문10-2. 숙박형 산림휴양·복지활동 경험 종류_{code}"
        day_group = df[day]
        ov_group = df[overnight]
        day_flag = day_group[day_col].notna().astype(int) if day_col in df else pd.Series(0, index=day_group.index)
        ov_flag = ov_group[ov_col].notna().astype(int) if ov_col in df else pd.Series(0, index=ov_group.index)
        day_rate = weighted_mean(day_flag, day_group[WEIGHT]) * 100
        ov_rate = weighted_mean(ov_flag, ov_group[WEIGHT]) * 100
        activity_rows.append([code, act_name, day_rate, ov_rate, ov_rate - day_rate, int(day_flag.sum()), int(ov_flag.sum())])
    pd.DataFrame(activity_rows, columns=["활동코드", "활동명", "당일형참여자_경험비율(%)", "숙박형참여자_경험비율(%)", "숙박-당일_차이(%p)", "당일형_표본수", "숙박형_표본수"]).to_csv(output_dir / "04_activity_prevalence_day_vs_overnight.csv", index=False, encoding="utf-8-sig")

    records = pd.concat([
        build_activity_records(df, "문11", "당일형", mappings),
        build_activity_records(df, "문12", "숙박형", mappings),
    ], ignore_index=True)
    reason_map = mappings["문11-4. 지역 선택 이유_1"]
    companion_map = mappings["문11-6. 동반유형_1"]
    purpose_map = mappings["문11-7. 방문목적_1"]
    characteristics: list[list[object]] = []
    for kind, group in records.groupby("유형", sort=False):
        for item, code_col, mapping in [
            ("지역선택이유", "지역선택이유코드", reason_map),
            ("동반유형", "동반유형코드", companion_map),
            ("방문목적", "방문목적코드", purpose_map),
        ]:
            valid = group[group[code_col].notna()].copy()
            total_weight = valid["가중치"].sum()
            for code, category in mapping.items():
                sub = valid[pd.to_numeric(valid[code_col], errors="coerce").eq(code)]
                # 코드북의 전체 범주를 보존한다. 관측이 없으면 0건·0%로 기록한다.
                characteristics.append([kind, item, code, category, len(sub), 0.0 if sub.empty else sub["가중치"].sum() / total_weight * 100])
    pd.DataFrame(characteristics, columns=["유형", "항목", "코드", "범주", "기록수", "가중비율(%)"]).to_csv(output_dir / "05_activity_record_characteristics.csv", index=False, encoding="utf-8-sig")

    consumption_rows: list[list[object]] = []
    for kind, group in records.groupby("유형", sort=False):
        spend = pd.to_numeric(group["소비금액_만원"], errors="coerce")
        mask = spend.notna()
        consumption_rows.append([kind, int(mask.sum()), weighted_mean(spend[mask], group.loc[mask, "가중치"]), weighted_median(spend[mask], group.loc[mask, "가중치"]), float(spend[mask].mean())])
    pd.DataFrame(consumption_rows, columns=["유형", "기록수", "가중평균_만원", "가중중앙값_만원", "비가중평균_만원"]).to_csv(output_dir / "06_consumption_summary.csv", index=False, encoding="utf-8-sig")

    lodging_col = "문13. 숙박형 산림휴양·복지활동 숙박시설"
    lodging_map = mappings[lodging_col]
    valid = df[df[lodging_col].notna()].copy()
    total_weight = valid[WEIGHT].sum()
    lodging_rows: list[list[object]] = []
    for code, name in lodging_map.items():
        sub = valid[pd.to_numeric(valid[lodging_col], errors="coerce").eq(code)]
        if sub.empty:
            continue
        lodging_rows.append([name, len(sub), sub[WEIGHT].sum() / total_weight * 100])
    pd.DataFrame(lodging_rows, columns=["숙박시설", "표본수", "가중비율(%)"]).sort_values("가중비율(%)", ascending=False).to_csv(output_dir / "07_overnight_lodging_types.csv", index=False, encoding="utf-8-sig")

    records.to_csv(output_dir / "survey_activity_records_long.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.raw_root, args.output_dir)

