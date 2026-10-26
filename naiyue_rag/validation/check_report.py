"""Payload-free checkpoint protocol, durable control journal and usage reconciliation."""
import copy
import json
import logging
import os
from pathlib import Path
import re
import stat
from ..core.encoding_report import ERROR_CODES,EncodingReport,validate_request_report,summarize_observations

LOGGER=logging.getLogger(__name__)
CODES=ERROR_CODES | frozenset('''check_preflight_failed check_path_invalid check_output_exists
check_limits_invalid check_budget_exceeded check_descriptor_invalid checkpoint_protocol_invalid
checkpoint_write_failed checkpoint_read_failed checkpoint_limit_exceeded worker_start_failed
worker_deadline_exceeded worker_failed worker_kill_failed worker_reap_timeout worker_reap_failed
worker_supervision_failed worker_initialization_failed worker_close_failed report_write_failed'''.split())

class CheckError(ValueError):
    def __init__(self,code):
        self.code=code if type(code) is str and code in CODES else 'check_preflight_failed'
        LOGGER.error('encoding_check_failed code=%s',self.code)
        super().__init__(self.code)


def safe_code(code,fallback='worker_failed'):
    return code if type(code) is str and code in CODES else fallback


def _require(condition):
    if not condition:raise CheckError('checkpoint_protocol_invalid')


