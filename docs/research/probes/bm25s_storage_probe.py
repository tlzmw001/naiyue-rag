"""Pinned BM25S storage/empty-corpus probes over synthetic, already-tokenized rows."""
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import warnings


PARAMS=dict(k1=1.5,b=.75,method='lucene',idf_method='lucene',backend='numpy',
            csc_backend='numpy',dtype='float64',int_dtype='int32',auto_compile=False)


def run_case(rows,root):
    import bm25s
    import numpy as np
    result={'N':len(rows),'vocab_count':len({t for row in rows for t in row}),
            'avgdl':sum(map(len,rows))/len(rows) if rows else 0}
    stage='index'
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always')
            model=bm25s.BM25(**PARAMS)
            model.index(rows,create_empty_token=False,show_progress=False)
            result['warning_count']=len(captured)
        result['dtypes']={k:str(model.scores[k].dtype) for k in ['data','indices','indptr']}
        result['shapes']={k:list(model.scores[k].shape) for k in ['data','indices','indptr']}
        result['num_docs']=model.scores['num_docs']
        result['vocab_exact']=set(model.vocab_dict)=={t for row in rows for t in row}
        stage='score'
        result['scores_alpha']=model.get_scores(['alpha']).tolist()
        try:model.get_scores([])
        except Exception as error:result['empty_query_error']=type(error).__name__
        stage='save';model.save(root,allow_pickle=False,show_progress=False)
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        stage='load';loaded=bm25s.BM25.load(root,allow_pickle=False,mmap=False,load_corpus=False,show_progress=False,
                             override_params={'auto_compile':False,'csc_backend':'numpy'})
        result['loaded_scores_equal']=np.array_equal(loaded.get_scores(['alpha']),model.get_scores(['alpha']))
        result['reload_no_file_changes']=before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        result['files']=sorted(before)
        result['status']='ok'
    except Exception as error:result.update(status='error',error_stage=stage,error_type=type(error).__name__)
    return result


def main():
    attempts=[]
    def denied(*args,**kwargs):attempts.append(1);raise RuntimeError('network forbidden')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=denied
    cases={
        'normal':[['alpha','alpha','beta'],['beta','gamma']],
        'mixed_empty':[['alpha'],[]],
        'all_empty':[[],[]],
        'zero_rows':[],
        'technical_tokens':[['开关','0','0.5','TC-01','cvr_ltv'],['关闭','1']],
    }
    with tempfile.TemporaryDirectory(prefix='naiyue-bm25s-storage-') as temporary:
        root=Path(temporary)
        results={name:run_case(rows,root/name) for name,rows in cases.items()}
        normal=results['normal']
        expected=math.log(1+(2-1+.5)/(1+.5))*2/(2+1.5*(1-.75+.75*3/2.5))
        normal['hand_score_error']=abs(normal['scores_alpha'][0]-expected)
        # A separate interpreter opens only the persisted native files, with no text or tokenizer.
        code='''
import json,socket,sys
def deny(*a,**kw):raise RuntimeError('network forbidden')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
import bm25s
m=bm25s.BM25.load(sys.argv[1],allow_pickle=False,mmap=False,load_corpus=False,
                 show_progress=False,override_params={'auto_compile':False,'csc_backend':'numpy'})
print(json.dumps(m.get_scores(['alpha']).tolist()))
'''
        child=subprocess.run([sys.executable,'-I','-c',code,str(root/'normal')],cwd=root,
                             env={},capture_output=True,text=True,timeout=30)
        child_ok=child.returncode==0 and json.loads(child.stdout)==normal['scores_alpha']
    sdk=metadata.distribution('bm25s')
    checks=[normal['status']=='ok',normal['hand_score_error']<1e-12,child_ok,
            all(row['reload_no_file_changes'] for row in results.values() if row['status']=='ok'),
            results['mixed_empty']['status']=='ok',len(attempts)==0]
    checks.extend(row['num_docs']==row['N'] and row['vocab_exact'] for row in results.values())
    checks.extend(results[name]['error_stage']=='score' and results[name]['error_type']=='ValueError'
                  for name in ['zero_rows','all_empty'])
    checks.extend(row.get('empty_query_error')=='IndexError'
                  for row in results.values() if row['status']=='ok')
    report=dict(date='2026-10-15',version=sdk.version,parameters=PARAMS,cases=results,
                new_process_scores_equal=child_ok,python_network_attempts=len(attempts),
                model_requests=0,real_project_env_reads=0,expected_checks_passed=all(checks),
                source_sha256={name:hashlib.sha256(sdk.locate_file('bm25s/'+name).read_bytes()).hexdigest()
                               for name in ['__init__.py','scoring.py']},
                boundary='synthetic SDK storage probe; formal BM25 adapter not implemented')
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if all(checks) else 1


if __name__=='__main__':raise SystemExit(main())
