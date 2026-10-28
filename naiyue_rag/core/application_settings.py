"""One application file, with typed module settings and explicit path ownership."""
from dataclasses import dataclass,asdict
import logging
import math
from pathlib import Path
import re
from .errors import SettingsError
from .yaml_config import read_yaml_mapping
from .application_paths import resolve_application_path
from .configuration_bootstrap import initialize_default_configuration
from .encoding_settings import RepresentationSettings,EncodingRuntimeSettings
from .ingestion_settings import IngestionSettings
from .sparse_encoding_settings import SparseEncodingSettings
from .storage_settings import StorageSettings
from .chroma_settings import ChromaSettings
from .bm25_settings import BM25Settings
from .hybrid_settings import HybridSettings
from .rerank_settings import RerankSettings
from .evidence_settings import EvidenceSettings

LOGGER=logging.getLogger(__name__)


def _exact(raw,fields):
    if type(raw) is not dict or set(raw)!=set(fields):raise ValueError()
    return dict(raw)


def _model(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',value) is None:raise ValueError()


def _positive(value):return type(value) is int and value>0


def _seconds(value):return type(value) in (int,float) and math.isfinite(value) and value>0


@dataclass(frozen=True,repr=False)
class ServiceSettings:
    host:str
    port:int
    access_token:str
    startup_timeout_seconds:float
    shutdown_timeout_seconds:float
    request_timeout_seconds:float
    max_request_bytes:int

    def __post_init__(self):
        if self.host!='127.0.0.1' or type(self.host) is not str or not _positive(self.port) or self.port>65535:raise ValueError()
        if type(self.access_token) is not str or re.fullmatch(r'[A-Za-z0-9_-]{32,128}',self.access_token) is None:raise ValueError()
        if not all(_seconds(v) for v in (self.startup_timeout_seconds,self.shutdown_timeout_seconds,self.request_timeout_seconds)) or \
                not _positive(self.max_request_bytes):raise ValueError()

    def to_dict(self):self.__post_init__();return asdict(self)


@dataclass(frozen=True,repr=False)
class EncodingSelection:
    model:str
    representation:RepresentationSettings
    runtime:EncodingRuntimeSettings

    def __post_init__(self):
        _model(self.model);r=self.representation;t=self.runtime
        if type(r) is not RepresentationSettings or type(t) is not EncodingRuntimeSettings:raise ValueError()
        if r.document_text_mode not in ('raw','labeled_case') or r.text_layout not in ('view_only','contexts_then_view'):raise ValueError()
        for value in (r.document_prefix,r.query_prefix):
            if type(value) is not str or '\x00' in value:raise ValueError()
            value.encode('utf-8')
        for name in ('batch_size','max_inputs','max_input_utf8_bytes','max_batch_input_utf8_bytes','max_requests','max_response_bytes'):
            if not _positive(getattr(t,name)):raise ValueError()
        if not _seconds(t.timeout_seconds) or not _seconds(t.deadline_seconds):raise ValueError()

    def to_dict(self):self.__post_init__();return asdict(self)


@dataclass(frozen=True,repr=False)
class RerankSelection:
    backend:str
    model:str|None
    settings:RerankSettings

    def __post_init__(self):
        if type(self.backend) is not str or self.backend not in ('none','llm','cross_encoder') or type(self.settings) is not RerankSettings:
            raise ValueError()
        self.settings.to_dict()
        if self.settings.enabled!=(self.backend!='none'):raise ValueError()
        if self.backend=='none':
            if self.model is not None:raise ValueError()
        else:_model(self.model)

    def to_dict(self):
        self.__post_init__();raw=self.settings.to_dict();raw.pop('enabled')
        return dict(backend=self.backend,model=self.model,**raw)


@dataclass(frozen=True,repr=False)
class ApplicationSettings:
    config_path:str
    data_root:str
    knowledge_base_root:str
    models_file:str
    service:ServiceSettings
    ingestion:IngestionSettings
    encoding:EncodingSelection
    sparse:SparseEncodingSettings
    storage:StorageSettings
    chroma:ChromaSettings
    bm25:BM25Settings
    hybrid:HybridSettings
    rerank:RerankSelection
    evidence:EvidenceSettings

    def to_dict(self):
        return dict(config_version=1,paths=dict(data_root=self.data_root,knowledge_base_root=self.knowledge_base_root),
            models_file=self.models_file,**{name:getattr(self,name).to_dict() for name in
            ('service','ingestion','encoding','sparse','storage','chroma','bm25','hybrid','rerank','evidence')})


def _assemble(source,raw):
    fields={'config_version','paths','models_file','service','ingestion','encoding','sparse','storage','chroma','bm25','hybrid','rerank','evidence'}
    raw=_exact(raw,fields)
    if type(raw['config_version']) is not int or raw['config_version']!=1:raise ValueError()
    paths=_exact(raw['paths'],{'data_root','knowledge_base_root'});base=source.parent
    data=resolve_application_path(paths['data_root'],base)
    knowledge=resolve_application_path(paths['knowledge_base_root'],base)
    models=resolve_application_path(raw['models_file'],base,directory=False)
    service=ServiceSettings(**_exact(raw['service'],ServiceSettings.__dataclass_fields__))
    ingestion=IngestionSettings.from_dict(raw['ingestion'])
    encoded=_exact(raw['encoding'],{'model','representation','runtime'})
    encoding=EncodingSelection(encoded['model'],
        RepresentationSettings(**_exact(encoded['representation'],RepresentationSettings.__dataclass_fields__)),
        EncodingRuntimeSettings(**_exact(encoded['runtime'],EncodingRuntimeSettings.__dataclass_fields__)))
    storage=_exact(raw['storage'],StorageSettings.__dataclass_fields__)
    storage['storage_root']=resolve_application_path(storage['storage_root'],data)
    sparse=_exact(raw['sparse'],SparseEncodingSettings.__dataclass_fields__)
    sparse['cache_dir']=resolve_application_path(sparse['cache_dir'],data)
    rerank=_exact(raw['rerank'],{'backend','model','top_k','max_candidates','max_input_characters'})
    backend=rerank.pop('backend');model=rerank.pop('model')
    return ApplicationSettings(str(source),data,knowledge,models,service,ingestion,encoding,
        SparseEncodingSettings.from_dict(sparse),StorageSettings.from_dict(storage),
        ChromaSettings.from_dict(raw['chroma']),BM25Settings.from_dict(raw['bm25']),
        HybridSettings.from_dict(raw['hybrid']),RerankSelection(backend,model,RerankSettings(enabled=backend!='none',**rerank)),
        EvidenceSettings.from_dict(raw['evidence']))


def load_application_settings(config_path=None):
    """Read one config; only omitted paths initialize the default user templates."""
    path=initialize_default_configuration() if config_path is None else config_path
    try:
        source=Path(path).expanduser()
        if source.is_symlink() or not source.is_file():raise ValueError()
    except Exception:
        LOGGER.error('application_settings_failed code=settings_file_error')
        raise SettingsError('settings_file_error') from None
    source,raw=read_yaml_mapping(source)
    try:return _assemble(source,raw)
    except Exception:
        LOGGER.error('application_settings_failed code=invalid_application_settings')
        raise SettingsError('invalid_application_settings') from None
