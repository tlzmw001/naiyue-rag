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
    'service_identity_mismatch':'端口上的服务与当前配置、模型表或执行版本不匹配；请先停止原服务，再用所选配置启动。',
    'model_selection_invalid':'请检查 config.yaml 的 encoding.model/rerank.model 与 models.json 的模型类型。',
    'retrieval_timeout':'检索超过 retrieval.request_timeout_seconds；可稍后重新提交，服务不会自动重试。',
    'retrieval_overloaded':'检索等待队列已满；请用 nyr status 查看状态后再提交。',
    'service_timeout':'客户端等待超过 service.request_timeout_seconds；请用 nyr status 查看后台状态。',
    'retrieval_update_busy':'已有摄取或移除任务正在执行，请完成后再提交更新；在线检索仍可使用。',
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
    result=argparse.ArgumentParser(prog='nyr',description='默认启动共享检索服务（本机认证入口）；chat仅检索证据，当前不生成回答。')
    result.add_argument('--version',action='version',version=f'nyr {__version__}')
    result.add_argument('--config',help='统一config.yaml；默认 ~/.naiyue-rag/config.yaml')
    result.add_argument('--parent-watch',action='store_true',help=argparse.SUPPRESS)
    result.add_argument('--instance-id',help=argparse.SUPPRESS)
    commands=result.add_subparsers(dest='command')
    for name in ('chat','documents','document','ingest','remove','query','status','models','eval'):
        child=commands.add_parser(name)
        child.add_argument('--config',default=argparse.SUPPRESS)
        if name=='eval':
            run=child.add_subparsers(dest='eval_command',required=True).add_parser('run',help='批量跑题并导出人工评审材料')
            run.add_argument('--config',default=argparse.SUPPRESS)
            run.add_argument('--questions',required=True);run.add_argument('--output',required=True)
            run.add_argument('--max-questions',type=int,default=1000)
            run.add_argument('--max-input-bytes',type=int,default=16777216)
        elif name=='ingest':
            child.add_argument('--expected-revision',type=_revision,required=True);child.add_argument('--force',action='store_true')
        elif name=='query':
            child.add_argument('text');child.add_argument('--expected-revision',type=_revision)
            child.add_argument('--scope-document-id',action='append',help='限定文档ID，可重复指定')
            child.add_argument('--exclude-document-id',action='append',help='排除文档ID，可重复指定')
        elif name=='documents':child.add_argument('--expected-revision',type=_revision)
        elif name in ('document','remove'):
            child.add_argument('document_id')
            child.add_argument('--expected-revision',type=_revision,required=name=='remove')
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
        if args.command=='eval':
            from .validation.evaluation_run import run_evaluation
            return run_evaluation(settings,args.questions,args.output,
                max_questions=args.max_questions,max_input_bytes=args.max_input_bytes)
        if args.command=='models':
            from .core.model_registry import load_model_registry
            from .validation.prepare_local_model import prepare_local_model,ModelPreparationError
            try:result=prepare_local_model(load_model_registry(settings).local_settings(args.model_id))
            except ModelPreparationError as error:raise LocalServiceError(error.code) from None
        else:
            with ManagedConnection(settings) as connection:
                if args.command=='chat':return chat(connection.client)
                if args.command=='status':result=connection.client.status()
                else:
                    data={'expected_revision':args.expected_revision}
                    if args.command=='query':
                        data['query']=args.text
                        if args.scope_document_id is not None:data['scope_document_ids']=args.scope_document_id
                        if args.exclude_document_id is not None:data['exclude_document_ids']=args.exclude_document_id
                    elif args.command=='ingest':data['force']=args.force
                    elif args.command in ('document','remove'):data['document_id']=args.document_id
                    result=connection.client.request(args.command,data)
        print(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False));return 0
    except KeyboardInterrupt:return 130 if args.command=='eval' else 0
    except (SettingsError,LocalServiceError) as error:
        LOGGER.error('cli_failed code=%s',error.code)
        _display_error(error.code);return 2
    except SystemExit:
        LOGGER.error('cli_failed code=service_start_failed')
        _display_error('service_start_failed');return 2
    except Exception:
        LOGGER.error('cli_failed code=cli_failed')
        _display_error('cli_failed');return 2
