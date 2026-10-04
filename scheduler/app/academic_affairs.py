# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from scheduler.calendar import ALL_DAYS

SCHOOL_DAYS = list(ALL_DAYS)


ACADEMIC_TABLES: dict[str, dict[str, Any]] = {
    "substitutions": {
        "label": "调代课",
        "columns": ["日期", "星期", "节次", "班级", "原教师", "代课教师", "原因", "状态"],
        "sample": {"日期": "", "星期": "星期一", "节次": "上午1", "班级": "", "原教师": "", "代课教师": "", "原因": "", "状态": "待审批"},
    },
    "exam_duties": {
        "label": "考务监考",
        "columns": ["考试名称", "日期", "星期", "时段", "科目", "考场", "所需监考数", "已排监考教师", "特殊要求", "状态"],
        "sample": {"考试名称": "", "日期": "", "星期": "星期一", "时段": "上午", "科目": "", "考场": "", "所需监考数": "2", "已排监考教师": "", "特殊要求": "", "状态": "待确认"},
    },
    "after_school": {
        "label": "课后服务",
        "columns": ["课程名称", "适用年级", "星期", "时段", "负责教师", "场地", "容量", "报名人数", "补贴口径", "状态"],
        "sample": {"课程名称": "", "适用年级": "", "星期": "星期一", "时段": "课后服务1", "负责教师": "", "场地": "", "容量": "40", "报名人数": "0", "补贴口径": "", "状态": "待确认"},
    },
    "walking_classes": {
        "label": "走班选科",
        "columns": ["组合/层次", "星期", "时段", "学生人数", "行政班来源", "教学班", "任课教师", "教室", "状态", "备注"],
        "sample": {"组合/层次": "", "星期": "星期一", "时段": "上午1", "学生人数": "0", "行政班来源": "", "教学班": "", "任课教师": "", "教室": "", "状态": "待确认", "备注": ""},
    },
    "rooms": {
        "label": "场地资源",
        "columns": ["场地", "类型", "容量", "可用时段", "不可用时段", "负责人", "备注"],
        "sample": {"场地": "", "类型": "普通教室", "容量": "50", "可用时段": "全天", "不可用时段": "", "负责人": "", "备注": ""},
    },
    "teaching_research": {
        "label": "教研/会议",
        "columns": ["教研组", "星期", "时段", "参与教师", "地点", "是否固定", "优先级", "状态", "备注"],
        "sample": {"教研组": "", "星期": "星期一", "时段": "下午4", "参与教师": "", "地点": "", "是否固定": "是", "优先级": "高", "状态": "待确认", "备注": ""},
    },
    "teacher_leave": {
        "label": "请假日志",
        "columns": ["教师", "开始日期", "结束日期", "星期", "时段", "原因", "代办安排", "状态"],
        "sample": {"教师": "", "开始日期": "", "结束日期": "", "星期": "星期一", "时段": "全天", "原因": "", "代办安排": "", "状态": "待审批"},
    },
    "class_events": {
        "label": "班级活动",
        "columns": ["活动名称", "班级", "日期", "星期", "时段", "负责教师", "地点", "参与人数", "是否影响上课", "状态"],
        "sample": {"活动名称": "", "班级": "", "日期": "", "星期": "星期一", "时段": "下午1", "负责教师": "", "地点": "", "参与人数": "0", "是否影响上课": "是", "状态": "待确认"},
    },
    "club_activities": {
        "label": "社团活动",
        "columns": ["社团名称", "适用年级", "星期", "时段", "指导教师", "地点", "容量", "报名人数", "状态"],
        "sample": {"社团名称": "", "适用年级": "", "星期": "星期三", "时段": "课后服务2", "指导教师": "", "地点": "", "容量": "40", "报名人数": "0", "状态": "待确认"},
    },
    "lunch_duty": {
        "label": "午餐/午休值守",
        "columns": ["日期", "星期", "时段", "区域", "值守教师", "所需人数", "已排人数", "状态", "备注"],
        "sample": {"日期": "", "星期": "星期一", "时段": "午休", "区域": "", "值守教师": "", "所需人数": "1", "已排人数": "0", "状态": "待确认", "备注": ""},
    },
    "boarding_dorm": {
        "label": "宿舍管理",
        "columns": ["日期", "星期", "时段", "宿舍楼/楼层", "值守教师", "性别要求", "所需人数", "已排人数", "状态"],
        "sample": {"日期": "", "星期": "星期一", "时段": "晚查寝", "宿舍楼/楼层": "", "值守教师": "", "性别要求": "", "所需人数": "1", "已排人数": "0", "状态": "待确认"},
    },
    "lab_reservations": {
        "label": "实验室预约",
        "columns": ["实验名称", "学科", "班级", "星期", "时段", "任课教师", "实验室", "准备员", "危险品/器材", "状态"],
        "sample": {"实验名称": "", "学科": "", "班级": "", "星期": "星期一", "时段": "上午1", "任课教师": "", "实验室": "", "准备员": "", "危险品/器材": "", "状态": "待确认"},
    },
    "equipment_loans": {
        "label": "设备借用",
        "columns": ["设备", "借用教师", "日期", "星期", "时段", "使用地点", "归还时间", "状态", "备注"],
        "sample": {"设备": "", "借用教师": "", "日期": "", "星期": "星期一", "时段": "上午1", "使用地点": "", "归还时间": "", "状态": "待确认", "备注": ""},
    },
    "public_lessons": {
        "label": "公开课/听评课",
        "columns": ["课题", "开课教师", "听课教师", "日期", "星期", "节次", "班级", "地点", "状态", "备注"],
        "sample": {"课题": "", "开课教师": "", "听课教师": "", "日期": "", "星期": "星期一", "节次": "上午2", "班级": "", "地点": "", "状态": "待确认", "备注": ""},
    },
    "teaching_inspections": {
        "label": "教学巡课",
        "columns": ["巡课日期", "星期", "时段", "巡课人员", "年级/楼层", "检查重点", "发现问题", "处理状态"],
        "sample": {"巡课日期": "", "星期": "星期一", "时段": "上午", "巡课人员": "", "年级/楼层": "", "检查重点": "", "发现问题": "", "处理状态": "待巡查"},
    },
    "parent_meetings": {
        "label": "家长会/家校沟通",
        "columns": ["会议主题", "班级/年级", "日期", "星期", "时段", "班主任/负责人", "地点", "预计人数", "状态"],
        "sample": {"会议主题": "", "班级/年级": "", "日期": "", "星期": "星期五", "时段": "下午4", "班主任/负责人": "", "地点": "", "预计人数": "0", "状态": "待确认"},
    },
    "grade_assemblies": {
        "label": "年级集会",
        "columns": ["集会主题", "年级", "日期", "星期", "时段", "负责人", "地点", "预计人数", "是否影响上课", "状态"],
        "sample": {"集会主题": "", "年级": "", "日期": "", "星期": "星期一", "时段": "上午1", "负责人": "", "地点": "", "预计人数": "0", "是否影响上课": "是", "状态": "待确认"},
    },
    "makeup_lessons": {
        "label": "补课/培优辅导",
        "columns": ["课程/对象", "学科", "星期", "时段", "负责教师", "地点", "学生人数", "来源", "状态"],
        "sample": {"课程/对象": "", "学科": "", "星期": "星期六", "时段": "上午1", "负责教师": "", "地点": "", "学生人数": "0", "来源": "培优", "状态": "待确认"},
    },
    "exam_marking": {
        "label": "命题/阅卷",
        "columns": ["考试名称", "学科", "任务类型", "负责人", "参与教师", "开始日期", "截止日期", "状态", "备注"],
        "sample": {"考试名称": "", "学科": "", "任务类型": "阅卷", "负责人": "", "参与教师": "", "开始日期": "", "截止日期": "", "状态": "待分配", "备注": ""},
    },
    "student_support": {
        "label": "学生个别辅导",
        "columns": ["学生/群体", "班级", "支持类型", "负责教师", "星期", "时段", "地点", "频次", "保密等级", "状态"],
        "sample": {"学生/群体": "", "班级": "", "支持类型": "学业辅导", "负责教师": "", "星期": "星期一", "时段": "下午4", "地点": "", "频次": "每周", "保密等级": "普通", "状态": "待确认"},
    },
    "sport_events": {
        "label": "体育赛事",
        "columns": ["赛事名称", "日期", "星期", "时段", "负责教师", "场地", "参与班级/年级", "预计人数", "状态"],
        "sample": {"赛事名称": "", "日期": "", "星期": "星期三", "时段": "下午", "负责教师": "", "场地": "", "参与班级/年级": "", "预计人数": "0", "状态": "待确认"},
    },
    "safety_drills": {
        "label": "安全演练",
        "columns": ["演练名称", "日期", "星期", "时段", "负责人", "参与年级", "集合地点", "是否停课", "状态"],
        "sample": {"演练名称": "", "日期": "", "星期": "星期二", "时段": "上午", "负责人": "", "参与年级": "", "集合地点": "", "是否停课": "是", "状态": "待确认"},
    },
    "teacher_training": {
        "label": "教师培训",
        "columns": ["培训名称", "日期", "星期", "时段", "参训教师", "地点", "主办方", "是否需要调课", "状态"],
        "sample": {"培训名称": "", "日期": "", "星期": "星期五", "时段": "下午", "参训教师": "", "地点": "", "主办方": "", "是否需要调课": "否", "状态": "待确认"},
    },
    "timetable_changes": {
        "label": "课表发布/变更",
        "columns": ["变更标题", "变更类型", "班级", "原星期", "原节次", "原学科", "原教师", "新星期", "新节次", "新学科", "新教师", "新教室", "生效日期", "提交人", "审批人", "状态", "说明"],
        "sample": {"变更标题": "", "变更类型": "临时调课", "班级": "", "原星期": "星期一", "原节次": "上午1", "原学科": "", "原教师": "", "新星期": "星期一", "新节次": "下午1", "新学科": "", "新教师": "", "新教室": "", "生效日期": "", "提交人": "", "审批人": "", "状态": "待审批", "说明": ""},
    },
    "subject_group_tasks": {
        "label": "备课组任务",
        "columns": ["备课组", "任务", "负责人", "参与教师", "开始日期", "截止日期", "优先级", "状态", "备注"],
        "sample": {"备课组": "", "任务": "", "负责人": "", "参与教师": "", "开始日期": "", "截止日期": "", "优先级": "中", "状态": "待分配", "备注": ""},
    },
    "campus_supervision": {
        "label": "校园值周",
        "columns": ["周次", "日期", "星期", "时段", "区域", "值周教师", "所需人数", "已排人数", "状态"],
        "sample": {"周次": "", "日期": "", "星期": "星期一", "时段": "早到校", "区域": "", "值周教师": "", "所需人数": "1", "已排人数": "0", "状态": "待确认"},
    },
}


