"""A2 offline BM25/RRF comparison using an immutable A1 vector cache."""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

from experiments.embedding_probe import ProbeError
from experiments.keyword_index import Tokenizer, TOKEN_POLICY, parameters, build_index as keyword_build
from experiments.keyword_index import load_index as keyword_load, write_index as keyword_write, search as keyword_search
from experiments.markdown_probe import new_run_id
from experiments.rank_fusion import fuse
from experiments.vector_eval import evaluate, load_labels, load_queries, covered
from experiments.vector_index import digest, load_corpus, load_index, search, pack_evidence, read_json, read_rows, make_index_text
from experiments.vector_probe import check_deadline


def validate_config(config):
    parameters(config)
    if config.get('mode') not in ['build', 'replay'] or \
            (config['mode'] == 'replay' and not config.get('keyword_run')):
        raise ProbeError('config', 'invalid_mode')
    for key, maximum in [('candidate_k', 20), ('max_context_chars', 8000), ('deadline_seconds', 180)]:
        if type(config.get(key)) is not int or not 0 < config[key] <= maximum:
            raise ProbeError('config', 'invalid_' + key)
    if type(config.get('rrf_k')) is not int or config['rrf_k'] != 60:
        raise ProbeError('config', 'invalid_rrf_k')
    for key in ['dataset', 'corpus_run', 'tasks', 'vector_run', 'output_root', 'endpoint', 'model']:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ProbeError('config', 'invalid_' + key)
    if type(config.get('dimensions')) is not int or config['dimensions'] != 2048:
        raise ProbeError('config', 'invalid_dimensions')


def without_elapsed(rows):
    return [{k: v for k, v in r.items() if k != 'elapsed_ms'} for r in rows]


def write_json(path, data):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, allow_nan=False, indent=2)


def scope_key(query):
    scope = {'scope_ids': sorted(query['scope_ids']) if query['scope_ids'] is not None else None,
             'exclude_ids': sorted(query['exclude_ids'])}
    return digest(json.dumps(scope, sort_keys=True).encode())


def assemble_keywords(config, folder, corpus, queries, tokenizer, started):
    unique = {scope_key(q): q for q in queries}
    descriptor = {'schema_version': 1, 'fingerprint': corpus['fingerprint'], 'identity': tokenizer.identity,
                  'parameters': parameters(config), 'scope_keys': sorted(unique)}
    origin = folder if config['mode'] == 'build' else Path(config['keyword_run'])
    header = None
    if config['mode'] == 'replay':
        try:
            if read_json(origin/'summary.json')['status'] != 'complete':
                raise ValueError('incomplete keyword run')
            header = read_json(origin/'keyword_manifest.json')
            if header['status'] != 'complete' or any(header.get(k) != v for k, v in descriptor.items()) or \
                    set(header['scopes']) != set(unique):
                raise ValueError('keyword identities/scopes')
        except Exception:
            raise ProbeError('keyword-cache', 'keyword_cache_mismatch') from None
    indices, manifests = {}, {}
    for key, query in unique.items():
        check_deadline(config, started)
        root = origin/'keyword-scopes'/key
        if config['mode'] == 'build':
            index = keyword_build(corpus, query['scope_ids'], query['exclude_ids'], tokenizer, config)
            check_deadline(config, started)
            keyword_write(root, index)
        else:
            if digest((root/'manifest.json').read_bytes()) != header['scopes'][key]:
                raise ProbeError('keyword-cache', 'keyword_cache_mismatch')
        check_deadline(config, started)
        indices[key] = keyword_load(root, corpus, query['scope_ids'], query['exclude_ids'], tokenizer, config)
        if config['mode'] == 'build':
            for q in queries:
                if scope_key(q) != key or not index['N']:
                    continue
                terms = tokenizer.tokenize(q['query'], query=True)
                if terms and index['bm25'].get_scores(terms).tolist() != indices[key]['bm25'].get_scores(terms).tolist():
                    raise ProbeError('keyword-cache', 'keyword_roundtrip_mismatch')
        manifests[key] = digest((root/'manifest.json').read_bytes())
        check_deadline(config, started)
    result = {**descriptor, 'status': 'complete', 'scopes': manifests,
              'source_keyword_run': str(origin.resolve())}
    if config['mode'] == 'build':
        write_json(folder/'keyword_manifest.json', result)
    else:
        write_json(folder/'keyword_reference.json', result)
    # Full token trace is derived from the same 52 inputs, independent of any labels.
    with (folder/'tokens.jsonl').open('x', encoding='utf-8') as handle:
        for unit in corpus['units']:
            text = make_index_text(unit)
            handle.write(json.dumps({'unit_id': unit['unit_id'], 'input_sha256': digest(text.encode()),
                                     'tokens': tokenizer.tokenize(text)}, ensure_ascii=False)+'\n')
    return indices, {'scope_count': len(indices), 'source_keyword_run': str(origin.resolve()),
                     'roundtrip_query_count': len(queries) if config['mode'] == 'build' else None,
                     'scopes': {key: {k: index[k] for k in ['N', 'avgdl', 'vocab_count', 'scope']}
                                for key, index in indices.items()}}


