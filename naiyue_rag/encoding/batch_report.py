"""Mutable process-local observations; terminal snapshots use the strict core contract."""
import time
import uuid
from ..core.encoding_report import EncodingReport,input_fingerprint,summarize_observations,validate_request_report


class BatchReport:
    def __init__(self,inputs,start):
        self.start=start
        self.data=dict(job_id=uuid.uuid4().hex,status='failed',input_count=len(inputs) if type(inputs) is list else None,
            input_fingerprint=None,planned_batch_count=None,completed_batch_count=0,paired_input_count=0,
            elapsed_seconds=0.,requests={},usage={},batches=[],error=None)
        self.started=0

    def planned(self,inputs,batches):
        self.data['input_fingerprint']=input_fingerprint(inputs)
        self.data['planned_batch_count']=len(batches)

    def enter(self,batch,index):
        start=self.data['batches'][-1]['input_end'] if self.data['batches'] else 0
        row=dict(index=index,input_start=start,input_end=start+len(batch),input_count=len(batch),
            input_fingerprint=input_fingerprint(batch),stage='dense',elapsed_seconds=0.,request_report=None,
            returned_model=None,source_kind=None,usage=None,usage_status='unknown_missing',error_code=None)
        self.data['batches'].append(row)
        self.batch_start=time.monotonic()

    @property
    def current(self):return self.data['batches'][-1]

    def request(self,report):self.current['request_report']=validate_request_report(report)

    def response(self,result):
        for key in ['returned_model','source_kind','usage','usage_status']:self.current[key]=result[key]

    def stage(self,stage):self.current['stage']=stage

    def complete(self):
        self.current['stage']='complete'
        self.current['elapsed_seconds']=max(0.,time.monotonic()-self.batch_start)
        self.data['completed_batch_count']+=1
        self.data['paired_input_count']+=self.current['input_count']

    def snapshot(self,*,status,stage=None,code=None):
        self.data['status']=status
        if code is not None:
            index=None
            if stage in ('dense','sparse','pairing'):
                index=self.current['index'];self.current['stage']=stage;self.current['error_code']=code
                self.current['elapsed_seconds']=max(0.,time.monotonic()-self.batch_start)
            self.data['error']=dict(stage=stage,code=code,batch_index=index)
        else:self.data['error']=None
        self.data['elapsed_seconds']=max(0.,time.monotonic()-self.start)
        self.data['requests'],self.data['usage']=summarize_observations(self.data['batches'],self.started)
        return EncodingReport.from_dict(self.data)
