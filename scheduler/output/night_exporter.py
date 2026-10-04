# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import pandas as pd

from scheduler.output.excel_writer import create_excel_writer


def export_checkin_sheet(writer, solver, days, male_heads, female_heads, checkin_m, checkin_f):
    rows = []
    for d in days:
        male = ""
        female = ""
        for tch in male_heads:
            if solver.Value(checkin_m[(tch, d)]) == 1:
                male = tch
                break
        for tch in female_heads:
            if solver.Value(checkin_f[(tch, d)]) == 1:
                female = tch
                break
        rows.append({"日期": d, "男晚查寝": male, "女晚查寝": female})
    df = pd.DataFrame(rows, columns=["日期", "男晚查寝", "女晚查寝"])
    df.to_excel(writer, sheet_name="晚查寝安排", index=False)


def export_result_xlsx(out_path, solver, vars, classes, cst, days, periods, male_heads, female_heads):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    y = vars["y"]
    rows = []
    for cls in classes:
        row = {"班级": cls}
        for d in days:
            for pi, p in enumerate(periods):
                col = d if pi == 0 else f"{d}.1"
                subj_list = [s for (c, s) in cst.keys() if c == cls]
                hit = ""
                for subj in subj_list:
                    if solver.Value(y[(cls, subj, d, p)]) == 1:
                        hit = f"{subj}-{cst[(cls, subj)]}"
                        break
                row[col] = hit
        rows.append(row)

    cols = ["班级"]
    for d in days:
        cols += [d, f"{d}.1"]
    df_schedule = pd.DataFrame(rows, columns=cols)

    with create_excel_writer(out_path) as writer:
        df_schedule.to_excel(writer, sheet_name="排课", index=False)
        if ("checkin_m" in vars) and ("checkin_f" in vars):
            export_checkin_sheet(
                writer,
                solver,
                days,
                male_heads,
                female_heads,
                vars["checkin_m"],
                vars["checkin_f"],
            )
