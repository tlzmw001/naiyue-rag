"""nyr local service, terminal retrieval and explicit maintenance commands."""
import argparse
import json
import logging
import re
import sys
import unicodedata
from ._version import __version__
from .core.application_settings import load_application_settings
from .core.errors import SettingsError
from .local_client import LocalServiceError
from .managed_service import ManagedConnection

LOGGER=logging.getLogger(__name__)
HINTS={
    'model_credential_invalid':'请检查 models_file 指定的文件（默认 models.json），为选中模型配置 api_key 或 api_key_env。',
    'invalid_application_settings':'请检查 --config 指定的统一配置；未指定时使用 ~/.naiyue-rag/config.yaml。',
    'service_identity_mismatch':'端口上的服务与当前配置或模型表不匹配；请先停止原服务，再用所选配置启动。',
    'model_selection_invalid':'请检查 config.yaml 的 encoding.model/rerank.model 与 models.json 的模型类型。',
}


def _display_error(code):
    detail={'code':code}
    if code in HINTS:detail['hint']=HINTS[code]
    print(json.dumps({'error':detail},ensure_ascii=False))


def _revision(value):
    try:
        result=int(value)
        if result<0:raise ValueError()
        return result
    except ValueError:raise argparse.ArgumentTypeError('expected a non-negative revision') from None


def parser():
    result=argparse.ArgumentParser(prog='nyr',description='耐阅RAG本机服务；chat仅检索证据，当前不生成回答。')
    result.add_argument('--version',action='version',version=f'nyr {__version__}')
    result.add_argument('--config',help='统一config.yaml；默认 ~/.naiyue-rag/config.yaml')
    result.add_argument('--parent-watch',action='store_true',help=argparse.SUPPRESS)
    result.add_argument('--instance-id',help=argparse.SUPPRESS)
    commands=result.add_subparsers(dest='command')
    for name in ('chat','documents','ingest','query','models'):
        child=commands.add_parser(name)
        child.add_argument('--config',default=argparse.SUPPRESS)
        if name=='ingest':
            child.add_argument('--expected-revision',type=_revision,required=True);child.add_argument('--force',action='store_true')
        elif name=='query':
            child.add_argument('text');child.add_argument('--expected-revision',type=_revision)
        elif name=='documents':child.add_argument('--expected-revision',type=_revision)
        elif name=='models':
            prepare=child.add_subparsers(dest='model_command',required=True).add_parser('prepare')
            prepare.add_argument('model_id');prepare.add_argument('--config',default=argparse.SUPPRESS)
    return result


def _terminal(text):
    # Strip ANSI CSI/OSC and all remaining controls except normal text layout.
    text=re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)','',text)
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    return ''.join(c for c in text if c in '\n\t' or not unicodedata.category(c).startswith('C'))


def chat(client):
    print('耐阅RAG终端检索：输入问题查看证据，/exit 或 Ctrl+C 退出。')
    while True:
        try:
            query=input('nyr> ')
            if query.strip()=='/exit':return 0
            if not query.strip():continue
            try:
                result=client.request('query',{'query':query})
                print(_terminal(result.get('context_text') or result.get('status','empty')))
            except LocalServiceError as error:_display_error(error.code)
        except (EOFError,KeyboardInterrupt):print();return 0


def main(argv=None):
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    args=parser().parse_args(argv)
    try:
        try:settings=load_application_settings(args.config)
        except SettingsError as error:
            if error.code=='settings_file_error':raise SettingsError('invalid_application_settings') from None
            raise
        if args.command is None:
            from .service import run_service
            run_service(settings,parent_watch=args.parent_watch,instance_id=args.instance_id);return 0
        if args.parent_watch or args.instance_id:raise LocalServiceError('service_invalid_request')
        if args.command=='models':
            from .core.model_registry import load_model_registry
            from .validation.prepare_local_model import prepare_local_model,ModelPreparationError
            try:result=prepare_local_model(load_model_registry(settings).local_settings(args.model_id))
            except ModelPreparationError as error:raise LocalServiceError(error.code) from None
        else:
            with ManagedConnection(settings) as connection:
                if args.command=='chat':return chat(connection.client)
                data={'expected_revision':args.expected_revision}
                if args.command=='query':data['query']=args.text
                elif args.command=='ingest':data['force']=args.force
                result=connection.client.request(args.command,data)
        print(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False));return 0
    except KeyboardInterrupt:return 0
    except (SettingsError,LocalServiceError) as error:
        LOGGER.error('cli_failed code=%s',error.code)
        _display_error(error.code);return 2
    except SystemExit:
        LOGGER.error('cli_failed code=service_start_failed')
        _display_error('service_start_failed');return 2
    except Exception:
        LOGGER.error('cli_failed code=cli_failed')
        _display_error('cli_failed');return 2