K12_CAPABILITY_ITEMS: list[dict[str, str]] = [
    {"id": "k12.01", "category": "基础配置", "title": "教师定位 Web 编辑", "meaning": "减少 Excel 往返。"},
    {"id": "k12.02", "category": "基础配置", "title": "白天规则 Web 编辑", "meaning": "支持统一入口维护基础课位。"},
    {"id": "k12.03", "category": "基础配置", "title": "保留 Excel 回退", "meaning": "学校可逐步迁移。"},
    {"id": "k12.04", "category": "规则治理", "title": "规则按业务分组", "meaning": "教务按场景找规则。"},
    {"id": "k12.05", "category": "规则治理", "title": "硬约束与软约束分离", "meaning": "明确必须满足和可权衡优化。"},
    {"id": "k12.06", "category": "规则治理", "title": "规则作用对象编辑", "meaning": "支持全体、教师、学科组等对象。"},
    {"id": "k12.07", "category": "规则治理", "title": "规则例外编辑", "meaning": "支持常见个别情况。"},
    {"id": "k12.08", "category": "规则治理", "title": "自然语言临时规则", "meaning": "让口头要求进入配置闭环。"},
    {"id": "k12.09", "category": "规则治理", "title": "AI 接口自定义", "meaning": "后续可接用户自有模型。"},
    {"id": "k12.10", "category": "规则治理", "title": "确定冲突图", "meaning": "用 Cytoscape.js 展示规则冲突关系。"},
    {"id": "k12.11", "category": "教务表", "title": "调代课管理", "meaning": "跟踪待审批调代课。"},
    {"id": "k12.12", "category": "教务表", "title": "考务监考管理", "meaning": "检查监考人数是否足够。"},
    {"id": "k12.13", "category": "教务表", "title": "课后服务管理", "meaning": "关注容量、报名和场地。"},
    {"id": "k12.14", "category": "教务表", "title": "走班选科管理", "meaning": "兼容高中选科走班。"},
    {"id": "k12.15", "category": "教务表", "title": "场地资源管理", "meaning": "形成场地容量和负责人基础库。"},
    {"id": "k12.16", "category": "教务表", "title": "教研会议管理", "meaning": "把固定教研时间纳入排课参考。"},
    {"id": "k12.17", "category": "教务日志", "title": "教师请假日志", "meaning": "记录请假事件并辅助代课安排。"},
    {"id": "k12.18", "category": "教务表", "title": "班级活动管理", "meaning": "处理德育、研学、主题班会等占课。"},
    {"id": "k12.19", "category": "教务表", "title": "社团活动管理", "meaning": "支撑课后社团排班。"},
    {"id": "k12.20", "category": "教务表", "title": "午餐午休值守", "meaning": "覆盖中小学午间管理。"},
    {"id": "k12.21", "category": "教务表", "title": "宿舍管理", "meaning": "覆盖寄宿制查寝和值守。"},
    {"id": "k12.22", "category": "教务表", "title": "实验室预约", "meaning": "管理实验室、准备员和器材。"},
    {"id": "k12.23", "category": "教务表", "title": "设备借用", "meaning": "减少设备和场地错配。"},
    {"id": "k12.24", "category": "教务表", "title": "公开课听评课", "meaning": "纳入开课和听课教师占用。"},
    {"id": "k12.25", "category": "教务表", "title": "教学巡课", "meaning": "支持日常教学督导。"},
    {"id": "k12.26", "category": "教务表", "title": "家长会家校沟通", "meaning": "纳入晚间和周末场地安排。"},
    {"id": "k12.27", "category": "教务表", "title": "年级集会", "meaning": "管理大规模集会占用。"},
    {"id": "k12.28", "category": "教务表", "title": "补课培优辅导", "meaning": "支持周末和课后辅导。"},
    {"id": "k12.29", "category": "教务表", "title": "命题阅卷", "meaning": "跟踪考试前后教师任务。"},
    {"id": "k12.30", "category": "教务表", "title": "学生个别辅导", "meaning": "支持学业、心理和个别化支持。"},
    {"id": "k12.31", "category": "教务表", "title": "体育赛事", "meaning": "管理操场和体育馆占用。"},
    {"id": "k12.32", "category": "教务表", "title": "安全演练", "meaning": "处理停课和集合场地安排。"},
    {"id": "k12.33", "category": "教务表", "title": "教师培训", "meaning": "识别参训教师调课需求。"},
    {"id": "k12.34", "category": "教务表", "title": "课表发布变更", "meaning": "把调课单、发布审批和变更留痕纳入流程。"},
    {"id": "k12.35", "category": "教务表", "title": "备课组任务", "meaning": "覆盖教研组任务分配。"},
    {"id": "k12.36", "category": "教务表", "title": "校园值周", "meaning": "覆盖早到校、课间、放学值周。"},
    {"id": "k12.37", "category": "风险检测", "title": "待审批事项统计", "meaning": "避免未确认配置进入发布。"},
    {"id": "k12.38", "category": "风险检测", "title": "监考人数不足检测", "meaning": "考务安排先行兜底。"},
    {"id": "k12.39", "category": "风险检测", "title": "值守人数不足检测", "meaning": "午休、宿舍、值周可复用。"},
    {"id": "k12.40", "category": "风险检测", "title": "场地重复占用检测", "meaning": "跨活动发现同一地点撞车。"},
    {"id": "k12.41", "category": "风险检测", "title": "教师同一时段冲突检测", "meaning": "发现任务叠加。"},
    {"id": "k12.42", "category": "风险检测", "title": "请假日志冲突检测", "meaning": "请假记录能触发调代课提醒。"},
    {"id": "k12.43", "category": "风险检测", "title": "容量超限检测", "meaning": "避免场地或课程报名超载。"},
    {"id": "k12.44", "category": "风险检测", "title": "教师日负荷预警", "meaning": "发现单日任务过重。"},
    {"id": "k12.45", "category": "风险检测", "title": "基础字段缺失检测", "meaning": "先补齐关键字段。"},
    {"id": "k12.46", "category": "风险检测", "title": "调代课自代冲突检测", "meaning": "避免原教师和代课教师相同。"},
    {"id": "k12.47", "category": "风险检测", "title": "公开课信息完整性检测", "meaning": "开课、听课、场地都可核查。"},
    {"id": "k12.48", "category": "风险检测", "title": "实验室准备项检测", "meaning": "避免实验课无准备员或场地。"},
    {"id": "k12.49", "category": "决策辅助", "title": "治理建议输出", "meaning": "把风险转成可执行建议。"},
    {"id": "k12.50", "category": "决策辅助", "title": "健康分输出", "meaning": "快速判断配置成熟度。"},
]


