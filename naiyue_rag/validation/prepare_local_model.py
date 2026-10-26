"""Explicitly prepare pinned public safetensors; core query never downloads models."""
import argparse
import hashlib
import json
import logging
from pathlib import Path
from ..core.cross_encoder_settings import CrossEncoderSettings,load_cross_encoder_settings
from ..reranking.cross_encoder import audit_model

REQUIRED=('config.json','model.safetensors','tokenizer.json','tokenizer_config.json')
OPTIONAL=('README.md','sentencepiece.bpe.model','special_tokens_map.json')


class ModelPreparationError(ValueError):
    def __init__(self,code):
        self.code=code if code in ('model_prepare_path','model_prepare_metadata','model_prepare_download',
            'model_prepare_integrity','model_prepare_limit','model_prepare_write') else 'model_prepare_integrity'
        logging.getLogger(__name__).error('model_prepare_failed code=%s',self.code)
        super().__init__(self.code)


def _summary(path,status):
    data=json.loads((path/'naiyue-model.json').read_text())
    return dict(status=status,model_id=data['model_id'],revision=data['revision'],files=len(data['files']),
        bytes=sum(i['size_bytes'] for i in data['files'].values()))


def prepare_local_model(settings):
    if type(settings) is not CrossEncoderSettings:raise ModelPreparationError('model_prepare_path')
    settings=CrossEncoderSettings.from_dict(settings.to_dict());target=Path(settings.model_path)
    try:
        if target==Path(target.anchor) or any(p.is_symlink() for p in (target,*target.parents)):raise ValueError()
        if (target/'naiyue-model.json').exists():
            audit_model(settings);return _summary(target,'unchanged')
        if target.exists() and (not target.is_dir() or any(target.iterdir())):raise ValueError()
    except Exception:raise ModelPreparationError('model_prepare_path') from None
    try:
        from huggingface_hub import HfApi,hf_hub_download
        info=HfApi().model_info(settings.model_id,revision=settings.model_revision,files_metadata=True,token=False)
        if info.sha!=settings.model_revision:raise ValueError()
        index={entry.rfilename:entry for entry in info.siblings}
        if len(index)!=len(info.siblings) or not set(REQUIRED)<=set(index):raise ValueError()
        names=list(REQUIRED)+[n for n in OPTIONAL if n in index];size=0
        for name in names:
            entry=index[name]
            if type(entry.size) is not int or entry.size<=0:raise ValueError()
            size+=entry.size
        if size>settings.max_model_bytes:raise ModelPreparationError('model_prepare_limit')
    except ModelPreparationError:raise
    except Exception:raise ModelPreparationError('model_prepare_metadata') from None
    try:target.mkdir(parents=True,exist_ok=True)
    except OSError:raise ModelPreparationError('model_prepare_path') from None
    manifest=dict(model_id=settings.model_id,revision=settings.model_revision,files={})
    for name in names:
        try:
            path=Path(hf_hub_download(settings.model_id,name,revision=settings.model_revision,token=False,
                local_dir=str(target),cache_dir=str(target/'download-cache')))
        except Exception:raise ModelPreparationError('model_prepare_download') from None
        try:
            entry=index[name]
            if path!=target/name or path.is_symlink() or path.stat().st_size!=entry.size:raise ValueError()
            sha=hashlib.sha256();git=hashlib.sha1();git.update(b'blob '+str(entry.size).encode()+b'\0')
            with path.open('rb') as handle:
                while block:=handle.read(1048576):sha.update(block);git.update(block)
            expected=entry.lfs.sha256 if entry.lfs else entry.blob_id
            if (sha.hexdigest() if entry.lfs else git.hexdigest())!=expected:raise ValueError()
            manifest['files'][name]=dict(size_bytes=entry.size,sha256=sha.hexdigest())
        except Exception:raise ModelPreparationError('model_prepare_integrity') from None
    try:
        with (target/'naiyue-model.json').open('x',encoding='utf-8') as handle:json.dump(manifest,handle,indent=2)
        audit_model(settings)
        return _summary(target,'prepared')
    except Exception:raise ModelPreparationError('model_prepare_write') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--settings',required=True);args=parser.parse_args(argv)
    try:
        result=prepare_local_model(load_cross_encoder_settings(args.settings))
        print(json.dumps(result,ensure_ascii=False));return 0
    except ModelPreparationError as error:
        print(json.dumps(dict(status='failed',code=error.code)));return 2
    except Exception:
        logging.getLogger(__name__).error('model_prepare_failed code=model_prepare_metadata')
        print(json.dumps(dict(status='failed',code='model_prepare_metadata')));return 2


if __name__=='__main__':raise SystemExit(main())
