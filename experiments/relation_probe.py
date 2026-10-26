"""A3 explicit relations experiment; cache-only, source-grounded evidence."""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

from experiments.embedding_probe import ProbeError
from experiments.hybrid_probe import assemble_keywords, scope_key, write_json
from experiments.hybrid_probe import validate_config as validate_a2_config
from experiments.keyword_index import Tokenizer, search as keyword_search
from experiments.markdown_probe import new_run_id
from experiments.rank_fusion import fuse
from experiments.relation_index import build_index, write_index, load_index as load_relations, expand, limit, POLICY
from experiments.relation_retrieval import build_route, combine_routes
from experiments.vector_eval import load_queries, load_labels, evaluate, covered
from experiments.vector_index import load_corpus, load_index, read_json, read_rows, digest, search, pack_evidence
from experiments.vector_probe import check_deadline


def validate_config(config):
    if config.get('mode') not in ['build', 'replay'] or \
            (config['mode'] == 'replay' and not config.get('relation_run')):
        raise ProbeError('config', 'invalid_mode')
    if not isinstance(config.get('a2_run'), str) or not config['a2_run'].strip():
        raise ProbeError('config', 'invalid_a2_run')
    validate_a2_config(dict(config, mode='replay', keyword_run=config['a2_run']))
    if config.get('relation_policy') != POLICY:
        raise ProbeError('config', 'invalid_relation_policy')
    for name, maximum in [('seed_k', 5), ('max_seed_documents', 3), ('max_hops', 2),
                          ('max_related_documents', 8), ('per_document_k', 4), ('relation_k', 20),
                          ('max_graph_nodes', 64), ('max_edge_visits', 128)]:
        limit(config, name, maximum)


def baseline_recompute(config, corpus, vector_index, keywords, queries, tokenizer, started):
    prior = read_json(Path(config['a2_run'])/'summary.json', 'baseline')
    if prior['status'] != 'complete' or prior['corpus_fingerprint'] != corpus['fingerprint'] or \
            prior['index_id'] != vector_index['index_id'] or \
            Path(prior['source_vector_run']).resolve() != Path(config['vector_run']).resolve():
        raise ProbeError('baseline', 'baseline_mismatch')
    calculated, a1 = [], []
    for query in queries:
        check_deadline(config, started)
        ranked = search(vector_index, vector_index['query_vectors'][query['task_id']],
                        query['scope_ids'], query['exclude_ids'], config['candidate_k'])
        dense = {**query, **ranked, **pack_evidence(ranked['candidates'], config['max_context_chars']),
                 'index_id': vector_index['index_id'], 'elapsed_ms': 0}
        sparse = keyword_search(keywords[scope_key(query)], query['query'], tokenizer, config['candidate_k'])
        fused = fuse(dense['candidates'], sparse['candidates'], vector_index['units'], config['rrf_k'], config['candidate_k'])
        sparse = {**query, **sparse, **pack_evidence(sparse['candidates'], config['max_context_chars'])}
        hybrid = {**query, 'candidates': fused['candidates'], **pack_evidence(fused['candidates'], config['max_context_chars'])}
        calculated.append({**query, 'candidate_k': config['candidate_k'], 'index_id': vector_index['index_id'],
                           'dense': dense, 'sparse': sparse, 'hybrid': hybrid, 'union_candidates': fused['union_candidates']})
        a1.append(dense)
    original_a1 = read_rows(Path(config['vector_run'])/'results.jsonl', 'baseline')
    if [{k: v for k, v in r.items() if k != 'elapsed_ms'} for r in original_a1] != \
            [{k: v for k, v in r.items() if k != 'elapsed_ms'} for r in a1]:
        raise ProbeError('baseline', 'baseline_mismatch')
    original = read_rows(Path(config['a2_run'])/'results.jsonl', 'baseline')
    if [{k: v for k, v in r.items() if k != 'timings_ms'} for r in original] != calculated:
        raise ProbeError('baseline', 'baseline_mismatch')
    # Frozen original timing is historical; recomputation timing belongs to this run's summary.
    return original


