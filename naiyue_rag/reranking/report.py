"""Closed, source-free rerank observation and whole-operation failure."""
import copy
import logging
import math
import re

CODES=frozenset('''rerank_invalid_input rerank_input_limit rerank_invalid_output rerank_failed rerank_timeout
rerank_deadline_exceeded rerank_response_too_large rerank_response_close_failed rerank_client_close_failed
rerank_invalid_response_headers rerank_unsupported_content_encoding rerank_transport_not_bound
rerank_connection_failed rerank_request_failed rerank_initialization_failed rerank_unsafe_sdk_environment
rerank_provider_busy rerank_provider_closed rerank_invalid_credential rerank_model_failed rerank_model_unavailable'''.split())


def new_report():
    return dict(status='pending',attempted_requests=0,http_status=None,response_bytes=0,elapsed_seconds=0.,
        error_code=None,response_close_error_code=None,client_close_error_code=None,usage=None)


def valid_code(code):
    return type(code) is str and (code in CODES or re.fullmatch(r'rerank_http_[3-5][0-9]{2}',code) is not None)


def validate_report(report):
    try:
        if type(report) is not dict or set(report)!=set(new_report()):raise ValueError()
        if type(report['status']) is not str or report['status'] not in ('pending','disabled','empty','success','error'):raise ValueError()
        for key in ('attempted_requests','response_bytes'):
            if type(report[key]) is not int or report[key]<0:raise ValueError()
        http=report['http_status']
        if http is not None and (type(http) is not int or not 100<=http<=599):raise ValueError()
        elapsed=report['elapsed_seconds']
        if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<0:raise ValueError()
        for key in ('error_code','response_close_error_code','client_close_error_code'):
            if report[key] is not None and not valid_code(report[key]):raise ValueError()
        if (report['status']=='error')!=(report['error_code'] is not None):raise ValueError()
        usage=report['usage']
        if usage is not None:
            if type(usage) is not dict or set(usage)!={'prompt_tokens','completion_tokens','total_tokens'} or \
                    any(type(v) is not int or v<0 for v in usage.values()) or \
                    usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:raise ValueError()
    except Exception:raise ValueError('rerank_invalid_output') from None


class RerankError(ValueError):
    def __init__(self,code,report=None,*,encoding_report=None):
        from ..core.encoding_report import EncodingReport
        self.code=code if valid_code(code) else 'rerank_failed'
        observed=copy.deepcopy(report) if report is not None else new_report()
        observed['status']='error';observed['error_code']=self.code
        try:validate_report(observed)
        except ValueError:
            observed=new_report();observed['status']='error';observed['error_code']=self.code
        self.report=observed
        self.encoding_report=None if encoding_report is None else EncodingReport.from_dict(encoding_report.to_dict())
        logging.getLogger(__name__).error('rerank_failed code=%s',self.code)
        super().__init__(self.code)

    def to_dict(self):
        validate_report(self.report)
        return dict(code=self.code,report=copy.deepcopy(self.report),encoding_report=None if self.encoding_report is None else self.encoding_report.to_dict())


def validate_scores(scores,candidate_ids):
    try:
        if type(scores) is not list or len(scores)!=len(candidate_ids):raise ValueError()
        seen=set()
        for item in scores:
            if type(item) is not dict or set(item)!={'passage_id','score'}:raise ValueError()
            uid=item['passage_id'];score=item['score']
            if type(uid) is not str or uid not in candidate_ids or uid in seen or \
                    type(score) not in (int,float) or not math.isfinite(score):raise ValueError()
            seen.add(uid)
        if seen!=set(candidate_ids):raise ValueError()
    except Exception:raise ValueError('rerank_invalid_output') from None
