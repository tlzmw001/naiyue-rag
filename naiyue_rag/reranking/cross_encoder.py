"""Local CrossEncoder.predict, after complete pair-token preflight, never downloads."""
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from ..core.cross_encoder_settings import CrossEncoderSettings,load_cross_encoder_settings
from .report import RerankError,new_report,validate_scores


def audit_model(settings):
    try:
        path=Path(settings.model_path)
        if not path.is_dir() or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError()
        manifest=path/'naiyue-model.json'
        if manifest.is_symlink() or manifest.stat().st_size>65536:raise ValueError()
        data=json.loads(manifest.read_text())
        if type(data) is not dict or set(data)!={'model_id','revision','files'} or \
                data['model_id']!=settings.model_id or data['revision']!=settings.model_revision:raise ValueError()
        files=data['files']
        if type(files) is not dict or not {'config.json','model.safetensors','tokenizer.json','tokenizer_config.json'}<=set(files):raise ValueError()
        total=0
        for name,info in files.items():
            if type(name) is not str or Path(name).name!=name or name in ('.','..') or \
                    type(info) is not dict or set(info)!={'size_bytes','sha256'}:raise ValueError()
            size=info['size_bytes'];sha=info['sha256']
            if type(size) is not int or size<=0 or type(sha) is not str or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError()
            total+=size
            item=path/name
            if total>settings.max_model_bytes or item.is_symlink() or item.stat().st_size!=size:raise ValueError()
            digest=hashlib.sha256()
            with item.open('rb') as handle:
                while block:=handle.read(1048576):digest.update(block)
            if digest.hexdigest()!=sha:raise ValueError()
        return path
    except Exception:raise RerankError('rerank_model_unavailable') from None


class CrossEncoderReranker:
    provider='cross_encoder'

    def __init__(self,settings,*,model=None):
        if type(settings) is not CrossEncoderSettings:raise RerankError('rerank_invalid_input')
        self.settings=CrossEncoderSettings.from_dict(settings.to_dict());self.model=settings.model_id
        self._lock=threading.Lock()
        if model is not None:self._model=model;return
        path=audit_model(settings)
        try:
            from sentence_transformers import CrossEncoder
            import torch
            self._model=CrossEncoder(str(path),device=settings.device,
                local_files_only=True,trust_remote_code=False,token=False,activation_fn=torch.nn.Identity(),
                model_kwargs={'use_safetensors':True})
            # Reject a requested length beyond the actual pretrained model's capacity.
            capacity=self._model.tokenizer.model_max_length
            if type(capacity) is not int or capacity<settings.max_pair_tokens:raise ValueError()
            self._model.max_seq_length=settings.max_pair_tokens
        except Exception:raise RerankError('rerank_model_unavailable') from None

    def score(self,query,candidates):
        started=time.monotonic();report=new_report()
        if not self._lock.acquire(blocking=False):raise RerankError('rerank_provider_busy')
        try:
            cfg=CrossEncoderSettings.from_dict(self.settings.to_dict())
            if type(query) is not str or not query.strip() or type(candidates) is not list or not candidates:raise ValueError()
            pairs=[];ids=[]
            for candidate in candidates:
                if type(candidate) is not dict or set(candidate)!={'passage_id','text'} or \
                        any(type(v) is not str or not v.strip() for v in candidate.values()):raise ValueError()
                uid=candidate['passage_id'];text=candidate['text']
                if uid in ids:raise ValueError()
                ids.append(uid);pairs.append((query,text))
                tokens=self._model.tokenizer(query,text,add_special_tokens=True,truncation=False,
                    return_attention_mask=False,return_token_type_ids=False)['input_ids']
                if len(tokens)>cfg.max_pair_tokens:raise RerankError('rerank_input_limit',report)
            raw=self._model.predict(pairs,batch_size=cfg.batch_size,show_progress_bar=False,convert_to_numpy=True)
            # Native ndarray converts scalars; nested/multi-class output stays nested and is rejected.
            values=raw.tolist() if hasattr(raw,'tolist') else raw
            if type(values) is not list or len(values)!=len(ids):raise ValueError()
            scores=[dict(passage_id=uid,score=score) for uid,score in zip(ids,values,strict=True)]
            validate_scores(scores,ids);report['status']='success';report['elapsed_seconds']=time.monotonic()-started
            return scores,report
        except RerankError:raise
        except Exception:
            report['elapsed_seconds']=max(0.,time.monotonic()-started)
            raise RerankError('rerank_model_failed',report) from None
        finally:self._lock.release()


def load_cross_encoder(path):return CrossEncoderReranker(load_cross_encoder_settings(path))