def check_evaluation(config, rows, corpus, gold):
    metrics = []
    for row in rows:
        a2 = row['A2']
        metrics.append({'task_id': row['task_id'], 'A1': evaluate(a2['dense'], corpus, gold),
                        'BM25': evaluate(a2['sparse'], corpus, gold), 'A2': evaluate(a2['hybrid'], corpus, gold),
                        'union_recalled_ids': [eid for eid in gold['tasks'][row['task_id']]['required']
                                              if covered(gold['evidence'][eid], a2['union_candidates'])]})
    if metrics != read_json(Path(config['a2_run'])/'evaluation.json', 'baseline') or \
            [m['A1'] for m in metrics] != read_json(Path(config['vector_run'])/'evaluation.json', 'baseline'):
        raise ProbeError('baseline', 'baseline_mismatch')
    return [{'task_id': row['task_id'], 'A2': baseline['A2'],
             'relation_route': evaluate(row['relation_route'], corpus, gold), 'A3': evaluate(row['A3'], corpus, gold)}
            for row, baseline in zip(rows, metrics, strict=True)]


def build_report(state, rows, graph):
    lines = ['# A3已有关系＋分文档召回实际对照', '',
             f"状态：{state['status']}；模型请求：{state['attempt_count']}；网络尝试：{state['network_attempts']}",
             '完成以最后summary.json为准；缺少摘要的目录为部分产物。',
             '固定合成集、标签not_reviewed；变化包括配额/局部RRF/再融合，不归因纯连边收益。', '',
             '| 任务 | 路径 | Recall@20 | Coverage@8000 | 返回条/字符 |', '|---|---|---:|---:|---|']
    metrics = {m['task_id']: m for m in state['evaluation'] or []}
    for row in rows:
        for name, result in [('A2', row['A2']['hybrid']), ('relation_route', row['relation_route']), ('A3', row['A3'])]:
            m = metrics[row['task_id']][name]
            lines.append(f"| {row['task_id']} | {name} | {m['recall_at_20']} | {m['coverage_at_budget']} | "
                         f"{len(result['selected'])}/{result['context_characters']} |")
    edges = {e['edge_id']: e for e in graph['edges']} if graph else {}
    for row in rows:
        lines.extend(['', '## '+row['task_id'], '', row['query'], '',
                      '种子：'+json.dumps(row['expansion']['seeds'], ensure_ascii=False), '',
                      '| 关联文档 | 跳数 | 原边与遍历方向 |', '|---|---:|---|'])
        for doc in row['expansion']['related_documents']:
            path = doc['best_path']; descriptions = []
            for hop in path['hops']:
                edge = edges[hop['edge_id']]; span = edge['source_span']
                where = f"L{span['line_start']}" if span else 'filename-suffix-v1'
                descriptions.append(f"{edge['from_document_id']}→{edge['to_document_id']} {where} [{hop['direction']}]")
            lines.append(f"| {doc['document_id']} | {path['hop_count']} | {'; '.join(descriptions)} |")
        lines.extend(['', '````markdown', row['A3']['context_text'], '````'])
    lines.extend(['', '错误：'+json.dumps(state['sanitized_error'], ensure_ascii=False),
                  '模型usage/费用不适用；answerability=unknown，无真实资料/答案/MCP/生产质量证明。'])
    return '\n'.join(lines)+'\n'


