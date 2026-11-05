# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set, Any

import pandas as pd

from scheduler.calendar import (
    ALL_DAYS as CANONICAL_ALL_DAYS,
    WEEKDAY_DAYS,
    WEEKEND_DAYS,
    is_weekday_day,
    is_weekend_day,
)
from scheduler.data.teacher_table_schema import (
    DEFAULT_CLASS_COLUMN,
    DEFAULT_HEAD_COLUMN,
    DEFAULT_HEAD_GENDER_COLUMN,
    normalize_teacher_table_frame,
    teacher_subject_columns,
)


# ---------------------------
# 中文常量：与你的 Excel 完全一致
# ---------------------------
SHEET_TIME_GRID = "白天时间格子"
SHEET_FIXED = "固定课位"
SHEET_HOURS = "学科白天周课时"
SHEET_SUBJECT_BANS = "学科白天禁排时段"
SHEET_OVERRIDES = "班级白天课时需求差异"

POS_SHEET = "Sheet1"  # 教师定位表.xlsx 里的 sheet 名

SHEET_TO_WEB_KEY = {
    SHEET_TIME_GRID: "time_grid",
    SHEET_FIXED: "fixed_slots",
    SHEET_HOURS: "subject_hours",
    SHEET_SUBJECT_BANS: "subject_bans",
    SHEET_OVERRIDES: "class_overrides",
}

SHEET_COLUMNS = {
    SHEET_FIXED: ["作用范围", "班级", "星期", "时段", "节次", "学科"],
    SHEET_SUBJECT_BANS: ["学科", "禁排星期", "禁排时段", "节次"],
    SHEET_OVERRIDES: ["班级", "学科", "早自习课时", "周中课时", "周末课时"],
}


DAYS_WEEKDAY = list(WEEKDAY_DAYS)
DAYS_WEEKEND = list(WEEKEND_DAYS)
ALL_DAYS = list(CANONICAL_ALL_DAYS)


# ---------------------------
# 数据结构（读完后返回这个）
# ---------------------------
@dataclass(frozen=True)
class Slot:
    day: str          # 星期一..星期日
    block: str        # 早自习/上午/下午
    period: int       # 1..4（早自习固定为1）


@dataclass
class DayInputData:
    classes: List[str]

    # (班级, 学科) -> 教师（来自教师定位表非空单元格）
    cls_subj_teacher: Dict[Tuple[str, str], str]

    # 可排时间槽（已经扣除了固定课位占用的槽位）
    available_slots: List[Slot]

    # 固定课位： (班级, Slot) -> 学科
    fixed_assign: Dict[Tuple[str, Slot], str]

    # 每班课时需求： (班级, 学科) -> (早自习, 周中, 周末)
    req_hours: Dict[Tuple[str, str], Tuple[int, int, int]]

    # 学科禁排： (学科) -> set[Slot] 或者更粗粒度的规则（这里先展开为 Slot 集合）
    subject_ban_slots: Dict[str, Set[Slot]]


# ---------------------------
# 工具函数：字符串清洗
# ---------------------------
def _norm_str(x: Any) -> str:
    if pd.isna(x):
        return ""
    s = str(x)
    # 去掉两端空白，压缩中间空白
    s = re.sub(r"\s+", " ", s.strip())
    return s


def _read_sheet(rules_xlsx_path: str, sheet_name: str, web_tables: dict[str, Any] | None = None) -> pd.DataFrame:
    day_rules = ((web_tables or {}).get("day_rules") or {}) if isinstance(web_tables, dict) else {}
    web_key = SHEET_TO_WEB_KEY.get(sheet_name)
    rows = day_rules.get(web_key) if isinstance(day_rules, dict) and web_key else None
    if isinstance(rows, list):
        if not rows:
            return pd.DataFrame(columns=SHEET_COLUMNS.get(sheet_name, []))
        return pd.DataFrame([row for row in rows if isinstance(row, dict)])
    return pd.read_excel(rules_xlsx_path, sheet_name=sheet_name)


def _read_teacher_positioning(pos_xlsx_path: str, web_tables: dict[str, Any] | None = None) -> pd.DataFrame:
    rows = web_tables.get("teacher_subjects") if isinstance(web_tables, dict) else None
    if isinstance(rows, list):
        return normalize_teacher_table_frame(pd.DataFrame([row for row in rows if isinstance(row, dict)]))
    return normalize_teacher_table_frame(pd.read_excel(pos_xlsx_path, sheet_name=POS_SHEET))