def build_report(state, results):
    lines = ['# A2 BM25＋RRF实际对照', '', f"状态：{state['status']}；模式：{state['config']['mode']}",
             f"模型请求：{state['attempt_count']}；网络尝试：{state['network_attempts']}",
             '模型usage/本轮费用不适用；仅合成固定集、标签not_reviewed，不作为真实业务通过。', '',
             '运行完成以最后写入的summary.json.status=complete为准；缺少摘要的目录为部分产物。', '',
             '| 任务 | 路径 | Recall@10 | Recall@20 | Coverage@8000 | 返回条/字符 |',
             '|---|---|---:|---:|---:|---|']
    metrics = {m['task_id']: m for m in state['evaluation'] or []}
    for row in results:
        for name, key in [('A1', 'dense'), ('BM25', 'sparse'), ('A2', 'hybrid')]:
            metric = metrics[row['task_id']][name]
            lines.append(f"| {row['task_id']} | {name} | {metric['recall_at_10']} | {metric['recall_at_20']} | "
                         f"{metric['coverage_at_budget']} | {len(row[key]['selected'])}/{row[key]['context_characters']} |")
    for row in results:
        lines.extend(['', '## '+row['task_id'], '', row['query'], '',
                      '查询词项：'+json.dumps(row['sparse']['query_tokens'], ensure_ascii=False),
                      f"范围比较：dense={row['dense']['compared_count']}，sparse={row['sparse']['compared_count']}；"
                      f"union={len(row['union_candidates'])}，fused={len(row['hybrid']['candidates'])}", '',
                      '| RRF排名 | 文档/正文行 | dense排名/cosine | sparse排名/BM25 | 已返回 |',
                      '|---:|---|---|---|---|'])
        selected = {r['unit_id'] for r in row['hybrid']['selected']}
        for unit in row['union_candidates']:
            info, span = unit['retrieval_info'], unit['body_span']
            lines.append(f"| {unit['rank']} | {unit['document_id']} L{span['line_start']}-{span['line_end']} | "
                         f"{info['dense_rank']}/{info['cosine']} | {info['sparse_rank']}/{info['bm25_score']} | "
                         f"{unit['unit_id'] in selected} |")
        lines.extend(['', '````markdown', row['hybrid']['context_text'], '````'])
    lines.extend(['', '错误：'+json.dumps(state['sanitized_error'], ensure_ascii=False),
                  'answerability=unknown；没有关系扩展、重排、图、答案、MCP或真实资料验证。',
                  'deadline为阶段协作检查，不保证硬中断CPU函数；网络观测仅限单线程实验CLI。'])
    return '\n'.join(lines)+'\n'


