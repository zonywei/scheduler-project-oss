from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.academic_affairs import (
    default_academic_affairs_payload,
    normalize_academic_affairs,
    summarize_academic_affairs,
)
from scheduler.app.academic_affairs_io import build_academic_table_template_csv, parse_academic_table_csv
from scheduler.app.academic_affairs_io import build_academic_table_template_xlsx, parse_academic_table_xlsx
from scheduler.app.academic_affairs_io import build_academic_workbook_template_xlsx, parse_academic_workbook_xlsx
from scheduler.app.config_service import preview_academic_affairs_payload


def test_academic_schema_covers_50_capability_items():
    payload = default_academic_affairs_payload()
    summary = summarize_academic_affairs(payload)

    assert len(summary["schema"]) >= 26
    assert len(summary["capability_items"]) == 50
    assert {"teacher_leave", "lab_reservations", "campus_supervision"} <= set(summary["schema"])
    assert summary["metrics"]["health_score"] == 100


def test_normalize_keeps_new_tables_and_settings():
    payload = normalize_academic_affairs(
        {
            "tables": {
                "teacher_leave": [{"row_index": 1, "教师": "教师C", "星期": "星期一", "时段": "上午1"}],
                "lab_reservations": [{"实验名称": "光学实验", "任课教师": "教师B"}],
            },
            "settings": {"teacher_daily_task_warning_threshold": 3},
        }
    )

    assert payload["tables"]["teacher_leave"][0]["教师"] == "教师C"
    assert "row_index" not in payload["tables"]["teacher_leave"][0]
    assert payload["tables"]["lab_reservations"][0]["实验名称"] == "光学实验"
    assert payload["settings"]["teacher_daily_task_warning_threshold"] == 3


def test_academic_summary_detects_room_teacher_leave_and_capacity_risks():
    payload = default_academic_affairs_payload()
    tables = payload["tables"]
    tables["rooms"] = [{"场地": "实验楼101", "类型": "实验室", "容量": "30"}]
    tables["teacher_leave"] = [{"教师": "教师C", "星期": "星期一", "时段": "上午1", "状态": "已审批"}]
    tables["lab_reservations"] = [
        {"实验名称": "光学实验", "星期": "星期一", "时段": "上午1", "任课教师": "教师C", "实验室": "实验楼101", "准备员": ""},
    ]
    tables["public_lessons"] = [
        {"课题": "公开课", "星期": "星期一", "节次": "上午1", "开课教师": "教师C", "听课教师": "", "地点": "实验楼101"},
    ]
    tables["club_activities"] = [
        {"社团名称": "机器人社", "星期": "星期一", "时段": "上午1", "指导教师": "教师D", "地点": "实验楼101", "容量": "20", "报名人数": "45"},
    ]

    summary = summarize_academic_affairs(payload)
    titles = {risk["title"] for risk in summary["risks"]}

    assert "场地同一时段重复占用" in titles
    assert "请假日志与已排任务冲突" in titles
    assert "课后服务存在待确认事项" not in titles
    assert any("容量" in title for title in titles)
    assert summary["metrics"]["room_conflicts"] >= 1
    assert summary["metrics"]["capacity_warnings"] >= 1
    assert summary["metrics"]["health_score"] < 100


def test_academic_summary_detects_staffing_pending_and_teacher_load():
    payload = default_academic_affairs_payload()
    payload["settings"]["teacher_daily_task_warning_threshold"] = 2
    tables = payload["tables"]
    tables["exam_duties"] = [
        {"考试名称": "期中考试", "星期": "星期二", "时段": "上午", "科目": "数学", "考场": "101", "所需监考数": "2", "已排监考教师": "教师B", "状态": "待确认"},
    ]
    tables["lunch_duty"] = [
        {"星期": "星期二", "时段": "午休", "区域": "食堂", "值守教师": "", "所需人数": "2", "已排人数": "1", "状态": "待确认"},
    ]
    tables["teaching_research"] = [
        {"教研组": "数学组", "星期": "星期二", "时段": "下午4", "参与教师": "教师B", "地点": "会议室", "状态": "待确认"},
    ]

    summary = summarize_academic_affairs(payload)
    titles = {risk["title"] for risk in summary["risks"]}

    assert "监考教师数量不足" in titles
    assert "午餐/午休值守人数不足" in titles
    assert "教师单日教务任务偏多" in titles
    assert summary["metrics"]["pending_items"] >= 3
    assert summary["recommendations"]


def test_timetable_changes_have_manual_adjustment_summary_and_conflict_risks():
    payload = default_academic_affairs_payload()
    payload["tables"]["timetable_changes"] = [
        {
            "变更标题": "初一1班数学调课",
            "班级": "初一1班",
            "原星期": "星期一",
            "原节次": "上午1",
            "原学科": "数学",
            "原教师": "教师C",
            "新星期": "星期二",
            "新节次": "上午2",
            "新学科": "数学",
            "新教师": "教师B",
            "审批人": "教务主任",
            "状态": "已审批",
        },
        {
            "变更标题": "初一2班语文调课",
            "班级": "初一2班",
            "原星期": "星期三",
            "原节次": "下午1",
            "原学科": "语文",
            "原教师": "教师D",
            "新星期": "星期二",
            "新节次": "上午2",
            "新学科": "语文",
            "新教师": "教师B",
            "审批人": "教务主任",
            "状态": "已审批",
        },
        {
            "变更标题": "初一1班英语调课",
            "班级": "初一1班",
            "原星期": "星期四",
            "原节次": "上午3",
            "原学科": "英语",
            "原教师": "教师E",
            "新星期": "星期二",
            "新节次": "上午2",
            "新学科": "英语",
            "新教师": "教师H",
            "审批人": "教务主任",
            "状态": "已审批",
        },
    ]

    summary = summarize_academic_affairs(payload)
    titles = {risk["title"] for risk in summary["risks"]}

    assert "调课后教师同一时段冲突" in titles
    assert "调课后班级同一时段冲突" in titles
    assert summary["metrics"]["timetable_change_rows"] == 3
    assert summary["metrics"]["manual_change_conflicts"] == 2
    assert summary["manual_adjustment"]["total"] == 3
    assert summary["manual_adjustment"]["approved"] == 3
    assert summary["manual_adjustment"]["ready"] is False