TEACHER_EVENT_COLUMNS: dict[str, list[str]] = {
    "substitutions": ["代课教师"],
    "exam_duties": ["已排监考教师"],
    "after_school": ["负责教师"],
    "walking_classes": ["任课教师"],
    "teaching_research": ["参与教师"],
    "teacher_leave": ["教师"],
    "class_events": ["负责教师"],
    "club_activities": ["指导教师"],
    "lunch_duty": ["值守教师"],
    "boarding_dorm": ["值守教师"],
    "lab_reservations": ["任课教师", "准备员"],
    "equipment_loans": ["借用教师"],
    "public_lessons": ["开课教师", "听课教师"],
    "teaching_inspections": ["巡课人员"],
    "parent_meetings": ["班主任/负责人"],
    "grade_assemblies": ["负责人"],
    "makeup_lessons": ["负责教师"],
    "exam_marking": ["负责人", "参与教师"],
    "student_support": ["负责教师"],
    "sport_events": ["负责教师"],
    "safety_drills": ["负责人"],
    "teacher_training": ["参训教师"],
    "timetable_changes": ["新教师"],
    "subject_group_tasks": ["负责人", "参与教师"],
    "campus_supervision": ["值周教师"],
}


ROOM_COLUMNS: dict[str, list[str]] = {
    "exam_duties": ["考场"],
    "after_school": ["场地"],
    "walking_classes": ["教室"],
    "teaching_research": ["地点"],
    "class_events": ["地点"],
    "club_activities": ["地点"],
    "lab_reservations": ["实验室"],
    "equipment_loans": ["使用地点"],
    "public_lessons": ["地点"],
    "parent_meetings": ["地点"],
    "grade_assemblies": ["地点"],
    "makeup_lessons": ["地点"],
    "student_support": ["地点"],
    "sport_events": ["场地"],
    "safety_drills": ["集合地点"],
    "teacher_training": ["地点"],
    "timetable_changes": ["新教室"],
}