def _parse_slot_label(label: str) -> Slot:
    """
    将“白天时间格子”第一列（时段节次）解析成 Slot 的 block/period。
    你现在的值形如：早自习、早自习1、上午1、上午2、...、下午4
    """
    label = _norm_str(label)
    early = re.match(r"^早自习(\d+)?$", label)
    if early:
        return Slot(day="?", block="早自习", period=int(early.group(1) or 1))

    m = re.match(r"^(上午|下午)(\d+)$", label)
    if not m:
        raise ValueError(f"无法解析时段节次：{label}（应为 早自习 / 早自习1..N / 上午1..N / 下午1..N）")

    block = m.group(1)
    period = int(m.group(2))
    if period < 1 or period > 10:
        raise ValueError(f"节次异常：{label}")
    return Slot(day="?", block=block, period=period)


def _is_weekday(day: str) -> bool:
    return is_weekday_day(day)


def _is_weekend(day: str) -> bool:
    return is_weekend_day(day)


# ---------------------------
# 读取：白天时间格子（矩阵 -> slots）
# ---------------------------
def load_time_grid_rules(rules_xlsx_path: str, web_tables: dict[str, Any] | None = None) -> List[Slot]:
    df = _read_sheet(rules_xlsx_path, SHEET_TIME_GRID, web_tables)
    # 期望列：时段节次 + 星期一..星期日
    if "时段节次" not in df.columns:
        raise ValueError(f"[{SHEET_TIME_GRID}] 缺少列：时段节次")

    for d in ALL_DAYS:
        if d not in df.columns:
            raise ValueError(f"[{SHEET_TIME_GRID}] 缺少星期列：{d}")

    slots: List[Slot] = []
    for _, row in df.iterrows():
        base = _parse_slot_label(row["时段节次"])  # day="?"
        for day in ALL_DAYS:
            v = row[day]
            if pd.isna(v):
                continue
            try:
                vv = int(v)
            except Exception:
                raise ValueError(f"[{SHEET_TIME_GRID}] 单元格必须是0/1：{day}, {row['时段节次']}={v}")
            if vv == 1:
                slots.append(Slot(day=day, block=base.block, period=base.period))
            elif vv == 0:
                pass
            else:
                raise ValueError(f"[{SHEET_TIME_GRID}] 单元格必须是0/1：{day}, {row['时段节次']}={v}")
    return slots


# ---------------------------
# 读取：教师定位表（班级开课集合 + 任课教师）
# ---------------------------
def load_teacher_positioning(
    pos_xlsx_path: str,
    web_tables: dict[str, Any] | None = None,
    teacher_columns: dict[str, Any] | None = None,
) -> Tuple[List[str], Dict[Tuple[str, str], str]]:
    df = _read_teacher_positioning(pos_xlsx_path, web_tables)

    teacher_columns = teacher_columns if isinstance(teacher_columns, dict) else {}
    class_col = str(teacher_columns.get("class") or DEFAULT_CLASS_COLUMN).strip()
    head_col = str(teacher_columns.get("head") or DEFAULT_HEAD_COLUMN).strip()
    gender_col = str(teacher_columns.get("head_gender") or DEFAULT_HEAD_GENDER_COLUMN).strip()

    if class_col not in df.columns:
        raise ValueError(f"[教师定位表] 缺少列：{class_col}")

    subject_cols = teacher_subject_columns(
        df.columns,
        class_col=class_col,
        head_col=head_col,
        gender_col=gender_col,
    )

    classes: List[str] = []
    cls_subj_teacher: Dict[Tuple[str, str], str] = {}

    for _, row in df.iterrows():
        cls = _norm_str(row[class_col])
        if not cls:
            continue
        classes.append(cls)

        for subj in subject_cols:
            teacher = _norm_str(row.get(subj, ""))
            if teacher:  # 非空表示该班开设该学科
                cls_subj_teacher[(cls, subj)] = teacher

    classes = sorted(classes, key=lambda x: (len(x), x))  # 简单排序：1班..17班
    return classes, cls_subj_teacher


# ---------------------------
# 读取：学科白天周课时 + 班级差异覆盖
# ---------------------------
def load_subject_hours(
    rules_xlsx_path: str,
    web_tables: dict[str, Any] | None = None,
) -> Dict[str, Tuple[int, int, int]]:
    df = _read_sheet(rules_xlsx_path, SHEET_HOURS, web_tables)
    need_cols = ["学科", "早自习课时", "周中课时", "周末课时"]
    for c in need_cols:
        if c not in df.columns:
            raise ValueError(f"[{SHEET_HOURS}] 缺少列：{c}")

    subj_hours: Dict[str, Tuple[int, int, int]] = {}
    for _, r in df.iterrows():
        subj = _norm_str(r["学科"])
        if not subj:
            continue
        e = int(r["早自习课时"])
        w = int(r["周中课时"])
        we = int(r["周末课时"])
        subj_hours[subj] = (e, w, we)
    return subj_hours