def failure_analysis(results, metrics, corpus, gold):
    lines = ['# A2必要证据逐项诊断', '', 'gold只在检索完成后使用；历史命中不等于现行规则。', '',
             '| 任务/证据 | dense排名 | sparse排名 | RRF排名 | A1返回 | A2返回 | 状态 |',
             '|---|---:|---:|---:|---|---|---|']
    for row in results:
        for eid in gold['tasks'][row['task_id']]['required']:
            label = gold['evidence'][eid]
            rankings = []
            for group in [row['dense']['candidates'], row['sparse']['candidates'], row['union_candidates']]:
                rankings.append(next((u['rank'] for u in group if covered(label, [u])), None))
            old = covered(label, row['dense']['selected']); new = covered(label, row['hybrid']['selected'])
            if new: reason = 'returned'
            elif rankings[2] is None: reason = 'not_in_union'
            elif rankings[2] > row['candidate_k']: reason = 'fusion_excluded'
            else: reason = 'budget_excluded'
            lines.append(f"| {row['task_id']}/{eid} | {rankings[0]} | {rankings[1]} | {rankings[2]} | {old} | {new} | {reason} |")
    lines.extend(['', '## 逐题变化与边界', ''])
    for metric in metrics:
        old, new = metric['A1'], metric['A2']
        lines.append(f"- {metric['task_id']}：Recall20 {old['recall_at_20']}→{new['recall_at_20']}；"
                     f"Coverage {old['coverage_at_budget']}→{new['coverage_at_budget']}；"
                     f"未召回={new['not_recalled']}；预算遗漏={new['budget_excluded']}。")
    lines.extend(['', '没有按gold调参数。未标注内容不自动判为无关，Q04指标N/A、系统unknown。',
                  '本次只支持或反对该固定配置的合成集表现，不证明真实全库、无答案识别或生产能力。'])
    return '\n'.join(lines)+'\n'