REQUIRED_FIELDS: dict[str, list[str]] = {
    "substitutions": ["星期", "节次", "班级", "原教师", "代课教师", "状态"],
    "exam_duties": ["考试名称", "星期", "时段", "科目", "考场", "所需监考数"],
    "after_school": ["课程名称", "星期", "时段", "负责教师", "场地"],
    "walking_classes": ["组合/层次", "星期", "时段", "任课教师", "教室"],
    "rooms": ["场地", "类型", "容量"],
    "teacher_leave": ["教师", "星期", "时段", "状态"],
    "lab_reservations": ["实验名称", "星期", "时段", "任课教师", "实验室"],
    "public_lessons": ["课题", "开课教师", "星期", "节次", "地点"],
    "timetable_changes": ["变更标题", "班级", "原星期", "原节次", "新星期", "新节次", "新教师", "状态"],
}


def default_academic_affairs_payload() -> dict[str, Any]:
    return {
        "tables": {key: [] for key in ACADEMIC_TABLES},
        "settings": {
            "substitution_approval_enabled": True,
            "exam_invigilation_balance_enabled": True,
            "after_school_service_enabled": True,
            "walking_class_enabled": True,
            "teacher_daily_task_warning_threshold": 4,
        },
    }


def normalize_academic_affairs(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_academic_affairs_payload()
    if not isinstance(payload, dict):
        return base
    tables = payload.get("tables")
    if isinstance(tables, dict):
        for key in ACADEMIC_TABLES:
            rows = tables.get(key)
            if isinstance(rows, list):
                base["tables"][key] = [_clean_row(row) for row in rows if isinstance(row, dict)]
    settings = payload.get("settings")
    if isinstance(settings, dict):
        base["settings"].update(settings)
    return base


def summarize_academic_affairs(payload: dict[str, Any]) -> dict[str, Any]:
    data = normalize_academic_affairs(payload)
    tables = data["tables"]
    settings = data["settings"]
    risks: list[dict[str, Any]] = []

    risks.extend(_pending_status_risks(tables))
    risks.extend(_substitution_risks(tables))
    risks.extend(_staffing_risks(tables))
    risks.extend(_capacity_risks(tables))
    risks.extend(_room_conflict_risks(tables))
    risks.extend(_teacher_conflict_risks(tables))
    risks.extend(_teacher_leave_risks(tables))
    risks.extend(_teacher_load_risks(tables, _to_int(settings.get("teacher_daily_task_warning_threshold"), 4)))
    risks.extend(_required_field_risks(tables))
    risks.extend(_timetable_change_risks(tables))
    risks.extend(_special_business_risks(tables))
    risks = _dedupe_risks(risks)

    teacher_load = _teacher_load(tables)
    room_usage = _room_usage(tables)
    timetable_changes = tables["timetable_changes"]
    pending_total = sum(1 for table in tables.values() for row in table if _is_pending(row.get("状态") or row.get("处理状态")))
    errors = sum(1 for risk in risks if risk["severity"] == "error")
    warnings = sum(1 for risk in risks if risk["severity"] == "warning")
    health_score = max(0, 100 - errors * 12 - warnings * 5)
    room_conflicts = sum(1 for risk in risks if risk.get("kind") == "room_conflict")
    teacher_conflicts = sum(1 for risk in risks if risk.get("kind") == "teacher_conflict")
    capacity_warnings = sum(1 for risk in risks if risk.get("kind") == "capacity")
    manual_change_conflicts = sum(1 for risk in risks if risk.get("kind") in {"timetable_change_teacher_conflict", "timetable_change_class_conflict"})
    manual_change_noops = sum(1 for risk in risks if risk.get("kind") == "timetable_change_noop")
    manual_change_missing_approvals = sum(1 for risk in risks if risk.get("kind") == "timetable_change_approval")
    pending_timetable_changes = len([r for r in timetable_changes if _is_pending(r.get("状态"))])
    approved_timetable_changes = len([r for r in timetable_changes if _is_confirmed(r.get("状态"))])
    manual_adjustment = {
        "total": len(timetable_changes),
        "pending": pending_timetable_changes,
        "approved": approved_timetable_changes,
        "conflicts": manual_change_conflicts,
        "noop_changes": manual_change_noops,
        "missing_approvals": manual_change_missing_approvals,
        "ready": bool(timetable_changes) and pending_timetable_changes == 0 and manual_change_conflicts == 0,
    }

    metrics = {
        "pending_substitutions": len([r for r in tables["substitutions"] if _is_pending(r.get("状态"))]),
        "exam_rows": len(tables["exam_duties"]),
        "after_school_courses": len(tables["after_school"]),
        "walking_class_groups": len(tables["walking_classes"]),
        "rooms": len(tables["rooms"]),
        "teacher_load_records": sum(teacher_load.values()),
        "teacher_leave_rows": len(tables["teacher_leave"]),
        "timetable_change_rows": len(timetable_changes),
        "pending_timetable_changes": pending_timetable_changes,
        "approved_timetable_changes": approved_timetable_changes,
        "manual_change_conflicts": manual_change_conflicts,
        "pending_items": pending_total,
        "room_conflicts": room_conflicts,
        "teacher_conflicts": teacher_conflicts,
        "capacity_warnings": capacity_warnings,
        "risk_errors": errors,
        "risk_warnings": warnings,
        "health_score": health_score,
    }
    metric_cards = [
        {"label": "待确认事项", "value": pending_total, "hint": "审批/确认状态仍未完成"},
        {"label": "教师任务", "value": metrics["teacher_load_records"], "hint": "跨教务表统计"},
        {"label": "场地冲突", "value": room_conflicts, "hint": "同一时段同一地点"},
        {"label": "教师冲突", "value": teacher_conflicts, "hint": "同一时段多任务"},
        {"label": "超容量", "value": capacity_warnings, "hint": "人数超过容量"},
        {"label": "调课单", "value": len(timetable_changes), "hint": "发布/变更记录"},
        {"label": "健康分", "value": health_score, "hint": "错误和警告越少越高"},
    ]

    return {
        "metrics": metrics,
        "metric_cards": metric_cards,
        "table_counts": [{"key": key, "label": ACADEMIC_TABLES[key]["label"], "count": len(tables[key])} for key in ACADEMIC_TABLES],
        "teacher_load_top": [{"teacher": k, "count": v} for k, v in teacher_load.most_common(10)],
        "room_usage_top": [{"room": k, "count": v} for k, v in room_usage.most_common(10)],
        "manual_adjustment": manual_adjustment,
        "risks": risks,
        "recommendations": _recommendations(risks, teacher_load, room_usage, pending_total),
        "schema": ACADEMIC_TABLES,
        "capability_items": K12_CAPABILITY_ITEMS,
    }


def _pending_status_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    risks = []
    for table_key, rows in tables.items():
        label = ACADEMIC_TABLES[table_key]["label"]
        pending = [row for row in rows if _is_pending(row.get("状态") or row.get("处理状态"))]
        if pending:
            title = "存在未审批调代课" if table_key == "substitutions" else f"{label}存在待确认事项"
            risks.append(_risk("warning", title, f"{label}当前有 {len(pending)} 条记录仍未确认。", "发布课表或安排前先完成审批/确认。", kind="pending", refs=[table_key]))
    return risks


def _substitution_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    risks = []
    for row in tables["substitutions"]:
        original = str(row.get("原教师") or "").strip()
        substitute = str(row.get("代课教师") or "").strip()
        if original and substitute and original == substitute:
            risks.append(_risk("error", "调代课原教师和代课教师相同", f"{original} 在 {row.get('星期') or ''} {row.get('节次') or ''} 被设置为自己代自己的课。", "重新选择代课教师，或删除这条无效调代课。", kind="substitution", refs=["substitutions"]))
    return risks


def _staffing_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    risks = []
    for row in tables["exam_duties"]:
        need = _to_int(row.get("所需监考数"), 0)
        teachers = _split_names(row.get("已排监考教师"))
        if need > 0 and len(teachers) < need:
            risks.append(_risk("error", "监考教师数量不足", f"{row.get('考试名称') or '未命名考试'} {row.get('科目') or ''} {row.get('考场') or ''} 需要 {need} 人，当前 {len(teachers)} 人。", "补足监考教师，或降低该考场监考人数要求。", kind="staffing", refs=["exam_duties"]))
    for table_key in ("lunch_duty", "boarding_dorm", "campus_supervision"):
        label = ACADEMIC_TABLES[table_key]["label"]
        for row in tables[table_key]:
            need = _to_int(row.get("所需人数"), 0)
            scheduled = max(_to_int(row.get("已排人数"), 0), len(_split_names(row.get("值守教师") or row.get("值周教师"))))
            if need > 0 and scheduled < need:
                risks.append(_risk("warning", f"{label}人数不足", f"{row.get('星期') or ''} {row.get('时段') or ''} {row.get('区域') or row.get('宿舍楼/楼层') or ''} 需要 {need} 人，当前 {scheduled} 人。", "补足值守教师，或调整该时段所需人数。", kind="staffing", refs=[table_key]))
    return risks


def _capacity_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    risks = []
    room_caps = _room_capacity_map(tables)
    for table_key, rows in tables.items():
        label = ACADEMIC_TABLES[table_key]["label"]
        for row in rows:
            own_capacity = _to_int(row.get("容量"), 0)
            size = _event_size(row)
            if own_capacity and size > own_capacity:
                title = "课后服务报名超容量" if table_key == "after_school" else f"{label}报名或人数超容量"
                risks.append(_risk("warning", title, f"{_event_title(table_key, row)} 人数 {size}，自身容量 {own_capacity}。", "拆分活动、限制报名，或更换更大场地。", kind="capacity", refs=[table_key]))
            for room in _row_rooms(table_key, row):
                room_capacity = room_caps.get(room, 0)
                if room_capacity and size > room_capacity:
                    risks.append(_risk("warning", "场地容量不足", f"{_event_title(table_key, row)} 使用 {room}，预计 {size} 人，场地容量 {room_capacity}。", "更换大容量场地或降低参与人数。", kind="capacity", refs=[table_key, "rooms"]))
    return risks


def _room_conflict_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for event in _iter_room_events(tables):
        day, slot = event["day"], event["slot"]
        if not day or not slot or _is_all_day(slot):
            continue
        by_key[(event["room"], day, slot)].append(event)
    risks = []
    for (room, day, slot), events in by_key.items():
        if len(events) <= 1:
            continue
        names = "、".join(_short_event(e) for e in events[:5])
        refs = sorted({e["table"] for e in events})
        title = "课后服务场地冲突" if refs == ["after_school"] else "场地同一时段重复占用"
        risks.append(_risk("error", title, f"{room} 在 {day} {slot} 同时安排：{names}。", "调整其中一项的场地或时段。", kind="room_conflict", refs=refs))
    return risks


def _teacher_conflict_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for event in _iter_teacher_events(tables):
        if event["table"] == "teacher_leave":
            continue
        day, slot = event["day"], event["slot"]
        if not day or not slot or _is_all_day(slot):
            continue
        by_key[(event["teacher"], day, slot)].append(event)
    risks = []
    for (teacher, day, slot), events in by_key.items():
        if len(events) <= 1:
            continue
        if {e["table"] for e in events} == {"timetable_changes"}:
            continue
        names = "、".join(_short_event(e) for e in events[:5])
        risks.append(_risk("error", "教师同一时段多任务冲突", f"{teacher} 在 {day} {slot} 同时出现：{names}。", "保留优先级最高的安排，其余调整教师、日期或时段。", kind="teacher_conflict", refs=sorted({e["table"] for e in events})))
    return risks


def _teacher_leave_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events = [event for event in _iter_teacher_events(tables) if event["table"] != "teacher_leave"]
    risks = []
    for leave in _iter_teacher_events(tables):
        if leave["table"] != "teacher_leave":
            continue
        for event in events:
            if leave["teacher"] != event["teacher"]:
                continue
            if _same_time_window(leave, event):
                risks.append(_risk("error", "请假日志与已排任务冲突", f"{leave['teacher']} 请假时段 {leave['day'] or '未填日期'} {leave['slot'] or '未填时段'} 仍安排了 {_short_event(event)}。", "为该任务安排替代教师，或调整任务时段。", kind="leave_conflict", refs=["teacher_leave", event["table"]]))
    return risks


def _teacher_load_risks(tables: dict[str, list[dict[str, Any]]], threshold: int) -> list[dict[str, Any]]:
    by_teacher_day: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for event in _iter_teacher_events(tables):
        if event["table"] == "teacher_leave" or not event["teacher"] or not event["day"]:
            continue
        by_teacher_day[(event["teacher"], event["day"])].append(event)
    risks = []
    for (teacher, day), events in by_teacher_day.items():
        if len(events) >= max(1, threshold):
            risks.append(_risk("warning", "教师单日教务任务偏多", f"{teacher} 在 {day} 已关联 {len(events)} 项教务任务。", "把低优先级任务分散到其他教师或其他日期。", kind="teacher_load", refs=sorted({e["table"] for e in events})))
    return risks


def _required_field_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    risks = []
    for table_key, fields in REQUIRED_FIELDS.items():
        label = ACADEMIC_TABLES[table_key]["label"]
        for idx, row in enumerate(tables[table_key], start=1):
            missing = [field for field in fields if not str(row.get(field) or "").strip()]
            if missing and any(str(value or "").strip() for value in row.values()):
                risks.append(_risk("warning", f"{label}关键字段未填", f"第 {idx} 行缺少：{'、'.join(missing)}。", "补齐关键字段后再用于排课或教务发布。", kind="missing_field", refs=[table_key]))
    return risks


def _timetable_change_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = tables["timetable_changes"]
    risks: list[dict[str, Any]] = []
    by_teacher: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    by_class: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)

    for idx, row in enumerate(rows, start=1):
        status = row.get("状态")
        if _is_inactive_status(status):
            continue
        day = _row_day(row)
        slot = _row_slot(row)
        teacher = str(row.get("新教师") or "").strip()
        class_name = str(row.get("班级") or "").strip()
        if day and slot and teacher:
            by_teacher[(teacher, day, slot)].append((idx, row))
        if day and slot and class_name:
            by_class[(class_name, day, slot)].append((idx, row))

        original_day = str(row.get("原星期") or "").strip()
        original_slot = str(row.get("原节次") or "").strip()
        original_subject = str(row.get("原学科") or "").strip()
        new_subject = str(row.get("新学科") or "").strip()
        original_teacher = str(row.get("原教师") or "").strip()
        is_same_subject = not original_subject and not new_subject or bool(original_subject and new_subject and original_subject == new_subject)
        if original_day and original_slot and teacher and original_teacher and day == original_day and slot == original_slot and teacher == original_teacher and is_same_subject:
            risks.append(_risk("warning", "调课单没有实际变更", f"课表发布/变更第 {idx} 行新旧教师、时段和学科一致。", "删除该调课单，或补充真正需要变更的教师、节次、学科或教室。", kind="timetable_change_noop", refs=["timetable_changes"]))

        if _is_confirmed(status) and not str(row.get("审批人") or "").strip():
            risks.append(_risk("warning", "已通过调课单缺少审批人", f"课表发布/变更第 {idx} 行状态为 {status}，但审批人为空。", "补齐审批人，保证发布后可追责。", kind="timetable_change_approval", refs=["timetable_changes"]))

    for (teacher, day, slot), events in by_teacher.items():
        if len(events) <= 1:
            continue
        labels = "、".join(f"第{idx}行:{_event_title('timetable_changes', row)}" for idx, row in events[:5])
        risks.append(_risk("error", "调课后教师同一时段冲突", f"{teacher} 在 {day} {slot} 被多个调课单占用：{labels}。", "只保留一个生效调课单，其余改教师或改到其他节次。", kind="timetable_change_teacher_conflict", refs=["timetable_changes"]))

    for (class_name, day, slot), events in by_class.items():
        if len(events) <= 1:
            continue
        labels = "、".join(f"第{idx}行:{_event_title('timetable_changes', row)}" for idx, row in events[:5])
        risks.append(_risk("error", "调课后班级同一时段冲突", f"{class_name} 在 {day} {slot} 有多个调课结果：{labels}。", "同一班级同一节次只能保留一条生效安排。", kind="timetable_change_class_conflict", refs=["timetable_changes"]))

    return risks