def apply_class_overrides(
    rules_xlsx_path: str,
    base_req: Dict[Tuple[str, str], Tuple[int, int, int]],
    web_tables: dict[str, Any] | None = None,
) -> Dict[Tuple[str, str], Tuple[int, int, int]]:
    df = _read_sheet(rules_xlsx_path, SHEET_OVERRIDES, web_tables)
    # 允许空表
    if df.shape[0] == 0:
        return base_req

    need_cols = ["班级", "学科", "早自习课时", "周中课时", "周末课时"]
    for c in need_cols:
        if c not in df.columns:
            raise ValueError(f"[{SHEET_OVERRIDES}] 缺少列：{c}")

    req = dict(base_req)
    for _, r in df.iterrows():
        cls = _norm_str(r["班级"])
        subj = _norm_str(r["学科"])
        if not cls or not subj:
            continue
        e = int(r["早自习课时"])
        w = int(r["周中课时"])
        we = int(r["周末课时"])
        req[(cls, subj)] = (e, w, we)
    return req


# ---------------------------
# 读取：固定课位（展开到每个班）
# ---------------------------
def load_fixed_slots(
    rules_xlsx_path: str,
    classes: List[str],
    web_tables: dict[str, Any] | None = None,
) -> Dict[Tuple[str, Slot], str]:
    df = _read_sheet(rules_xlsx_path, SHEET_FIXED, web_tables)
    need_cols = ["作用范围", "班级", "星期", "时段", "节次", "学科"]
    for c in need_cols:
        if c not in df.columns:
            raise ValueError(f"[{SHEET_FIXED}] 缺少列：{c}")

    fixed: Dict[Tuple[str, Slot], str] = {}
    for _, r in df.iterrows():
        scope = _norm_str(r["作用范围"]).upper()
        cls_raw = _norm_str(r.get("班级", ""))
        day = _norm_str(r["星期"])
        block = _norm_str(r["时段"])
        period = int(r["节次"])
        subj = _norm_str(r["学科"])

        if day not in ALL_DAYS:
            raise ValueError(f"[{SHEET_FIXED}] 星期不合法：{day}")
        if block not in ["早自习", "上午", "下午"]:
            raise ValueError(f"[{SHEET_FIXED}] 时段不合法：{block}")
        if not subj:
            raise ValueError(f"[{SHEET_FIXED}] 学科为空：{r}")

        slot = Slot(day=day, block=block, period=period)

        if scope == "ALL":
            for cls in classes:
                fixed[(cls, slot)] = subj
        else:
            # 允许用户写 scope=班级 或其它任意非ALL，只要班级列给了
            if not cls_raw:
                raise ValueError(f"[{SHEET_FIXED}] 作用范围不是ALL时，班级不能为空：{r}")
            fixed[(cls_raw, slot)] = subj

    return fixed


# ---------------------------
# 读取：学科禁排（展开为 Slot 集合）
# ---------------------------
def load_subject_bans(
    rules_xlsx_path: str,
    all_slots: List[Slot],
    web_tables: dict[str, Any] | None = None,
) -> Dict[str, Set[Slot]]:
    df = _read_sheet(rules_xlsx_path, SHEET_SUBJECT_BANS, web_tables)
    need_cols = ["学科", "禁排星期", "禁排时段", "节次"]
    for c in need_cols:
        if c not in df.columns:
            raise ValueError(f"[{SHEET_SUBJECT_BANS}] 缺少列：{c}")

    # 为展开做索引
    slots_by_day_block: Dict[Tuple[str, str], List[Slot]] = {}
    for s in all_slots:
        slots_by_day_block.setdefault((s.day, s.block), []).append(s)

    bans: Dict[str, Set[Slot]] = {}

    for _, r in df.iterrows():
        subj = _norm_str(r["学科"])
        day = _norm_str(r["禁排星期"])
        block = _norm_str(r["禁排时段"])
        k = _norm_str(r["节次"]).upper()

        if not subj:
            continue
        if day not in ALL_DAYS:
            raise ValueError(f"[{SHEET_SUBJECT_BANS}] 禁排星期不合法：{day}")
        if block not in ["早自习", "上午", "下午"]:
            raise ValueError(f"[{SHEET_SUBJECT_BANS}] 禁排时段不合法：{block}")

        cand = slots_by_day_block.get((day, block), [])
        if k == "ALL":
            hit = cand
        else:
            period = int(k)
            hit = [s for s in cand if s.period == period]

        bans.setdefault(subj, set()).update(hit)

    return bans


