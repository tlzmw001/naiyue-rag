import json
import pytest


def test_question_file_keeps_notes_out_of_request_identity(tmp_path):
    from naiyue_rag.validation.evaluation_inputs import read_questions
    path=tmp_path/'questions.jsonl'
    row={'id':'Q1','query':'  边界\n条件？  ','reference_notes':'人工依据','checkpoints':['例外']}
    path.write_text('\n'+json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
    first=read_questions(path)
    assert first['questions'][0]['request']=={'query':row['query']}
    assert first['questions'][0]['reference_notes']=='人工依据'
    row['reference_notes']='另一份说明'
    path.write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8')
    second=read_questions(path)
    assert first['sha256']!=second['sha256']
    assert first['questions'][0]['request_sha256']==second['questions'][0]['request_sha256']


def test_unicode_line_separator_is_part_of_question_not_a_jsonl_boundary(tmp_path):
    from naiyue_rag.validation.evaluation_inputs import read_questions
    path=tmp_path/'questions.jsonl'
    path.write_text(json.dumps({'id':'Q1','query':'前提\u2028后续'},ensure_ascii=False),encoding='utf-8')
    assert read_questions(path)['questions'][0]['query']=='前提\u2028后续'


@pytest.mark.parametrize('payload',[
    '', '\n ', '{', '{"id":"Q1","id":"Q2","query":"q"}',
    '{"id":"Q1","query":NaN}', '{"id":"../q","query":"q"}',
    '{"id":"Q1","query":" "}', '{"id":"Q1","query":"q","extra":1}',
    '{"id":"Q1","query":"q","checkpoints":"x"}',
    '{"id":"Q1","query":"q","scope_document_ids":["bad"]}',
    '{"id":"Q1","query":"q"}\n{"id":"Q1","query":"other"}',
])
def test_invalid_questions_are_rejected(tmp_path,payload):
    from naiyue_rag.validation.evaluation_inputs import read_questions,EvaluationError
    path=tmp_path/'questions.jsonl';path.write_text(payload,encoding='utf-8')
    with pytest.raises(EvaluationError,match='evaluation_invalid_questions'):read_questions(path)


def test_question_limits_and_symlink_are_explicit(tmp_path):
    from naiyue_rag.validation.evaluation_inputs import read_questions,EvaluationError
    path=tmp_path/'q';path.write_text('{"id":"Q1","query":"q"}\n{"id":"Q2","query":"r"}')
    for kwargs in ({'max_questions':1},{'max_input_bytes':1},{'max_questions':True}):
        with pytest.raises(EvaluationError):read_questions(path,**kwargs)
    linked=tmp_path/'link';linked.symlink_to(path)
    with pytest.raises(EvaluationError):read_questions(linked)
