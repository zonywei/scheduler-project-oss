from __future__ import annotations

import json

from scheduler.app.model_gateway import pseudonymize_teacher_context, replace_model_tokens


def test_teacher_anonymization_maps_the_complete_context_and_restores_unmentioned_teachers() -> None:
    redacted, aliases, restore_map = pseudonymize_teacher_context(
        "教师A与教师B存在冲突",
        ["教师A", "教师B", "教师C"],
    )

    assert len(aliases) == 2
    assert "教师A" not in redacted
    assert "教师B" not in redacted
    assert "教师C" not in redacted
    assert set(restore_map.values()) == {"教师A", "教师B", "教师C"}

    model_output = {"teachers": list(restore_map), "note": "教师代号_003需要一起复核"}
    restored = replace_model_tokens(model_output, restore_map)
    assert restored["teachers"] == ["教师A", "教师B", "教师C"]
    assert "教师C" in restored["note"]
    assert "教师代号_003" not in json.dumps(restored, ensure_ascii=False)
