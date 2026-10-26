"""Settings -> project credential -> real SDK mock transport -> query result."""
import json
import os
import httpx
import pytest
import yaml
from naiyue_rag import load_embedding_provider,DenseEncoder,SparseEncoder,QueryEncoder
from naiyue_rag.core.errors import SettingsError
from test_openai_embedding import factory,safe_ambient,payload,PRIVATE
from test_encoding_settings import config_data
from test_sparse_encoding_settings import sparse_config
from test_document_chunker import offline

NAME='NAIYUE_RAG_ZHIPU_API_KEY'


def write_config(tmp_path,base_url='https://embedding.example.invalid/v1',model='synthetic-model'):
    raw=config_data();raw['embedding'].update(base_url=base_url,model=model,allowed_response_models=[model])
    path=tmp_path/'encoding.yaml';path.write_text(yaml.safe_dump(raw));return path

@pytest.mark.parametrize('profile',[('https://embedding.example.invalid/v1','synthetic-model',NAME),
    ('http://127.0.0.1:9876/v1','self-hosted-example','CUSTOM_EMBEDDING_KEY')])
def test_configured_provider_passes_model_endpoint_and_selected_key(tmp_path,monkeypatch,factory,profile):
    base,model,key_name=profile;path=write_config(tmp_path,base,model)
    monkeypatch.delenv(key_name,raising=False);(tmp_path/'.env').write_text(f'{key_name}={PRIVATE}\nOPENAI_LOG=debug\n')
    raw=payload();raw['model']=model;raw['usage']=dict(prompt_tokens=7,total_tokens=7)
    # Reuse the existing bounded SDK fixture to replace HTTPTransport; bootstrap itself stays real.
    _,transport=factory(lambda req:httpx.Response(200,json=raw))
    before=dict(os.environ)
    with load_embedding_provider(path,project_root=tmp_path,key_env=key_name) as provider:
        cfg=provider.settings
        result=QueryEncoder(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,sparse_config(tmp_path))).encode('开关 0.5')
        assert result.input.model_space_id==cfg.model_space_id and result.report.usage['total_tokens']==7
    assert provider.closed and dict(os.environ)==before
    assert len(transport.requests)==1 and str(transport.requests[0].url)==base+'/embeddings'
    assert transport.requests[0].headers['authorization']=='Bearer '+PRIVATE
    assert json.loads(transport.requests[0].content)['model']==model
    assert PRIVATE not in json.dumps(result.to_dict())


def test_model_config_failure_happens_before_any_credential_or_client(tmp_path,monkeypatch):
    import naiyue_rag.encoding.bootstrap as module
    path=tmp_path/'bad.yaml';path.write_text('invalid: true')
    monkeypatch.setattr(module,'resolve_api_key',lambda *a,**k:pytest.fail('must validate config first'))
    with pytest.raises(SettingsError,match='invalid_encoding_settings'):
        load_embedding_provider(path,project_root=tmp_path,key_env=NAME)


def test_missing_key_does_not_construct_provider(tmp_path,monkeypatch):
    import naiyue_rag.encoding.bootstrap as module
    monkeypatch.delenv(NAME,raising=False)
    monkeypatch.setattr(module,'OpenAICompatibleEmbedding',lambda *a,**k:pytest.fail('must resolve credential first'))
    with pytest.raises(SettingsError,match='credential_not_found'):
        load_embedding_provider(write_config(tmp_path),project_root=tmp_path,key_env=NAME)


def test_yaml_loader_still_does_not_implicitly_read_dotenv(tmp_path,monkeypatch):
    from naiyue_rag import load_encoding_settings
    import naiyue_rag.core.credentials as module
    path=write_config(tmp_path);(tmp_path/'.env').write_text('invalid="unterminated')
    monkeypatch.setattr(module,'_read_project_env',lambda root:pytest.fail('pure YAML loader must remain pure'))
    assert load_encoding_settings(path).embedding.model=='synthetic-model'
