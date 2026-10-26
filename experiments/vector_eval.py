"""Synthetic source-range labels are consumed only by evaluation."""
from experiments.embedding_probe import ProbeError
from experiments.vector_index import read_json, validate_scope


def load_queries(path, corpus):
    try:
        data = read_json(path, 'queries')
        if data['synthetic'] is not True:
            raise ValueError('material')
        queries, seen = [], set()
        for task in data['tasks']:
            task_id, query = task['task_id'], task['query']
            if not isinstance(task_id,str) or not task_id or task_id in seen or not isinstance(query,str) or not query.strip():
                raise ValueError('query')
            seen.add(task_id)
            scope = task.get('scope_document_ids')
            exclude = task.get('historical_search_exclude_document_ids', [])
            validate_scope(corpus['sources'], corpus['excluded_ids'], scope, exclude)
            queries.append({'task_id': task_id, 'query': query, 'scope_ids': scope, 'exclude_ids': exclude})
        if not queries:
            raise ValueError('empty tasks')
        return queries
    except ProbeError:
        raise
    except (ValueError, TypeError, KeyError):
        raise ProbeError('queries', 'invalid_queries') from None


def load_labels(path, corpus):
    try:
        data = read_json(path, 'labels')
        evidence = {}
        for eid, label in data['evidence_units'].items():
            src = corpus['sources'][label['document_id']]
            low, high = label['line_start'], label['line_end']
            if type(low) is not int or type(high) is not int or not 1 <= low <= high <= len(src['line_starts']):
                raise ValueError('range')
            if label['source_sha256'] != src['source_sha256'] or label['path'] != 'knowledge/' + src['relative_path']:
                raise ValueError('version/path')
            start = src['line_starts'][low-1]
            end = src['line_starts'][high] if high < len(src['line_starts']) else len(src['text'])
            positions = [i for i in range(start,end) if not src['text'][i].isspace()]
            if not positions:
                raise ValueError('empty label')
            evidence[eid] = {'document_id': label['document_id'], 'start': start, 'end': end,
                             'last_nonwhite': positions[-1], 'positions': positions}
        tasks = {}
        for task in data['tasks']:
            if task['task_id'] in tasks:
                raise ValueError('duplicate task')
            required = task['candidate_required_evidence']
            background = task.get('candidate_background_evidence', [])
            for ids in [required, background]:
                if not isinstance(ids,list) or any(not isinstance(i,str) or i not in evidence for i in ids) or len(set(ids)) != len(ids):
                    raise ValueError('label id')
            distractors = task.get('candidate_irrelevant_document_ids', [])
            if not set(distractors) <= set(corpus['sources']):
                raise ValueError('distractor')
            tasks[task['task_id']] = {'required': required, 'background': background,
                                      'irrelevant_documents': distractors, 'expected_status': task.get('expected_status')}
        return {'evidence': evidence, 'tasks': tasks, 'annotation_origin': data['annotation_origin'],
                'user_review_status': data['user_review_status']}
    except ProbeError:
        raise
    except (ValueError, TypeError, KeyError, IndexError):
        raise ProbeError('labels', 'invalid_labels') from None


def intersects(label, unit):
    span = unit['body_span']
    return unit['document_id'] == label['document_id'] and any(
        span['start_char'] <= pos < span['end_char'] for pos in label['positions'])


def covered(label, units):
    spans = [u['body_span'] for u in units if u['document_id'] == label['document_id']]
    return all(any(s['start_char'] <= pos < s['end_char'] for s in spans) for pos in label['positions'])


def evaluate(result, corpus, gold):
    task = gold['tasks'][result['task_id']]
    required = task['required']
    relevant = {u['unit_id'] for u in corpus['units'] if any(intersects(gold['evidence'][eid],u) for eid in required)}
    if required and not relevant:
        raise ProbeError('labels', 'unmapped_required_labels')
    candidates, selected = result['candidates'], result['selected']
    candidate_hits = {eid for eid in required if covered(gold['evidence'][eid], candidates)}
    selected_hits = {eid for eid in required if covered(gold['evidence'][eid], selected)}
    recall = {str(k): len({u['unit_id'] for u in candidates[:k]} & relevant)/len(relevant) if relevant else None
              for k in [10,20]}
    annotated = {u['unit_id'] for u in corpus['units'] if any(intersects(gold['evidence'][eid],u)
                 for eid in required + task['background'])}
    return {'task_id': result['task_id'], 'annotation_origin': gold['annotation_origin'],
            'user_review_status': gold['user_review_status'], 'required_count': len(required),
            'relevant_unit_count': len(relevant), 'recall_at_10': recall['10'], 'recall_at_20': recall['20'],
            'max_context_chars': result['max_context_chars'],
            'coverage_at_budget': len(selected_hits)/len(required) if required else None,
            'selected_evidence_ids': [eid for eid in required if eid in selected_hits],
            'not_recalled': [eid for eid in required if eid not in candidate_hits],
            'budget_excluded': [eid for eid in required if eid in candidate_hits and eid not in selected_hits],
            'background_hits': [eid for eid in task['background'] if covered(gold['evidence'][eid],selected)],
            'distractor_candidate_count': sum(u['document_id'] in task['irrelevant_documents'] for u in candidates),
            'distractor_selected_count': sum(u['document_id'] in task['irrelevant_documents'] for u in selected),
            'unlabelled_selected_ids': [u['unit_id'] for u in selected if u['unit_id'] not in annotated
                                      and u['document_id'] not in task['irrelevant_documents']],
            'expected_status': task['expected_status'], 'system_answerability': result['answerability']}
