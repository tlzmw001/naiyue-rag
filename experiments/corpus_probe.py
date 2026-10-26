"""Export common source-grounded evidence for later retrieval experiments."""

import argparse
import json
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path

from experiments.evidence_units import build_units
from experiments.markdown_probe import load_sources, new_run_id


def build_report(summary, units):
    lines = ['# 公共证据单元实际报告', '', f"状态：{summary['status']}；运行：{summary['run_id']}",
             f"源文件：{summary['source_count']}；单元：{summary['unit_count']}；用例：{summary['case_count']}",
             f"eligible：{summary['eligible_count']}；blocked诊断：{summary['blocked_count']}",
             f"最大渲染字符：{summary['max_rendered_characters']}；上限：{summary['parameters']['max_evidence_chars']}",
             '模型/网络调用：0；模型tokens与费用：不适用。', '',
             '所有内容完全合成，范围/结构/位置检查不能替代检索或真实资料评测。', '',
             '| 文档 | 单元 | 用例 | 诊断 |', '|---|---:|---:|---:|']
    for result in summary['results']:
        lines.append(f"| {result['document_id']} | {result['unit_count']} | {result['case_count']} | {len(result['diagnostics'])} |")
    cases = [unit for unit in units if unit['kind'] == 'test_case']
    if cases:
        sample = max(cases, key=lambda unit: len(unit['body']))
        lines.extend(['', '## 最长用例实际证据', '', '````markdown', sample['rendered_text'], '````'])
    formula = next((u for u in units if 'pv_short_raw = ' in u['body']), None)
    if formula:
        lines.extend(['', '## 公式与顺序实际证据', '', '````markdown', formula['rendered_text'], '````'])
    lines.extend(['', '## 所有诊断', '', '```json',
                  json.dumps(summary['diagnostics'], ensure_ascii=False, indent=2), '```', '',
                  '未建索引/图，未运行A1–B1，未调用Embedding/GLM，未验证LightRAG共享片段或远端真实材料。',
                  '源范围来自实际文件，不使用手写行号或任务标签；超限单元原样导出但eligible=false。'])
    return '\n'.join(lines) + '\n'


def run(dataset, include_ids, exclude_ids, max_evidence_chars, output_root):
    began = time.perf_counter()
    if type(max_evidence_chars) is not int or max_evidence_chars <= 0:
        raise ValueError('invalid_parameters: max_evidence_chars')
    for ids in [include_ids, exclude_ids]:
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError('invalid_parameters: scope_ids')
    if set(include_ids) & set(exclude_ids):
        raise ValueError('conflicting_scope')
    try:
        sources = load_sources(dataset)
    except (ValueError, OSError) as error:
        # Existing reader has public source detail; expose only its fixed category here.
        category = str(error).partition(':')[0]
        allowed = {'read_manifest', 'read_source', 'invalid_utf8', 'hash_mismatch',
                   'path_outside_knowledge', 'duplicate_document_id', 'invalid_source_record'}
        raise ValueError('source_error: ' + (category if category in allowed else type(error).__name__)) from None
    identities = {source['document_id'] for source in sources}
    if not set(include_ids + exclude_ids) <= identities:
        raise ValueError('unknown_document_id')
    selected = [s for s in sources if (not include_ids or s['document_id'] in include_ids)
                and s['document_id'] not in exclude_ids]
    if not selected:
        raise ValueError('empty_scope')
    run_id = new_run_id()
    folder = Path(output_root).resolve() / run_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except OSError:
        raise ValueError('output_error: create_directory') from None
    summary = {'schema_version': 1, 'run_id': run_id, 'status': 'complete', 'output_dir': str(folder),
               'python': platform.python_version(), 'versions': {'llama-index-core': version('llama-index-core')},
               'parameters': {'dataset': str(Path(dataset).resolve()), 'include_ids': include_ids,
                              'exclude_ids': exclude_ids, 'max_evidence_chars': max_evidence_chars,
                              'length_unit': 'unicode_characters', 'include_metadata': True,
                              'include_prev_next_rel': False},
               'source_count': len(selected), 'results': [], 'diagnostics': [],
               'model_calls': 0, 'network_calls': 0, 'model_tokens': None, 'cost': None}
    units, registry = [], []
    for source in selected:
        made, diagnostics = build_units(source, max_evidence_chars)
        units.extend(made)
        summary['diagnostics'].extend(diagnostics)
        summary['results'].append({'document_id': source['document_id'], 'unit_count': len(made),
                                   'case_count': sum(u['kind'] == 'test_case' for u in made),
                                   'diagnostics': diagnostics})
        record = {key: value for key, value in source.items() if key not in ('text', 'line_starts')}
        record['line_count'] = len(source['line_starts'])
        record['character_count'] = len(source['text'])
        registry.append(record)
    summary.update(unit_count=len(units), case_count=sum(u['kind'] == 'test_case' for u in units),
                   eligible_count=sum(u['eligible'] for u in units),
                   blocked_count=sum(d['severity'] == 'blocked' for d in summary['diagnostics']),
                   max_rendered_characters=max((u['rendered_characters'] for u in units), default=0))
    if summary['blocked_count']:
        summary['status'] = 'blocked'
    summary['exit_code'] = 0 if summary['status'] == 'complete' else 2
    try:
        for name, records in [('sources.jsonl', registry), ('units.jsonl', units)]:
            with (folder / name).open('x', encoding='utf-8') as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
        summary['elapsed_ms'] = round((time.perf_counter() - began) * 1000, 3)
        with (folder / 'report.md').open('x', encoding='utf-8') as handle:
            handle.write(build_report(summary, units))
        with (folder / 'summary.json').open('x', encoding='utf-8') as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
    except (OSError, ValueError, TypeError):
        raise ValueError('output_error: write_files') from None
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--include-document-id', action='append', default=[])
    parser.add_argument('--exclude-document-id', action='append', required=True)
    parser.add_argument('--max-evidence-chars', type=int, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run(args.dataset, args.include_document_id, args.exclude_document_id,
                      args.max_evidence_chars, args.output_root)
    except (ValueError, OSError) as error:
        print(f'corpus_error: {error}', file=sys.stderr)
        return 2
    print(f"status={summary['status']} sources={summary['source_count']} units={summary['unit_count']} "
          f"cases={summary['case_count']} blocked={summary['blocked_count']} output={summary['output_dir']}")
    return summary['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