def run(config, network_counter=None):
    started = time.monotonic(); validate_config(config)
    folder = Path(config['output_root']).resolve()/new_run_id()
    try: folder.mkdir(parents=True, exist_ok=False)
    except OSError: raise ProbeError('output', 'output_error') from None
    state = {'status': 'running', 'config': config, 'attempt_count': 0, 'network_attempts': None,
             'model_usage': None, 'model_cost_cny': None, 'evaluation': None, 'sanitized_error': None,
             'output_dir': str(folder)}
    results, analysis = [], None
    try:
        corpus = load_corpus(config['corpus_run'], config['dataset'])
        queries = load_queries(config['tasks'], corpus)
        index = load_index(config['vector_run'], corpus['fingerprint'], config)
        state.update(corpus_fingerprint=corpus['fingerprint'], index_id=index['index_id'],
                     source_vector_run=str(Path(config['vector_run']).resolve()))
        if set(index['query_hashes']) != {q['task_id'] for q in queries} or any(
                index['query_hashes'][q['task_id']] != digest(q['query'].encode()) for q in queries):
            raise ProbeError('cache', 'cache_mismatch')
        if read_json(Path(config['vector_run'])/'summary.json')['status'] != 'complete':
            raise ProbeError('baseline', 'baseline_mismatch')
        dense_results = []
        for query in queries:
            check_deadline(config, started)
            ranked = search(index, index['query_vectors'][query['task_id']], query['scope_ids'],
                            query['exclude_ids'], config['candidate_k'])
            dense_results.append({**query, **ranked, **pack_evidence(ranked['candidates'], config['max_context_chars']),
                                  'index_id': index['index_id'], 'elapsed_ms': 0})
        original = read_rows(Path(config['vector_run'])/'results.jsonl', 'baseline')
        if without_elapsed(original) != without_elapsed(dense_results):
            raise ProbeError('baseline', 'baseline_mismatch')
        check_deadline(config, started)
        began = time.monotonic(); tokenizer = Tokenizer(folder/'jieba-cache')
        state['tokenizer_ms'] = round((time.monotonic()-began)*1000, 3)
        began = time.monotonic()
        keywords, metadata = assemble_keywords(config, folder, corpus, queries, tokenizer, started)
        state.update(metadata, keyword_prepare_ms=round((time.monotonic()-began)*1000, 3))
        for query, dense in zip(queries, dense_results, strict=True):
            check_deadline(config, started)
            began = time.monotonic()
            sparse = keyword_search(keywords[scope_key(query)], query['query'], tokenizer, config['candidate_k'])
            sparse_ms = (time.monotonic()-began)*1000; check_deadline(config, started)
            began = time.monotonic()
            fused = fuse(dense['candidates'], sparse['candidates'], index['units'], config['rrf_k'], config['candidate_k'])
            fusion_ms = (time.monotonic()-began)*1000
            began = time.monotonic()
            sparse = {**query, **sparse, **pack_evidence(sparse['candidates'], config['max_context_chars'])}
            hybrid = {**query, 'candidates': fused['candidates'],
                      **pack_evidence(fused['candidates'], config['max_context_chars'])}
            results.append({**query, 'candidate_k': config['candidate_k'], 'index_id': index['index_id'],
                            'dense': dense, 'sparse': sparse, 'hybrid': hybrid, 'union_candidates': fused['union_candidates'],
                            'timings_ms': {'sparse': round(sparse_ms, 3), 'fusion': round(fusion_ms, 3),
                                           'packing': round((time.monotonic()-began)*1000, 3)}})
            check_deadline(config, started)
        gold = load_labels(config['tasks'], corpus)
        a1_metrics = [evaluate(r, corpus, gold) for r in dense_results]
        if a1_metrics != read_json(Path(config['vector_run'])/'evaluation.json', 'baseline'):
            raise ProbeError('baseline', 'baseline_mismatch')
        state['evaluation'] = [{'task_id': row['task_id'], 'A1': a1,
                               'BM25': evaluate(row['sparse'], corpus, gold),
                               'A2': evaluate(row['hybrid'], corpus, gold),
                               'union_recalled_ids': [eid for eid in gold['tasks'][row['task_id']]['required']
                                                     if covered(gold['evidence'][eid], row['union_candidates'])]}
                              for row, a1 in zip(results, a1_metrics, strict=True)]
        analysis = failure_analysis(results, state['evaluation'], corpus, gold)
        check_deadline(config, started); state['status'] = 'complete'
    except ProbeError as error:
        state.update(status='error', sanitized_error=error.record(), evaluation=None); results = []
    except Exception:
        state.update(status='error', sanitized_error=ProbeError('pipeline', 'unexpected_error').record(), evaluation=None)
        results = []
    state.update(elapsed_ms=round((time.monotonic()-started)*1000, 3),
                 network_attempts=network_counter[0] if network_counter is not None else None,
                 exit_code=0 if state['status'] == 'complete' else 2)
    try:
        if state['evaluation'] is not None:
            with (folder/'results.jsonl').open('x', encoding='utf-8') as handle:
                for row in results: handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
            write_json(folder/'evaluation.json', state['evaluation'])
            with (folder/'failure-analysis.md').open('x', encoding='utf-8') as handle: handle.write(analysis)
        report = build_report(state, results)
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
    for name in ['mode', 'dataset', 'corpus-run', 'tasks', 'vector-run', 'endpoint', 'model', 'output-root',
                 'bm25-method', 'tokenizer-policy', 'backend']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--keyword-run')
    for name in ['dimensions', 'candidate-k', 'rrf-k', 'max-context-chars', 'deadline-seconds']:
        parser.add_argument('--'+name, type=int, required=True)
    for name in ['bm25-k1', 'bm25-b']:
        parser.add_argument('--'+name, type=float, required=True)
    counter = [0]
    originals = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    def forbid(*args, **kwargs):
        counter[0] += 1
        raise ProbeError('network', 'network_forbidden')
    try:
        socket.socket.connect = socket.socket.connect_ex = socket.getaddrinfo = forbid
        state = run(vars(parser.parse_args(argv)), counter)
    except ProbeError as error:
        print(str(error), file=sys.stderr); return 2
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = originals
    print(f"status={state['status']} attempts={state['attempt_count']} network_attempts={state['network_attempts']} output={state['output_dir']}")
    if state['sanitized_error']:
        print(json.dumps(state['sanitized_error']), file=sys.stderr)
    return state['exit_code']


if __name__ == '__main__': raise SystemExit(main())
