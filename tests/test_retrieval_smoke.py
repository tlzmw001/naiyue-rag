"""Independent metric arithmetic, including zero-label handling."""
import pytest


def test_recall_uses_gold_count_and_deduplicated_ids():
    from naiyue_rag.validation.retrieval_smoke import score_ids
    assert score_ids(['a','a','x'],['a','b'])==dict(hits=1,required=2,recall=.5)
    assert score_ids([],['a'])==dict(hits=0,required=1,recall=0.)
    assert score_ids(['x'],[])==dict(hits=0,required=0,recall=None)


def test_fixed_labels_are_resolved_to_unique_saved_chunk():
    from naiyue_rag.validation.retrieval_smoke import resolve_gold
    from types import SimpleNamespace
    chunks=[SimpleNamespace(id='a',text='完整测试 TC-01',metadata={'source_path':'cases.md'})]
    assert resolve_gold(chunks,[dict(source_path='cases.md',anchor='TC-01')])==['a']
    with pytest.raises(ValueError,match='smoke_ambiguous_labels'):resolve_gold(chunks*2,[dict(source_path='cases.md',anchor='TC-01')])


@pytest.mark.parametrize('fault',['path','duplicate','empty_query','extra','invalid_gold','unanswerable'])
def test_labels_cannot_escape_output_or_change_the_schema(fault):
    from naiyue_rag.validation.retrieval_smoke import validate_labels
    data={'label_source':'assistant_constructed','review_status':'not_reviewed_by_user',
          'unit':'exact_current_chunk_selected_by_unique_source_and_body_anchor',
          'questions':[{'id':'Q1','query':'问题','required':[{'source_path':'a.md','anchor':'正文'}]}]}
    if fault=='path':data['questions'][0]['id']='../escape'
    elif fault=='duplicate':data['questions']*=2
    elif fault=='empty_query':data['questions'][0]['query']=''
    elif fault=='extra':data['questions'][0]['extra']='SYNTHETIC_PRIVATE'
    elif fault=='invalid_gold':data['questions'][0]['required'][0]['extra']='x'
    else:data['questions'][0]['unanswerable']=1
    with pytest.raises(ValueError,match='smoke_invalid_labels'):validate_labels(data)
