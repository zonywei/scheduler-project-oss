# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple, List, Set
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot


@dataclass
class DayVars:
    x: Dict[Tuple[str, str, Slot], cp_model.IntVar]
    xs_by_cls_slot: Dict[Tuple[str, Slot], List[cp_model.IntVar]]
    xs_by_cls_subj: Dict[Tuple[str, str], List[cp_model.IntVar]]


def _is_teacher_slot_ban_exemption(
    data: DayInputData,
    cls: str,
    subj: str,
    slot: Slot,
) -> bool:
    teacher = str(data.cls_subj_teacher.get((cls, subj), "")).replace(" ", "")
    subj_norm = str(subj).strip()
    for item in getattr(data, "teacher_slot_ban_exemptions", []) or []:
        if not isinstance(item, dict):
            continue
        target_teacher = str(item.get("teacher", "")).replace(" ", "")
        subjects = {str(x).strip() for x in (item.get("subjects", []) or []) if str(x).strip()}
        if teacher != target_teacher or (subjects and subj_norm not in subjects):
            continue
        if slot.day != str(item.get("day", "")).strip():
            continue
        if slot.block != str(item.get("block", "")).strip():
            continue
        if int(slot.period) != int(item.get("period", 0)):
            continue
        return True
    return False


def build_day_variables(model: cp_model.CpModel, data: DayInputData) -> DayVars:
    x = {}
    xs_by_cls_slot = {}
    xs_by_cls_subj = {}

    # 每班固定槽集合
    fixed_by_cls: Dict[str, Set[Slot]] = {c: set() for c in data.classes}
    for (cls, slot), _ in data.fixed_assign.items():
        fixed_by_cls[cls].add(slot)

    # 每班开设学科（定位表非空）
    subjects_by_cls: Dict[str, List[str]] = {c: [] for c in data.classes}
    for (cls, subj), _tch in data.cls_subj_teacher.items():
        subjects_by_cls[cls].append(subj)
    for cls in subjects_by_cls:
        subjects_by_cls[cls] = sorted(set(subjects_by_cls[cls]))

    # 建变量：仅“非固定槽”×“该班开设学科”×“不被学科禁排”
    for cls in data.classes:
        for slot in data.available_slots:
            if slot in fixed_by_cls[cls]:
                continue  # 固定槽不建变量

            for subj in subjects_by_cls[cls]:
                if (
                    subj in data.subject_ban_slots
                    and slot in data.subject_ban_slots[subj]
                    and not _is_teacher_slot_ban_exemption(data, cls, subj, slot)
                ):
                    continue

                v = model.NewBoolVar(f"x[{cls},{subj},{slot.day},{slot.block}{slot.period}]")
                x[(cls, subj, slot)] = v
                xs_by_cls_slot.setdefault((cls, slot), []).append(v)
                xs_by_cls_subj.setdefault((cls, subj), []).append(v)

    return DayVars(x=x, xs_by_cls_slot=xs_by_cls_slot, xs_by_cls_subj=xs_by_cls_subj)