def _hash(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None


def _keys(data,fields):_require(type(data) is dict and set(data)==set(fields.split()))


class Ledger:
    def __init__(self,job):
        self.job=job;self.seq=0;self.identity=None;self.stage=None;self.reservations=[]
        self.observations=[];self.tasks={};self.cleanup=None;self.final=None

    def accept(self,event):
        # Invalid events cannot partially mutate the verified prefix.
        candidate=copy.deepcopy(self)
        try:candidate._accept(event)
        except CheckError:raise
        except Exception:raise CheckError('checkpoint_protocol_invalid') from None
        self.__dict__.update(candidate.__dict__)

    def _accept(self,event):
        _keys(event,'seq run_id type data')
        _require(type(event['seq']) is int and event['seq']==self.seq+1 and self.final is None)
        _require(event['run_id']==self.job['run_id']);kind=event['type'];data=event['data']
        _require(type(kind) is str)
        if kind=='worker_started':
            _keys(data,'model_space_id representation_id tokenizer_id dimensions')
            _require(self.identity is None and self.stage is None and self.cleanup is None)
            _require(data['model_space_id']==self.job['model_space_id'] and data['representation_id']==self.job['representation_id'])
            _require(_hash(data['tokenizer_id']) and type(data['dimensions']) is int and data['dimensions']==self.job['settings']['embedding']['expected_dimensions'])
            self.identity=copy.deepcopy(data)
        elif kind=='task_started':
            _keys(data,'stage');stage=data['stage']
            _require(self.identity is not None and self.cleanup is None)
            _require(stage=='documents' and self.stage is None or stage=='query' and self.stage=='documents' and
                     self.tasks.get('documents',{}).get('report',{}).get('status')=='success')
            self.stage=stage
        elif kind=='request_reserved':
            _keys(data,'ordinal stage input_count input_fingerprint')
            _require(self.stage in ('documents','query') and data['stage']==self.stage and self.stage not in self.tasks and self.cleanup is None)
            _require(len(self.reservations)==len(self.observations) and type(data['ordinal']) is int and data['ordinal']==len(self.reservations)+1)
            _require(len(self.reservations)<self.job['settings']['runtime']['max_requests'])
            previous=sum(r['stage']==self.stage for r in self.reservations)
            plan=self.job['plans'][self.stage]['batches']
            _require(previous<len(plan) and type(data['input_count']) is int and data['input_count']==plan[previous]['input_count'] and data['input_fingerprint']==plan[previous]['input_fingerprint'])
            self.reservations.append(copy.deepcopy(data))
        elif kind=='request_observed':
            _keys(data,'ordinal report returned_model source_kind usage usage_status')
            _require(self.cleanup is None and self.stage not in self.tasks and len(self.reservations)==len(self.observations)+1 and
                     type(data['ordinal']) is int and data['ordinal']==len(self.reservations))
            report=validate_request_report(data['report']);_require(report['attempted_requests']<=1)
            model=data['returned_model'];source=data['source_kind'];usage=data['usage'];status=data['usage_status']
            _require((model is None and source is None) or (model in self.job['settings']['embedding']['allowed_response_models'] and source in ('service','simulated')))
            if status=='known':
                _require(type(usage) is dict and set(usage) in ({'prompt_tokens','total_tokens'},{'prompt_tokens','total_tokens','completion_tokens'}))
                _require(all(type(v) is int and v>=0 for v in usage.values()) and usage['total_tokens']>=usage['prompt_tokens'])
                _require(model is not None and report['attempted_requests']==1 and report['error_code'] is None)
            else:_require(status in ('unknown_missing','unknown_invalid') and usage is None)
            self.observations.append(copy.deepcopy(data))
        elif kind=='task_result':
            _keys(data,'stage report summary');stage=data['stage']
            _require(stage==self.stage and stage not in self.tasks and self.cleanup is None)
            report=EncodingReport.from_dict(data['report']).to_dict();plan=self.job['plans'][stage]
            _require(report['input_count']==plan['input_count'] and report['input_fingerprint']==plan['input_fingerprint'] and report['planned_batch_count']==len(plan['batches']))
            reserved=[r for r in self.reservations if r['stage']==stage]
            observed=[o for r,o in zip(self.reservations,self.observations) if r['stage']==stage]
            _require(report['requests']['dense_calls_started']==len(reserved))
            rows=[dict(request_report=o['report'],usage=o['usage'],usage_status=o['usage_status']) for o in observed]
            requests,usage=summarize_observations(rows,len(reserved))
            _require(report['requests']==requests and report['usage']==usage)
            for batch,expected in zip(report['batches'],plan['batches']):
                _require(batch['input_count']==expected['input_count'] and batch['input_fingerprint']==expected['input_fingerprint'])
            for batch,observation in zip(report['batches'],observed):
                _require(batch['request_report']==observation['report'] and batch['usage']==observation['usage'] and batch['returned_model']==observation['returned_model'] and batch['source_kind']==observation['source_kind'])
            summary=data['summary']
            if report['status']=='success':
                _keys(summary,'count dimensions model_space_id representation_id tokenizer_id input_fingerprint json_roundtrip')
                _require(type(summary['count']) is int and summary['count']==plan['input_count'] and summary['input_fingerprint']==plan['input_fingerprint'] and summary['json_roundtrip'] is True)
                _require(all(summary[k]==v and type(summary[k]) is type(v) for k,v in self.identity.items()))
            else:_require(report['status']=='failed' and summary is None)
            self.tasks[stage]=copy.deepcopy(data)
        elif kind=='cleanup':
            _keys(data,'attempted closed error_code')
            _require(self.cleanup is None and type(data['attempted']) is bool and type(data['closed']) is bool)
            _require(data['error_code'] in (None,'worker_close_failed') and (data['closed'] if data['attempted'] and data['error_code'] is None else not data['closed']))
            self.cleanup=copy.deepcopy(data)
        elif kind=='final':
            _keys(data,'status stage error_code')
            _require(self.cleanup is not None and data['stage'] in ('initialize','documents','query','cleanup'))
            if data['status']=='complete':
                _require(data['error_code'] is None and data['stage']=='cleanup' and self.cleanup['closed'] and self.cleanup['error_code'] is None)
                _require(set(self.tasks)=={'documents','query'} and all(v['report']['status']=='success' for v in self.tasks.values()))
                _require(len(self.reservations)==len(self.observations))
            else:
                _require(data['status']=='failed' and type(data['error_code']) is str and data['error_code'] in CODES)
                failures=[v['report']['error']['code'] for v in self.tasks.values() if v['report']['status']=='failed']
                if failures:_require(data['error_code']==failures[-1])
            self.final=copy.deepcopy(data)
        else:raise CheckError('checkpoint_protocol_invalid')
        self.seq+=1

    def summary(self):
        rows=[dict(request_report=o['report'],usage=o['usage'],usage_status=o['usage_status']) for o in self.observations]
        requests,usage=summarize_observations(rows,len(self.reservations))
        return dict(reserved_dense_calls=len(self.reservations),observed_dense_calls=len(self.observations),
                    attempted_requests=requests['attempted_requests'],attempted_requests_known_sum=requests['attempted_requests_known_sum'],usage=usage)


class Journal:
    def __init__(self,job):self.job=job;self.ledger=Ledger(job);self.bytes=0;self.failed=False

    def emit(self,kind,data):
        if self.failed:raise CheckError('checkpoint_write_failed')
        event=dict(seq=self.ledger.seq+1,run_id=self.job['run_id'],type=kind,data=data)
        next_ledger=copy.deepcopy(self.ledger);next_ledger.accept(event)
        encoded=(json.dumps(event,ensure_ascii=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(encoded)+self.bytes>self.job['max_checkpoint_bytes'] or event['seq']>self.job['max_checkpoint_records']:
            self.failed=True;raise CheckError('checkpoint_limit_exceeded')
        try:
            path=Path(self.job['run_dir'])/'checkpoints.jsonl'
            flags=os.O_WRONLY|os.O_APPEND|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
            with os.fdopen(os.open(path,flags),'ab') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise OSError()
                stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        except Exception:
            self.failed=True;raise CheckError('checkpoint_write_failed') from None
        self.ledger=next_ledger;self.bytes+=len(encoded)


def read_journal(job):
    ledger=Ledger(job);truncated=False
    try:
        path=Path(job['run_dir'])/'checkpoints.jsonl'
        flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
        with os.fdopen(os.open(path,flags),'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise OSError()
            raw=stream.read(job['max_checkpoint_bytes']+1)
    except Exception:return ledger,'checkpoint_read_failed',False
    oversized=len(raw)>job['max_checkpoint_bytes']
    raw=raw[:job['max_checkpoint_bytes']]
    lines=raw.splitlines(keepends=True)
    for line in lines:
        if not line.endswith(b'\n'):
            truncated=True;break
        if ledger.seq>=job['max_checkpoint_records']:return ledger,'checkpoint_limit_exceeded',truncated
        try:
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError()
                    result[key]=value
                return result
            event=json.loads(line,object_pairs_hook=unique);ledger.accept(event)
        except Exception:return ledger,'checkpoint_protocol_invalid',truncated
    return ledger,'checkpoint_limit_exceeded' if oversized else None,truncated