def failure_analysis(rows, corpus, gold):
    lines = ['# A3逐条必要证据去留', '',
             '| 任务/证据 | 文档已关联 | 文档内排名 | 路由排名 | 最终排名 | A2返回 | A3返回 | 状态 |',
             '|---|---|---:|---:|---:|---|---|---|']
    for row in rows:
        for eid in gold['tasks'][row['task_id']]['required']:
            label = gold['evidence'][eid]; route = row['relation_route']; final = row['A3']
            associated = label['document_id'] in {d['document_id'] for d in row['expansion']['related_documents']}
            local = [u for d in route['documents'] for u in d['local_candidates']]
            positions = [next((u['rank'] for u in group if covered(label, [u])), None)
                         for group in [local, route['pool_candidates'], row['combined_union']]]
            old = covered(label, row['A2']['hybrid']['selected']); new = covered(label, final['selected'])
            if new: reason = 'returned'
            elif positions[2] is not None and positions[2] <= row['candidate_k']: reason = 'budget_excluded'
            elif positions[2] is not None: reason = 'final_fusion_excluded'
            elif positions[1] is not None: reason = 'route_limit_excluded'
            elif associated: reason = 'document_recall_excluded'
            else: reason = 'document_not_related_or_seed'
            lines.append(f"| {row['task_id']}/{eid} | {associated} | {positions[0]} | {positions[1]} | "
                         f"{positions[2]} | {old} | {new} | {reason} |")
    lines.extend(['', '关联只是线索；种子文档不作为新增目标。原始候选/配额/路径见results.jsonl。',
                  '名称配对在当前Mock已有显式引用支持，不能独立归因；Q04指标N/A、系统unknown。'])
    return '\n'.join(lines)+'\n'


