"""Local review artifacts; untrusted text is displayed literally, never executed."""
import csv
import html
import json
import os
from pathlib import Path
import re
from .evaluation_inputs import EvaluationError


def create_text(path,*,encoding='utf-8',newline='\n'):
    fd=None
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        stream=os.fdopen(fd,'w',encoding=encoding,newline=newline);fd=None
        return stream
    except Exception:raise EvaluationError('evaluation_output_failed') from None
    finally:
        if fd is not None:os.close(fd)


def write_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    try:
        with create_text(temporary) as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    except Exception:raise EvaluationError('evaluation_output_failed') from None


def _literal(value):
    text=html.escape(str(value),quote=False)
    text=re.sub(r'([\\`*{}\[\]()#+.!|>~-])',r'\\\1',text)
    text=re.sub(r'(?<!\w)_|_(?!\w)',r'\\_',text)
    text=''.join(c for c in text if c in '\n\t' or ord(c)>=32 and ord(c)!=127)
    return '\n'.join('> '+line for line in text.splitlines()) or '>'


def _cell(value):
    # CSV quotes do not prevent formula execution in spreadsheet applications.
    text=str(value)
    return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text


def write_reports(output,meta,rows):
    output=Path(output)
    lines=['# 检索人工评审报告','',
        '状态：'+str(meta['status']),
        '阶段：'+meta['stage']+'；记录排名深度：'+str(meta['rank_limit']),
        '本报告不自动判断检索正确性；人工结论填写 review.csv。','',
        '## 运行信息','',_literal(json.dumps({k:v for k,v in meta.items() if k!='questions'},
            ensure_ascii=False,indent=2)), '']
    for row in rows:
        lines+=['## '+row['id'],'','问题：',_literal(row['query']),'',
            '执行状态：'+row['status']+'；客户端耗时（秒）：'+str(row['elapsed_seconds']),'']
        if row.get('reference_notes'):lines+=['人工参考（未发送给模型）：',_literal(row['reference_notes']),'']
        if row.get('checkpoints'):lines+=['人工检查要点：',_literal('\n'.join(row['checkpoints'])),'']
        if row['status']!='success':
            lines+=['错误码：'+row['error']['code'],''];continue
        result=row['result'];lines+=['检索状态：'+result.get('status','unknown'),'']
        for position,evidence in enumerate(result.get('evidence',[]),1):
            lines+=['### 返回证据 '+str(position),'',_literal(json.dumps({key:evidence.get(key) for key in
                ('rank','source_path','source_sha256','body_span','retrieval')},ensure_ascii=False)),'']
            for context in evidence.get('contexts',[]):lines+=[_literal(context['text']),'']
            lines+=[_literal(evidence['body']),'']
        lines+=['预算排除：',_literal(json.dumps(result.get('omitted',[]),ensure_ascii=False)),
            '阶段观察：',_literal(json.dumps(result.get('observations',{}),ensure_ascii=False)),'']
    try:
        with create_text(output/'report.md') as stream:stream.write('\n'.join(lines))
        with create_text(output/'review.csv',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['id','request_sha256','judgment','notes'])
            for question in meta.get('questions',rows):
                writer.writerow([_cell(question['id']),_cell(question['request_sha256']),'',''])
    except Exception:raise EvaluationError('evaluation_output_failed') from None
