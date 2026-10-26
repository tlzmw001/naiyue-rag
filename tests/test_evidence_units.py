"""Public evidence contracts against synthetic source text, without network."""

import hashlib
import importlib
import re
import socket

import pytest

from experiments.markdown_probe import load_sources

HEADER = '| 序号 | 用例名称 | 前提条件 | 测试步骤 | 预期结果 | 等级 | 设计者 | 测试结果 | 备注 |'
SEPARATOR = '| --- | --- | --- | --- | --- | --- | --- | --- | --- |'
ROW1 = '| TC-01 | 计算 | p=2<br>v=3 | 检查 `p*v` | 6 | P1 | SYNTHETIC |  | `field\\|missing` |'
ROW2 = '| TC-02 | 部分复用 | 沿用 TC-01 的 p；v=4 | 发起请求 | 8 | P1 | SYNTHETIC |  | 不继承步骤 |'
CASE_TEXT = f'# 合成用例\n\n## 维度一\n\n> 来源：需求 §1\n> 覆盖：计算\n\n{HEADER}\n{SEPARATOR}\n{ROW1}\n{ROW2}\n'


def source(text, role='module'):
    starts = [0] if text else []
    starts.extend(i + 1 for i, char in enumerate(text) if char == '\n' and i + 1 < len(text))
    return {'document_id': 'D1', 'relative_path': 'L1/example.md', 'role': role,
            'semantic_level': 'L1', 'directory_level': 'L1', 'text': text,
            'source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'line_starts': starts}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)


@pytest.fixture
def units_module():
    return importlib.import_module('experiments.evidence_units')


def assert_spans(src, units):
    for unit in units:
        for text, span in [(unit['body'], unit['body_span'])] + [
                (item['text'], item['span']) for item in unit['contexts']]:
            assert src['text'][span['start_char']:span['end_char']] == text
            assert span['source_sha256'] == src['source_sha256']
            assert span['line_start'] == src['text'][:span['start_char']].count('\n') + 1
            assert span['line_end'] == src['text'][:span['end_char'] - 1].count('\n') + 1


def test_formula_and_order_survive_in_one_evidence(units_module):
    src = source('# 系统\n\n## 公式\n\n```text\n# 代码中的标题\nresult=p*v\n```\n\n先用原始值计算，再校准。\n')
    units, diagnostics = units_module.build_units(src, 4000)
    assert not [d for d in diagnostics if d['severity'] == 'blocked']
    unit = next(u for u in units if 'result=p*v' in u['body'])
    assert '# 代码中的标题' in unit['body'] and '先用原始值计算，再校准。' in unit['body']
    assert unit['heading_path'] == ['# 系统', '## 公式']
    assert unit['kind'] == 'text' and unit['case_id'] is None and unit['case_fields'] == []
    assert 'header_path' in unit['component_metadata']
    assert_spans(src, units)


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_case_is_complete_with_distinct_context_locations(units_module, newline):
    src = source(CASE_TEXT.replace('\n', newline), 'historical_test_cases')
    units, diagnostics = units_module.build_units(src, 4000)
    assert not [d for d in diagnostics if d['severity'] == 'blocked']
    cases = [u for u in units if u['kind'] == 'test_case']
    assert [u['body'] for u in cases] == [ROW1, ROW2]
    assert all(len(u['case_fields']) == 9 for u in cases)
    assert cases[0]['case_fields'][8] == '`field\\|missing`'
    assert {c['context_kind'] for c in cases[0]['contexts']} >= {
        'document_title', 'dimension', 'columns', 'source_note'}
    assert [c['text'] for c in cases[0]['contexts'] if c['context_kind'] == 'source_note'] == [
        '> 来源：需求 §1', '> 覆盖：计算']
    assert ROW1 not in '\n'.join(u['body'] for u in units if u['kind'] == 'text')
    assert ROW2 not in '\n'.join(u['body'] for u in units if u['kind'] == 'text')
    assert_spans(src, units)


def test_partial_reference_not_expanded_into_other_case(units_module):
    units, _ = units_module.build_units(source(CASE_TEXT, 'historical_test_cases'), 4000)
    second = next(u for u in units if u['case_id'] == 'TC-02')
    assert second['body'] == ROW2 and '检查 `p*v`' not in second['rendered_text']
    assert '沿用 TC-01 的 p' in second['case_fields'][2]


def test_stable_id_bound_to_version_and_position(units_module):
    src = source(CASE_TEXT, 'historical_test_cases')
    first, _ = units_module.build_units(src, 4000)
    again, _ = units_module.build_units(src, 4000)
    assert first == again
    changed, _ = units_module.build_units(source(CASE_TEXT + '\n版本变化。', 'historical_test_cases'), 4000)
    assert {u['unit_id'] for u in first}.isdisjoint(u['unit_id'] for u in changed)


def test_rendered_budget_includes_source_and_context_without_truncation(units_module):
    units, diagnostics = units_module.build_units(source(CASE_TEXT, 'historical_test_cases'), 100)
    unit = next(u for u in units if u['case_id'] == 'TC-01')
    assert unit['body'] == ROW1 and ROW1 in unit['rendered_text']
    assert unit['rendered_characters'] == len(unit['rendered_text']) > len(ROW1)
    assert unit['rendered_text'] == units_module.render_unit(unit)
    assert unit['eligible'] is False
    assert any(d['category'] == 'single_evidence_over_budget' for d in diagnostics)


@pytest.mark.parametrize('fault', ['columns', 'header', 'dimension', 'separator', 'duplicate', 'multiline', 'pipe'])
def test_unsupported_case_structure_is_blocking(units_module, fault):
    text = CASE_TEXT
    if fault == 'columns': text = text.replace(ROW1, '| TC-01 | 缺列 |')
    if fault == 'header': text = text.replace(HEADER + '\n', '')
    if fault == 'dimension': text = text.replace('## 维度一\n', '')
    if fault == 'separator': text = text.replace(SEPARATOR, '| --- | --- |')
    if fault == 'duplicate': text = text.replace('TC-02', 'TC-01')
    if fault == 'multiline': text = text.replace(ROW1, ROW1[:20] + '\n' + ROW1[20:])
    if fault == 'pipe': text = text.replace('field\\|missing', 'field|missing')
    _, diagnostics = units_module.build_units(source(text, 'historical_test_cases'), 4000)
    assert any(d['category'] == 'unsupported_structure' and d['severity'] == 'blocked' for d in diagnostics)


@pytest.mark.parametrize('text', ['# 文档\n\n```text\n未关闭', '# 文档\n\n~~~text\nx\n~~~'])
def test_bad_fence_not_sent_to_component(units_module, monkeypatch, text):
    def unexpected(*args): raise AssertionError('component must not see unsupported fence')
    monkeypatch.setattr(units_module, 'split_candidate', unexpected)
    units, diagnostics = units_module.build_units(source(text), 4000)
    assert units == [] and any(d['category'] == 'unsupported_structure' for d in diagnostics)


@pytest.mark.parametrize('fault', ['zero', 'unmapped', 'ambiguous', 'exception'])
def test_component_failure_never_gets_fake_location(units_module, monkeypatch, fault):
    src = source('# 重复\n内容\n\n# 重复\n内容\n')
    def split(*args):
        if fault == 'exception': raise RuntimeError('private exception text')
        if fault == 'zero': return []
        return [{'chunk_text': '改写文本' if fault == 'unmapped' else '# 重复\n内容', 'native_metadata': {}}]
    monkeypatch.setattr(units_module, 'split_candidate', split)
    units, diagnostics = units_module.build_units(src, 4000)
    assert units == [] and any(d['severity'] == 'blocked' for d in diagnostics)
    assert 'private exception text' not in str(diagnostics)


def test_empty_and_stale_line_hint_are_separate(units_module):
    units, diagnostics = units_module.build_units(source(''), 4000)
    assert units == [] and diagnostics[0]['category'] == 'empty_source'
    src = source('# 文档\n\n> 索引：L999-L1005\n\n## 正文\n内容。\n')
    units, diagnostics = units_module.build_units(src, 4000)
    assert any(d['category'] == 'stale_header_line_range' and d['severity'] == 'warning' for d in diagnostics)
    assert all(u['eligible'] for u in units)
    assert_spans(src, units)


@pytest.mark.parametrize('limit', [0, -1, True, '4000'])
def test_invalid_limit_rejected(units_module, limit):
    with pytest.raises(ValueError, match='invalid_parameters'):
        units_module.build_units(source('# 文档'), limit)


def test_actual_mock_rows_and_all_source_spans(units_module):
    sources = [s for s in load_sources('examples/mock-v1') if s['document_id'] != 'MOCK-TASK-004']
    all_cases = []
    for src in sources:
        units, diagnostics = units_module.build_units(src, 4000)
        assert not [d for d in diagnostics if d['severity'] == 'blocked'], diagnostics
        assert_spans(src, units)
        cases = [u for u in units if u['kind'] == 'test_case']
        expected_rows = [line for line in src['text'].splitlines() if re.match(r'^\| TC-[\w-]+ \|', line)]
        assert [u['body'] for u in cases] == expected_rows
        assert all(u['eligible'] for u in units)
        all_cases.extend(cases)
    assert len(all_cases) == 12