def run(config, network_counter=None):
    started = time.monotonic(); validate_config(config)
    folder = Path(config['output_root']).resolve()/new_run_id()
    try: folder.mkdir(parents=True, exist_ok=False)
    except OSError: raise ProbeError('output', 'output_error') from None
    state = {'status': 'running', 'config': config, 'attempt_count': 0, 'network_attempts': None,
             'model_usage': None, 'model_cost_cny': None, 'evaluation': None, 'sanitized_error': None,
             'output_dir': str(folder)}
    rows, graph, analysis = [], None, None
    try:
        corpus = load_corpus(config['corpus_run'], config['dataset'])
        queries = load_queries(config['tasks'], corpus)
        index = load_index(config['vector_run'], corpus['fingerprint'], config)
        if set(index['query_hashes']) != {q['task_id'] for q in queries} or any(
                index['query_hashes'][q['task_id']] != digest(q['query'].encode()) for q in queries):
            raise ProbeError('cache', 'cache_mismatch')
        state.update(corpus_fingerprint=corpus['fingerprint'], index_id=index['index_id'])
        check_deadline(config, started)
        tokenizer = Tokenizer(folder/'jieba-cache')
        kw_config = dict(config, mode='replay', keyword_run=config['a2_run'])
        keywords, metadata = assemble_keywords(kw_config, folder, corpus, queries, tokenizer, started)
        state['keyword_reference'] = metadata
        began = time.monotonic()
        baseline = baseline_recompute(config, corpus, index, keywords, queries, tokenizer, started)
        state['baseline_recompute_ms'] = round((time.monotonic()-began)*1000, 3)
        check_deadline(config, started)
        origin = folder if config['mode'] == 'build' else Path(config['relation_run'])
        if config['mode'] == 'build':
            graph = build_index(corpus, config['dataset'], config)
            write_index(folder/'relations', graph)
        else:
            if read_json(origin/'summary.json', 'relation-cache')['status'] != 'complete':
                raise ProbeError('relation-cache', 'relation_cache_mismatch')
        graph = load_relations(origin/'relations', corpus, config['dataset'], config)
        state.update(relation_source_run=str(origin.resolve()), relation_edge_count=len(graph['edges']),
                     relation_diagnostic_count=len(graph['diagnostics']))
        if config['mode'] == 'replay':
            write_json(folder/'relation_reference.json', {'source_run': str(origin.resolve()),
                       'manifest_sha256': digest((origin/'relations/relation_manifest.json').read_bytes())})
        for query, a2 in zip(queries, baseline, strict=True):
            check_deadline(config, started); began = time.monotonic()
            expanded = expand(graph, a2['hybrid']['candidates'], corpus, query['scope_ids'], query['exclude_ids'], config)
            expansion_ms = (time.monotonic()-began)*1000
            check_deadline(config, started); began = time.monotonic()
            route = build_route(index, keywords[scope_key(query)], index['query_vectors'][query['task_id']],
                                query, expanded['related_documents'], tokenizer, config)
            recall_ms = (time.monotonic()-began)*1000
            check_deadline(config, started); began = time.monotonic()
            combined = combine_routes(a2['hybrid']['candidates'], route['candidates'], index['units'],
                                      config['rrf_k'], config['candidate_k'])
            route = {**query, **route, **pack_evidence(route['candidates'], config['max_context_chars'])}
            final = {**query, 'candidates': combined['candidates'],
                     **pack_evidence(combined['candidates'], config['max_context_chars'])}
            rows.append({**query, 'candidate_k': config['candidate_k'], 'A2': a2, 'expansion': expanded,
                         'relation_route': route, 'A3': final, 'combined_union': combined['union_candidates'],
                         'timings_ms': {'expansion': round(expansion_ms, 3), 'recall': round(recall_ms, 3),
                                        'combine_pack': round((time.monotonic()-began)*1000, 3)}})
            check_deadline(config, started)
        gold = load_labels(config['tasks'], corpus)
        state['evaluation'] = check_evaluation(config, rows, corpus, gold)
        analysis = failure_analysis(rows, corpus, gold)
        check_deadline(config, started); state['status'] = 'complete'
    except ProbeError as error:
        state.update(status='error', sanitized_error=error.record(), evaluation=None); rows = []
    except Exception:
        state.update(status='error', sanitized_error=ProbeError('pipeline', 'unexpected_error').record(), evaluation=None)
        rows = []
    state.update(network_attempts=network_counter[0] if network_counter is not None else None,
                 exit_code=0 if state['status'] == 'complete' else 2)
    try:
        if state['evaluation'] is not None:
            with (folder/'results.jsonl').open('x', encoding='utf-8') as handle:
                for row in rows: handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
            write_json(folder/'evaluation.json', state['evaluation'])
            with (folder/'failure-analysis.md').open('x', encoding='utf-8') as handle: handle.write(analysis)
        report = build_report(state, rows, graph)
        if state['status'] == 'complete': check_deadline(config, started)
        with (folder/'report.md').open('x', encoding='utf-8') as handle: handle.write(report)
        if state['status'] == 'complete': check_deadline(config, started)
        state['elapsed_ms'] = round((time.monotonic()-started)*1000, 3)
        write_json(folder/'summary.json', state)
    except (OSError, ValueError, TypeError):
        raise ProbeError('output', 'output_error') from None
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['mode', 'dataset', 'corpus-run', 'tasks', 'vector-run', 'a2-run', 'endpoint', 'model',
                 'output-root', 'bm25-method', 'tokenizer-policy', 'backend', 'relation-policy']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--relation-run')
    for name in ['dimensions', 'candidate-k', 'rrf-k', 'max-context-chars', 'deadline-seconds', 'seed-k',
                 'max-seed-documents', 'max-hops', 'max-related-documents', 'per-document-k', 'relation-k',
                 'max-graph-nodes', 'max-edge-visits']:
        parser.add_argument('--'+name, type=int, required=True)
    for name in ['bm25-k1', 'bm25-b']:
        parser.add_argument('--'+name, type=float, required=True)
    counter = [0]; original = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    def forbid(*args, **kwargs):
        counter[0] += 1; raise ProbeError('network', 'network_forbidden')
    try:
        socket.socket.connect = socket.socket.connect_ex = socket.getaddrinfo = forbid
        state = run(vars(parser.parse_args(argv)), counter)
    except ProbeError as error:
        print(str(error), file=sys.stderr); return 2
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = original
    print(f"status={state['status']} attempts={state['attempt_count']} network_attempts={state['network_attempts']} output={state['output_dir']}")
    if state['sanitized_error']: print(json.dumps(state['sanitized_error']), file=sys.stderr)
    return state['exit_code']


if __name__ == '__main__': raise SystemExit(main())