def test_timetable_changes_detect_noop_and_missing_approval():
    payload = default_academic_affairs_payload()
    payload["tables"]["timetable_changes"] = [
        {
            "变更标题": "初二1班数学调课",
            "班级": "初二1班",
            "原星期": "星期一",
            "原节次": "上午1",
            "原学科": "数学",
            "原教师": "教师C",
            "新星期": "星期一",
            "新节次": "上午1",
            "新学科": "数学",
            "新教师": "教师C",
            "审批人": "",
            "状态": "已通过",
        }
    ]

    summary = summarize_academic_affairs(payload)
    titles = {risk["title"] for risk in summary["risks"]}

    assert "调课单没有实际变更" in titles
    assert "已通过调课单缺少审批人" in titles
    assert summary["manual_adjustment"]["noop_changes"] == 1
    assert summary["manual_adjustment"]["missing_approvals"] == 1


def test_academic_affairs_csv_template_and_import_round_trip():
    template = build_academic_table_template_csv("exam_duties")
    assert template.startswith("\ufeff".encode("utf-8"))
    text = template.decode("utf-8-sig")
    assert "考试名称,日期,星期,时段,科目,考场,所需监考数" in text

    csv_text = (
        "考试名称, 日期,星期,时段,科目,考场,所需监考数,已排监考教师,特殊要求,状态,额外列\n"
        "期中考试,2026-05-06,星期三,上午,数学,101,2,教师C、教师B,,已确认,导入备注\n"
    )
    imported = parse_academic_table_csv("exam_duties", csv_text)

    assert imported["persisted"] is False
    assert imported["table"] == "exam_duties"
    assert imported["row_count"] == 1
    assert imported["rows"][0]["考试名称"] == "期中考试"
    assert imported["rows"][0]["日期"] == "2026-05-06"
    assert imported["rows"][0]["考场"] == "101"
    assert "额外列" in imported["ignored_columns"]


def test_academic_affairs_csv_import_rejects_missing_required_columns():
    try:
        parse_academic_table_csv("rooms", "场地,容量\n综合楼报告厅,300\n")
    except ValueError as exc:
        assert "缺少必需列" in str(exc)
        assert "类型" in str(exc)
    else:
        raise AssertionError("CSV without schema columns should be rejected")


def test_academic_affairs_xlsx_template_imports_as_preview():
    template = build_academic_table_template_xlsx("rooms")
    assert template.startswith(b"PK")

    imported = parse_academic_table_xlsx("rooms", template)

    assert imported["persisted"] is False
    assert imported["table"] == "rooms"
    assert imported["row_count"] == 1
    assert imported["rows"][0]["类型"] == "普通教室"
    assert imported["message"] == "已解析 1 行，请核对后保存教务配置。"


def test_academic_affairs_workbook_template_imports_multiple_tables_as_preview():
    template = build_academic_workbook_template_xlsx()
    assert template.startswith(b"PK")

    imported = parse_academic_workbook_xlsx(template)

    assert imported["schema_version"] == "scheduler.academic_affairs_workbook_import.v1"
    assert imported["persisted"] is False
    assert imported["table_count"] >= 26
    assert imported["row_count"] >= imported["table_count"]
    assert "rooms" in imported["tables"]
    assert "exam_duties" in imported["tables"]
    assert imported["tables"]["rooms"][0]["类型"] == "普通教室"
    assert imported["table_results"][0]["row_count"] >= 1
    assert imported["import_summary"]["schema_version"] == "scheduler.academic_affairs_import_summary.v1"
    assert imported["import_summary"]["table_count"] == imported["table_count"]
    assert imported["import_summary"]["row_count"] == imported["row_count"]
    assert imported["import_summary"]["save_required"] is True
    assert imported["import_summary"]["message"] == "已导入到页面，尚未保存，保存后才会进入正式配置。"
    assert imported["message"] == f"已解析 {imported['table_count']} 张教务表、{imported['row_count']} 行，请核对后保存教务配置。"


def test_academic_affairs_preview_recomputes_risks_without_persisting():
    payload = default_academic_affairs_payload()
    payload["tables"]["exam_duties"] = [
        {"考试名称": "期末考试", "星期": "星期四", "时段": "上午", "科目": "物理", "考场": "201", "所需监考数": "2", "已排监考教师": "教师C", "状态": "待确认"},
    ]

    preview = preview_academic_affairs_payload({"academic_affairs": payload})
    titles = {risk["title"] for risk in preview["summary"]["risks"]}

    assert preview["persisted"] is False
    assert preview["summary"]["metrics"]["exam_rows"] == 1
    assert "监考教师数量不足" in titles
    assert preview["summary"]["metrics"]["health_score"] < 100
