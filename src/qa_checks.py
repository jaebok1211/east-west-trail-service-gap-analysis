from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd


def pdf_pages(path: Path) -> int:
    result = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError("PDF 페이지 수를 읽지 못했습니다.")


def run(outputs: Path, figures: Path, report: Path, qa_dir: Path) -> None:
    qa_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, object]] = []

    required_outputs = [
        "01_survey_overall.csv", "03_logistic_odds_ratios.csv", "03b_logistic_diagnostics.csv",
        "08_region_tourism_summary.csv", "10_route_metadata_final.csv", "11_endpoint_accessibility_final.csv",
        "12_section_gap_scores_final.csv", "14_priority_table_final.csv", "18_priority_sensitivity.csv",
        "accessibility_rule_check.csv", "facility_points_for_maps.csv",
    ]
    for name in required_outputs:
        checks.append({"검사항목": f"산출물 존재: {name}", "통과": (outputs / name).exists(), "세부": ""})

    required_figures = [
        "figure1_activity_comparison.png", "figure2_region_context.png", "figure3_overall_priority_map.png",
        "figure4_top4_detail_maps.png", "figure5_need_gap_typology.png",
    ]
    for name in required_figures:
        checks.append({"검사항목": f"시각화 존재: {name}", "통과": (figures / name).exists(), "세부": ""})

    priority = pd.read_csv(outputs / "14_priority_table_final.csv")
    top7 = priority.sort_values("보완우선순위").head(7)["구간번호"].astype(int).tolist()
    checks.append({"검사항목": "상위 7개 우선순위", "통과": top7 == [54, 53, 51, 12, 47, 52, 55], "세부": str(top7)})

    ep = pd.read_csv(outputs / "11_endpoint_accessibility_final.csv")
    for sec, point, food_near, supply_near in [(54, "시작", 4.93, .07), (53, "종료", 4.84, .17)]:
        row = ep[(ep["구간번호"].eq(sec)) & (ep["지점"].eq(point))].iloc[0]
        ok = row["식음_3km수"] == 0 and row["보급_1km수"] >= 1 and abs(row["식음_최근접km"] - food_near) < .1 and abs(row["보급_최근접km"] - supply_near) < .1
        checks.append({"검사항목": f"{sec}구간 식사·보급 분리", "통과": bool(ok), "세부": f"식음 {row['식음_최근접km']:.2f}km / 보급 {row['보급_최근접km']:.2f}km"})

    row51 = priority[priority["구간번호"].eq(51)].iloc[0]
    checks.append({"검사항목": "51구간 교통 후보표현", "통과": any(k in str(row51["교통해석상태"]) for k in ["추가확인","검증후보"]), "세부": str(row51["교통해석상태"])})

    access = pd.read_csv(outputs / "accessibility_rule_check.csv")
    max_diff = access["최대절대차"].max()
    checks.append({"검사항목": "접근성 등급 재계산 일치", "통과": max_diff < 1e-12, "세부": f"최대차={max_diff}"})

    pdf = report / "동서트레일_최종보고서_10p.pdf"
    pages = pdf_pages(pdf) if pdf.exists() else -1
    checks.append({"검사항목": "보고서 PDF 10쪽", "통과": pages == 10, "세부": f"{pages}쪽"})

    df = pd.DataFrame(checks)
    df.to_csv(qa_dir / "qa_checks.csv", index=False, encoding="utf-8-sig")
    summary = {"통과": int(df["통과"].sum()), "전체": len(df), "실패": df.loc[~df["통과"], "검사항목"].tolist()}
    (qa_dir / "qa_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not df["통과"].all():
        raise AssertionError("QA 실패: " + ", ".join(summary["실패"]))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--outputs", type=Path, required=True)
    p.add_argument("--figures", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--qa-dir", type=Path, required=True)
    a = p.parse_args()
    run(a.outputs, a.figures, a.report, a.qa_dir)

