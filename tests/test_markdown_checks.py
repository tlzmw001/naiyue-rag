"""Diagnostics must detect lost structure, even when the runner succeeds."""

import hashlib
import importlib
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures/markdown_edge_cases.md"


@pytest.fixture
def checks():
    return importlib.import_module("experiments.markdown_checks")


def source(text, role="historical_test_cases"):
    starts, offset = [], 0
    for line in text.splitlines(keepends=True):
        starts.append(offset)
        offset += len(line)
    return {"text": text, "line_starts": starts, "document_id": "D1", "relative_path": "sample.md",
            "role": role, "source_sha256": hashlib.sha256(text.encode()).hexdigest()}


def chunks(*texts):
    return [{"ordinal": i, "chunk_text": text, "native_metadata": {}} for i, text in enumerate(texts)]


def select(probes, prefix):
    return [p for p in probes if p["probe_id"].startswith(prefix)]


def test_whole_case_rows_columns_dimension_and_context_preserved(checks):
    text = FIXTURE.read_text()
    probes = checks.inspect_document(source(text), chunks(text))
    for kind in ["case_row/", "case_header/", "case_dimension/", "case_context/", "case_reference/"]:
        found = select(probes, kind)
        assert found
        assert all(p["status"] == "pass" for p in found)
    assert len(select(probes, "case_row/")) == 2
    assert any("unsupported_structure" in p["reason"] for p in probes)


def test_split_row_is_failure_even_if_joining_chunks_recovers_text(checks):
    text = FIXTURE.read_text()
    row = next(line for line in text.splitlines() if line.startswith("| TC-01 |"))
    cut = row.index("| 预") if "| 预" in row else len(row) // 2
    probes = checks.inspect_document(source(text), chunks(row[:cut], row[cut:]))
    assert select(probes, "case_row/TC-01")[0]["status"] == "fail"


def test_header_dimension_context_checked_separately(checks):
    text = FIXTURE.read_text()
    lines = text.splitlines()
    row = next(line for line in lines if line.startswith("| TC-01 |"))
    header = next(line for line in lines if line.startswith("| 序号 |"))
    heading = "## 维度一：完整用例"
    probes = checks.inspect_document(source(text), chunks(row))
    assert select(probes, "case_row/TC-01")[0]["status"] == "pass"
    for kind in ["case_header/TC-01", "case_dimension/TC-01", "case_context/TC-01"]:
        assert select(probes, kind)[0]["status"] == "fail"
    probes = checks.inspect_document(source(text), chunks(heading + "\n" + header + "\n" + row))
    assert select(probes, "case_header/TC-01")[0]["status"] == "pass"
    assert select(probes, "case_dimension/TC-01")[0]["status"] == "pass"
    assert select(probes, "case_context/TC-01")[0]["status"] == "fail"


def test_case_dimension_requires_header_and_row_in_same_chunk(checks):
    text = FIXTURE.read_text()
    row = next(line for line in text.splitlines() if line.startswith("| TC-01 |"))
    probes = checks.inspect_document(source(text), chunks("## 维度一：完整用例\n" + row))
    assert select(probes, "case_dimension/TC-01")[0]["status"] == "fail"


def test_inline_code_break_and_escaped_pipe_not_silently_lost(checks):
    text = FIXTURE.read_text()
    changed = text.replace("<br>", " ").replace("`field\\|missing`", "field-missing")
    probes = checks.inspect_document(source(text), chunks(changed))
    for kind in ["inline_break/", "inline_code/", "escaped_pipe/"]:
        assert any(p["status"] == "fail" for p in select(probes, kind))


def test_link_and_fenced_block_loss_detected(checks):
    text = FIXTURE.read_text()
    changed = text.replace("[需求](requirement.md)", "需求").replace("result = p * v", "")
    probes = checks.inspect_document(source(text), chunks(changed))
    assert all(p["status"] == "fail" for p in select(probes, "link/"))
    assert all(p["status"] == "fail" for p in select(probes, "code_block/"))


def test_heading_inside_code_not_used_as_case_dimension(checks):
    text = FIXTURE.read_text()
    probes = checks.inspect_document(source(text), chunks(text))
    dimensions = select(probes, "case_dimension/")
    assert all(p["expected_text"] == "## 维度一：完整用例" for p in dimensions)


def test_stale_header_is_warning_with_actual_source_location(checks):
    text = "# 标题\n> 索引：§1（L999-L1005）\n\n## 正文\n内容\n"
    probes = checks.inspect_document(source(text, "historical_requirement"), chunks(text))
    warning = select(probes, "source_warning/")[0]
    assert warning["status"] == "fail"
    assert "stale_header_line_range" in warning["reason"]
    assert warning["expected_source_spans"][0]["line_start"] == 2


def test_document_ids_are_not_interpreted_as_line_ranges(checks):
    text = "# 合成\n> 文档ID：MOCK-L0-001\n> 相关ID：MOCK-L2-001\n> 索引：（L999-L1005）\n"
    probes = checks.inspect_document(source(text, "module"), chunks(text))
    warnings = select(probes, "source_warning/")
    assert len(warnings) == 1
    assert warnings[0]["expected_text"] == "L999-L1005"


def test_non_case_role_does_not_infer_cases_from_folder_or_table(checks):
    probes = checks.inspect_document(source(FIXTURE.read_text(), "module"), chunks(FIXTURE.read_text()))
    assert not select(probes, "case_row/")


def test_empty_source_is_not_applicable(checks):
    probes = checks.inspect_document(source(""), [])
    assert len(probes) == 1
    assert probes[0]["status"] == "not_applicable"
    assert probes[0]["reason"] == "empty_source"


def test_partial_reference_retained_without_inheriting_fields(checks):
    text = FIXTURE.read_text()
    row = next(line for line in text.splitlines() if line.startswith("| TC-02 |"))
    probes = checks.inspect_document(source(text), chunks(row))
    reference = select(probes, "case_reference/TC-02")[0]
    assert reference["status"] == "pass"
    assert "沿用 TC-01 的 p；另设 v=10" in reference["expected_text"]
    assert "p=0.2" not in reference["expected_text"]


def test_unsupported_multiline_row_not_claimed_complete(checks):
    text = "## 维度\n| TC-01 | 标题 | 条件\n步骤 | 结果 | P1 | A | | 备注 |\n"
    probes = checks.inspect_document(source(text), chunks(text))
    assert not select(probes, "case_row/")
    assert any("unsupported_structure" in p["reason"] for p in probes)
