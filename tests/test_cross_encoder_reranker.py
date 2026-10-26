"""Local predict's complete token-pair preflight; no installed model needed."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

CANDIDATES=[dict(passage_id='a',text='完整用例'),dict(passage_id='b',text='历史需求')]


def config(tmp_path,**changes):
    from naiyue_rag.core.cross_encoder_settings import CrossEncoderSettings
    return CrossEncoderSettings.from_dict(dict(model_id='synthetic/model',model_revision='a'*40,model_path=str(tmp_path/'model'),
        device='cpu',batch_size=2,max_pair_tokens=512,max_model_bytes=1000000000)|changes)


class Tokenizer:
    def __init__(self,length=10):self.calls=[];self.length=length
    def __call__(self,query,text,**kwargs):
        self.calls.append((query,text,kwargs));return {'input_ids':list(range(self.length))}


class Model:
    def __init__(self):self.tokenizer=Tokenizer();self.calls=[];self.output=[-2.,3.]
    def predict(self,pairs,**kwargs):
        self.calls.append((pairs,kwargs))
        if isinstance(self.output,Exception):raise self.output
        return self.output


def test_tokenizer_and_predict_are_real_consumers_of_config(tmp_path):
    from naiyue_rag.reranking.cross_encoder import CrossEncoderReranker
    model=Model();backend=CrossEncoderReranker(config(tmp_path),model=model)
    scores,report=backend.score('question',CANDIDATES)
    assert scores==[dict(passage_id='a',score=-2.),dict(passage_id='b',score=3.)]
    assert report['attempted_requests']==0 and report['usage'] is None and report['status']=='success'
    assert model.calls[0][0]==[('question','完整用例'),('question','历史需求')]
    assert model.calls[0][1]['batch_size']==2 and model.calls[0][1]['show_progress_bar'] is False
    assert all(c[2]['truncation'] is False and c[2]['add_special_tokens'] is True for c in model.tokenizer.calls)


def test_oversize_is_rejected_before_predict_without_truncation(tmp_path):
    from naiyue_rag import RerankError
    from naiyue_rag.reranking.cross_encoder import CrossEncoderReranker
    model=Model();model.tokenizer.length=513
    with pytest.raises(RerankError,match='rerank_input_limit'):CrossEncoderReranker(config(tmp_path),model=model).score('q',CANDIDATES)
    assert model.calls==[]


@pytest.mark.parametrize('output',[[1.],[True,1.],[float('nan'),1.],[[.1],[.2]],OSError('SYNTHETIC_PRIVATE')])
def test_bad_predict_is_safe_atomic(tmp_path,output,caplog):
    from naiyue_rag import RerankError
    from naiyue_rag.reranking.cross_encoder import CrossEncoderReranker
    model=Model();model.output=output
    with pytest.raises(RerankError) as caught:CrossEncoderReranker(config(tmp_path),model=model).score('q',CANDIDATES)
    assert 'SYNTHETIC_PRIVATE' not in str(caught.value)+caplog.text+json.dumps(caught.value.to_dict())


def test_missing_local_model_is_explicit_no_download(tmp_path,monkeypatch):
    from naiyue_rag import RerankError
    from naiyue_rag.reranking.cross_encoder import CrossEncoderReranker
    import socket
    def deny(*args,**kwargs):pytest.fail('local backend must not connect')
    monkeypatch.setattr(socket.socket,'connect',deny)
    with pytest.raises(RerankError,match='rerank_model_unavailable'):CrossEncoderReranker(config(tmp_path))


@pytest.mark.parametrize('change',[dict(max_pair_tokens=True),dict(device='auto'),dict(batch_size=0),dict(model_revision='main'),dict(extra=1)])
def test_settings_are_closed(tmp_path,change):
    from naiyue_rag.core.errors import SettingsError
    with pytest.raises(SettingsError):config(tmp_path,**change)


def test_model_capacity_is_read_before_config_can_override_tokenizer(tmp_path,monkeypatch):
    import sys
    from naiyue_rag import RerankError
    import naiyue_rag.reranking.cross_encoder as module
    captured=[]
    class Native:
        def __init__(self,path,**kwargs):
            captured.append(kwargs)
            # Matches 6.1.0: max_length overrides the tokenizer's saved limit.
            self.tokenizer=SimpleNamespace(model_max_length=kwargs.get('max_length',256))
    monkeypatch.setattr(module,'audit_model',lambda settings:tmp_path)
    monkeypatch.setitem(sys.modules,'sentence_transformers',SimpleNamespace(CrossEncoder=Native))
    with pytest.raises(RerankError,match='rerank_model_unavailable'):
        module.CrossEncoderReranker(config(tmp_path,max_pair_tokens=512))
    assert captured and 'max_length' not in captured[0]