# ---------------------------
# 自检：容量 vs 需求（按班、按域）
# ---------------------------
def sanity_check_capacity(
    classes: List[str],
    req_hours: Dict[Tuple[str, str], Tuple[int, int, int]],
    all_slots: List[Slot],
    fixed_assign: Dict[Tuple[str, Slot], str],
) -> None:
    # 先算总容量（扣除固定占位）
    fixed_slots_per_class: Dict[str, Set[Slot]] = {c: set() for c in classes}
    for (cls, slot), _subj in fixed_assign.items():
        if cls in fixed_slots_per_class:
            fixed_slots_per_class[cls].add(slot)

    def cap_for(cls: str, domain: str) -> int:
        # domain: "E"早自习, "W"周中, "WE"周末
        cnt = 0
        for s in all_slots:
            if s in fixed_slots_per_class[cls]:
                continue
            if domain == "E":
                if s.block == "早自习":
                    cnt += 1
            elif domain == "W":
                if s.block != "早自习" and _is_weekday(s.day):
                    cnt += 1
            elif domain == "WE":
                if s.block != "早自习" and _is_weekend(s.day):
                    cnt += 1
        return cnt

    # 再算需求
    bad: List[str] = []
    for cls in classes:
        e_need = w_need = we_need = 0
        for (c, _subj), (e, w, we) in req_hours.items():
            if c != cls:
                continue
            e_need += e
            w_need += w
            we_need += we

        e_cap = cap_for(cls, "E")
        w_cap = cap_for(cls, "W")
        we_cap = cap_for(cls, "WE")

        if e_need > e_cap or w_need > w_cap or we_need > we_cap:
            bad.append(
                f"{cls}: 需求(E/W/WE)=({e_need}/{w_need}/{we_need}) "
                f"> 容量(E/W/WE)=({e_cap}/{w_cap}/{we_cap})"
            )

    if bad:
        msg = "\n".join(bad[:30])
        raise ValueError("白天规则容量自检失败（需求超过容量）：\n" + msg)


# ---------------------------
# 总入口：一次性读完并返回 DayInputData
# ---------------------------
def load_day_inputs(
    rules_xlsx_path: str,
    pos_xlsx_path: str,
    web_tables: dict[str, Any] | None = None,
    teacher_columns: dict[str, Any] | None = None,
) -> DayInputData:
    # 1) 时间格
    all_slots = load_time_grid_rules(rules_xlsx_path, web_tables)

    # 2) 班级 + 任课（非空即开课）
    classes, cls_subj_teacher = load_teacher_positioning(
        pos_xlsx_path,
        web_tables,
        teacher_columns=teacher_columns,
    )

    # 3) 固定课位（展开到每个班）
    fixed_assign = load_fixed_slots(rules_xlsx_path, classes, web_tables)

    # 4) 学科课时模板
    subj_hours = load_subject_hours(rules_xlsx_path, web_tables)

    # 5) 生成每班课时需求（仅对“该班开设的学科”）
    base_req: Dict[Tuple[str, str], Tuple[int, int, int]] = {}
    for (cls, subj), _tch in cls_subj_teacher.items():
        if subj not in subj_hours:
            raise ValueError(f"学科[{subj}] 在教师定位表出现，但在[{SHEET_HOURS}]里没有课时定义。")
        base_req[(cls, subj)] = subj_hours[subj]

    # 6) 覆盖差异
    req_hours = apply_class_overrides(rules_xlsx_path, base_req, web_tables)

    # 7) 先做容量自检（非常关键：防止数据把你炸死）
    sanity_check_capacity(classes, req_hours, all_slots, fixed_assign)

    # 8) 把固定课位占掉的槽从可排槽里扣除（建模时不再创建变量）
    fixed_slots_by_class: Dict[str, Set[Slot]] = {c: set() for c in classes}
    for (cls, slot), _subj in fixed_assign.items():
        fixed_slots_by_class[cls].add(slot)

    available_slots: List[Slot] = []
    # 注意：可排槽是“对所有班通用”的时间集合，但固定占位是“对每个班”的；
    # 这里先返回全体通用slots（建模时再按班扣除），也可以直接返回全slots。
    # 为简单起见：我们这里返回 all_slots（不扣），但提供 fixed_assign；建模时按班判断是否被固定占用。
    # —— 你要更省变量，可在建模时跳过 fixed 占用的槽。
    available_slots = list(all_slots)

    # 9) 学科禁排（展开为 Slot 集合）
    subject_ban_slots = load_subject_bans(rules_xlsx_path, all_slots, web_tables)

    return DayInputData(
        classes=classes,
        cls_subj_teacher=cls_subj_teacher,
        available_slots=available_slots,
        fixed_assign=fixed_assign,
        req_hours=req_hours,
        subject_ban_slots=subject_ban_slots,
    )
