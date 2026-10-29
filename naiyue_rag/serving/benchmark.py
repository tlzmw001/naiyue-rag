"""Aggregate-only acceptance against an existing, explicitly configured knowledge base."""
import argparse
from dataclasses import replace
import getpass
import json
import math
import sys
import threading
import time

from ..core.application_settings import load_application_settings
from . import RetrievalService, RetrievalError


def _distribution(values):
    values = sorted(values)
    if not values:
        return None
    return dict(min=values[0], p50=values[math.ceil(len(values)*.5)-1],
                p95=values[math.ceil(len(values)*.95)-1], max=values[-1])


def benchmark(settings, question, *, requests=10):
    if type(requests) is not int or requests < 1:
        raise RetrievalError('retrieval_invalid_request')
    started = time.monotonic()
    handles = [];errors = {};timings = [];queue = [];execution = [];revisions = set();peak = [0]
    stop = threading.Event()
    service = RetrievalService(settings)
    def observe():
        while not stop.is_set():
            peak[0] = max(peak[0], service.status()['executing'])
            stop.wait(.01)
    observer = threading.Thread(target=observe, daemon=True)
    observer.start()
    try:
        for _ in range(requests):
            try:
                handles.append(service.submit(question))
            except Exception as error:
                code = getattr(error, 'code', 'retrieval_worker_failed')
                errors[code] = errors.get(code, 0) + 1
        for handle in handles:
            try:
                result = handle.result()
                if result['active'] is not None:
                    revisions.add(result['active']['revision'])
                if result['active'] is None or result['status']!='retrieved' or not result['evidence']:
                    errors['no_evidence'] = errors.get('no_evidence', 0) + 1
                    continue
                status = handle.status()
                timings.append(status['elapsed_seconds'])
                queue.append(status['queue_seconds'])
                execution.append(status['execution_seconds'])
            except Exception as error:
                code = getattr(error, 'code', 'retrieval_worker_failed')
                errors[code] = errors.get(code, 0) + 1
    finally:
        stop.set();observer.join()
        try:
            service.close()
        except Exception as error:
            code = getattr(error, 'code', 'retrieval_cleanup_failed')
            errors[code] = errors.get(code, 0) + 1
    rss = None
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != 'darwin':rss *= 1024
    except ImportError:
        pass  # Windows has no stdlib resource counter; report unavailable explicitly.
    return dict(status='passed' if not errors and len(timings)==requests else 'failed',
                requests=requests, admitted=len(handles), completed=len(timings), errors=errors,
                configured_concurrency=settings.retrieval.max_concurrent_queries,
                observed_reserved_slots=peak[0], revisions=sorted(revisions),
                queue_seconds=_distribution(queue), execution_seconds=_distribution(execution),
                total_seconds=_distribution(timings), wall_seconds=time.monotonic()-started,
                client_peak_rss_bytes=rss)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--requests', type=int, default=10)
    parser.add_argument('--concurrency', type=int, choices=(2, 4), default=2)
    args = parser.parse_args(argv)
    try:
        cfg = load_application_settings(args.config)
        cfg = replace(cfg, retrieval=replace(cfg.retrieval, max_concurrent_queries=args.concurrency))
        question = getpass.getpass('输入验收问题（不回显、不写入报告）：')
        report = benchmark(cfg, question, requests=args.requests)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['status']=='passed' else 1
    except (KeyboardInterrupt, EOFError):
        return 130
    except Exception as error:
        print(json.dumps(dict(status='failed', code=getattr(error, 'code', 'retrieval_worker_failed'))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