def _special_business_risks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    risks = []
    for row in tables["lab_reservations"]:
        if any(str(row.get(key) or "").strip() for key in ("实验名称", "学科", "班级")) and not str(row.get("准备员") or "").strip():
            risks.append(_risk("warning", "实验室预约缺少准备员", f"{row.get('实验名称') or '未命名实验'} 尚未填写准备员。", "补充实验准备员，避免器材和安全准备遗漏。", kind="missing_field", refs=["lab_reservations"]))
    for row in tables["public_lessons"]:
        if str(row.get("课题") or "").strip() and not _split_names(row.get("听课教师")):
            risks.append(_risk("warning", "公开课缺少听课教师", f"{row.get('课题')} 还没有安排听课教师。", "补充听课教师，或标记为校内展示课。", kind="missing_field", refs=["public_lessons"]))
    for row in tables["teacher_training"]:
        if str(row.get("是否需要调课") or "").strip() == "是" and _is_pending(row.get("状态")):
            risks.append(_risk("warning", "教师培训需要调课但未确认", f"{row.get('培训名称') or '未命名培训'} 标记需要调课，状态仍为 {row.get('状态') or '未填'}。", "先完成调课方案，再确认培训名单。", kind="pending", refs=["teacher_training"]))
    return risks


def _recommendations(risks: list[dict[str, Any]], teacher_load: Counter[str], room_usage: Counter[str], pending_total: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if any(r["severity"] == "error" for r in risks):
        out.append({"title": "先处理红色确定问题", "detail": "当前存在错误级风险，建议先处理教师冲突、请假日志冲突、场地冲突或人数不足。"})
    if pending_total:
        out.append({"title": "发布前清空待确认事项", "detail": f"当前还有 {pending_total} 条待审批/待确认事项，建议建立发布前检查清单。"})
    if teacher_load:
        teacher, count = teacher_load.most_common(1)[0]
        out.append({"title": "关注教师额外负荷", "detail": f"{teacher} 当前关联教务任务 {count} 项，可在调代课、监考、值守中做分摊。"})
    if room_usage:
        room, count = room_usage.most_common(1)[0]
        out.append({"title": "建立热门场地预约规则", "detail": f"{room} 当前被引用 {count} 次，建议设置场地容量、不可用时段和负责人。"})
    if not out:
        out.append({"title": "当前教务扩展配置较干净", "detail": "未发现明显风险，可以继续补充真实业务数据做压力验证。"})
    return out


def _iter_teacher_events(tables: dict[str, list[dict[str, Any]]]) -> Iterable[dict[str, str]]:
    for table_key, columns in TEACHER_EVENT_COLUMNS.items():
        for idx, row in enumerate(tables.get(table_key, []), start=1):
            if table_key == "timetable_changes" and _is_inactive_status(row.get("状态")):
                continue
            for column in columns:
                for teacher in _split_names(row.get(column)):
                    yield {
                        "teacher": teacher,
                        "table": table_key,
                        "table_label": ACADEMIC_TABLES[table_key]["label"],
                        "row": str(idx),
                        "day": _row_day(row),
                        "slot": _row_slot(row),
                        "title": _event_title(table_key, row),
                    }


def _iter_room_events(tables: dict[str, list[dict[str, Any]]]) -> Iterable[dict[str, str]]:
    for table_key, columns in ROOM_COLUMNS.items():
        for idx, row in enumerate(tables.get(table_key, []), start=1):
            if table_key == "timetable_changes" and _is_inactive_status(row.get("状态")):
                continue
            for column in columns:
                for room in _split_names(row.get(column)):
                    yield {
                        "room": room,
                        "table": table_key,
                        "table_label": ACADEMIC_TABLES[table_key]["label"],
                        "row": str(idx),
                        "day": _row_day(row),
                        "slot": _row_slot(row),
                        "title": _event_title(table_key, row),
                    }


def _teacher_load(tables: dict[str, list[dict[str, Any]]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in _iter_teacher_events(tables):
        if event["table"] != "teacher_leave":
            counter[event["teacher"]] += 1
    return counter


def _room_usage(tables: dict[str, list[dict[str, Any]]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in _iter_room_events(tables):
        counter[event["room"]] += 1
    return counter


def _room_capacity_map(tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    out = {}
    for row in tables.get("rooms", []):
        room = str(row.get("场地") or "").strip()
        capacity = _to_int(row.get("容量"), 0)
        if room and capacity:
            out[room] = capacity
    return out


def _row_rooms(table_key: str, row: dict[str, Any]) -> list[str]:
    rooms: list[str] = []
    for column in ROOM_COLUMNS.get(table_key, []):
        rooms.extend(_split_names(row.get(column)))
    return list(dict.fromkeys(rooms))


def _event_size(row: dict[str, Any]) -> int:
    for key in ("报名人数", "学生人数", "预计人数", "参与人数"):
        value = _to_int(row.get(key), 0)
        if value:
            return value
    return 0


def _event_title(table_key: str, row: dict[str, Any]) -> str:
    for key in ("课程名称", "考试名称", "组合/层次", "教研组", "活动名称", "社团名称", "实验名称", "课题", "会议主题", "集会主题", "课程/对象", "赛事名称", "演练名称", "培训名称", "任务", "变更标题"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ACADEMIC_TABLES.get(table_key, {}).get("label", table_key)


def _row_day(row: dict[str, Any]) -> str:
    for key in ("新星期", "星期"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    for key in ("生效日期", "日期", "开始日期", "巡课日期"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _row_slot(row: dict[str, Any]) -> str:
    for key in ("新节次", "节次", "时段"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _same_time_window(left: dict[str, str], right: dict[str, str]) -> bool:
    if left["day"] and right["day"] and left["day"] != right["day"]:
        return False
    if left["slot"] and right["slot"] and not (_is_all_day(left["slot"]) or _is_all_day(right["slot"])) and left["slot"] != right["slot"]:
        return False
    return bool(left["day"] or right["day"] or left["slot"] or right["slot"])


def _short_event(event: dict[str, str]) -> str:
    return f"{event['table_label']}第{event['row']}行:{event['title']}"


def _is_all_day(slot: Any) -> bool:
    text = str(slot or "").strip()
    return text in {"全天", "全日", "上午", "下午", "晚间"}


def _is_pending(value: Any) -> bool:
    text = str(value or "").strip()
    return text in {"", "待审批", "待确认", "待分配", "待巡查", "待处理"}


def _is_confirmed(value: Any) -> bool:
    text = str(value or "").strip()
    return text in {"已审批", "已确认", "已通过", "已批准", "批准", "通过", "已发布", "生效", "已生效"}


def _is_inactive_status(value: Any) -> bool:
    text = str(value or "").strip()
    return text in {"已驳回", "驳回", "取消", "已取消", "作废", "已作废", "废弃"}


def _risk(severity: str, title: str, detail: str, suggestion: str, *, kind: str, refs: list[str]) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
        "kind": kind,
        "refs": refs,
    }


def _dedupe_risks(risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out = []
    for risk in risks:
        key = (str(risk.get("title")), str(risk.get("detail")), str(risk.get("kind")))
        if key in seen:
            continue
        seen.add(key)
        out.append(risk)
    return out


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in row.items() if str(k) != "row_index"}


def _split_names(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized = text.replace("，", "、").replace(",", "、").replace("/", "、").replace("；", "、").replace(";", "、")
    return [x.strip() for x in normalized.split("、") if x.strip()]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default
