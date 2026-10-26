"""Bounded standard-API experiment, independent of any production RAG adapter."""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from experiments.markdown_probe import new_run_id

KEY_ENV = "NAIYUE_RAG_ZHIPU_API_KEY"
# Authorization boundary from Spec 0002, not a runtime endpoint default.
APPROVED_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/embeddings"
SAMPLES = [
    ("S1", "联合预测一次返回多个基础值，派生分使用原始预测值计算。"),
    ("S2", "存储密钥轮换时保留旧密钥，等待迁移完成后停止使用。"),
    ("Q", "一次预测取得多个结果时，派生分如何计算？"),
]


class ProbeError(Exception):
    def __init__(self, stage, category, http_status=None):
        self.stage, self.category, self.http_status = stage, category, http_status
        super().__init__(f"{stage}: {category}")

    def record(self):
        return {"stage": self.stage, "category": self.category, "http_status": self.http_status}


def validate_config(config):
    try:
        if config["endpoint"] != APPROVED_ENDPOINT or config["model"] != "embedding-3":
            raise ValueError("unapproved target")
        for field, maximum in [("dimensions", 2048), ("timeout_seconds", 30),
                               ("deadline_seconds", 120), ("max_requests", 2)]:
            value = config[field]
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError("invalid limit")
        if config["dimensions"] != 2048:
            raise ValueError("unapproved dimension")
        for field in ["budget_cny", "unit_price_cny_per_million"]:
            value = config[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid cost")
        if config["budget_cny"] > 1 or not isinstance(config["output_root"], str) or not config["output_root"]:
            raise ValueError("unapproved budget/output")
    except (KeyError, TypeError, ValueError):
        raise ProbeError("preflight", "invalid_config") from None
    upper_cost = 3 * 3072 * config["unit_price_cny_per_million"] / 1_000_000
    if upper_cost > config["budget_cny"]:
        raise ProbeError("preflight", "insufficient_budget")


def validate_vectors(payload, count, dimensions, model):
    try:
        if payload["model"] != model or len(payload["data"]) != count:
            raise ValueError("model or count")
        vectors = [None] * count
        for item in payload["data"]:
            index, vector = item["index"], item["embedding"]
            if type(index) is not int or not 0 <= index < count or vectors[index] is not None:
                raise ValueError("index")
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise ValueError("dimension")
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
                raise ValueError("numeric value")
            norm = math.hypot(*vector)
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("norm")
            vectors[index] = vector
        if any(vector is None for vector in vectors):
            raise ValueError("missing index")
        return vectors
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProbeError("response", "invalid_vectors") from None


def validate_usage(usage):
    try:
        for field in ["prompt_tokens", "total_tokens"]:
            if type(usage[field]) is not int or usage[field] < 0:
                raise ValueError("usage")
        if usage["total_tokens"] < usage["prompt_tokens"]:
            raise ValueError("usage order")
        if "completion_tokens" in usage and (type(usage["completion_tokens"]) is not int
                                               or usage["completion_tokens"] < 0):
            raise ValueError("completion usage")
        return {field: usage[field] for field in ["prompt_tokens", "total_tokens", "completion_tokens"]
                if field in usage}
    except (KeyError, TypeError, ValueError):
        raise ProbeError("usage", "usage_unknown") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("http", "redirect_rejected", http_status=code)


def send_embedding(config, texts, key):
    if not isinstance(texts, list) or not 1 <= len(texts) <= 2 or any(
            not isinstance(text, str) or not 0 < len(text) <= 200 for text in texts):
        raise ProbeError("preflight", "invalid_input")
    body = json.dumps({"model": config["model"], "dimensions": config["dimensions"],
                       "input": texts}, ensure_ascii=False).encode("utf-8")
    request = Request(config["endpoint"], data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key,
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=config["timeout_seconds"]) as reply:
            if reply.status != 200:
                raise ProbeError("http", "http_error", http_status=reply.status)
            raw = reply.read()
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProbeError("response", "invalid_json", http_status=200) from None
    except HTTPError as error:
        raise ProbeError("http", "http_error", http_status=error.code) from None
    except (TimeoutError, URLError, OSError):
        raise ProbeError("http", "transport_error") from None


def cosine(left, right):
    if not left or len(left) != len(right) or any(
            type(value) not in (int, float) or not math.isfinite(value) for value in left + right):
        raise ProbeError("similarity", "invalid_vector")
    a, b = math.hypot(*left), math.hypot(*right)
    if a == 0 or b == 0 or not math.isfinite(a) or not math.isfinite(b):
        raise ProbeError("similarity", "invalid_norm")
    score = math.fsum((x / a) * (y / b) for x, y in zip(left, right, strict=True))
    return min(1.0, max(-1.0, score))


def initial_summary(config):
    return {
        "schema_version": 1, "status": "running", "config": dict(config),
        "inputs": [{"input_id": identity, "characters": len(text),
                    "sha256": hashlib.sha256(text.encode()).hexdigest()} for identity, text in SAMPLES],
        "attempt_count": 0, "requests": [], "cosine_scores": None,
        "known_estimated_cost_cny": None, "estimated_cost_cny": None,
        "provider_billed_cost_cny": None, "sanitized_error": None, "elapsed_ms": None,
    }


def run_worker(config, emit):
    state, vectors = initial_summary(config), []
    started = time.monotonic()
    current = None
    try:
        validate_config(config)
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise ProbeError("preflight", "missing_key")
        for identities, texts in [(["S1", "S2"], [SAMPLES[0][1], SAMPLES[1][1]]),
                                  (["Q"], [SAMPLES[2][1]])]:
            if state["attempt_count"] >= config["max_requests"]:
                current = None
                raise ProbeError("budget", "request_limit")
            known_cost = state["known_estimated_cost_cny"] or 0
            reserved = len(texts) * 3072 * config["unit_price_cny_per_million"] / 1_000_000
            if known_cost + reserved > config["budget_cny"]:
                current = None
                raise ProbeError("budget", "insufficient_budget")
            current = {"input_ids": identities, "status": "running", "http_status": None,
                       "vectors": None, "usage": None, "elapsed_ms": None, "sanitized_error": None}
            state["requests"].append(current)
            state["attempt_count"] += 1
            state["estimated_cost_cny"] = None
            emit(json.loads(json.dumps(state)))
            request_started = time.monotonic()
            payload = send_embedding(config, texts, key)
            current["http_status"] = 200
            received = validate_vectors(payload, len(texts), config["dimensions"], config["model"])
            current["vectors"] = [{"input_id": identity, "dimensions": len(vector),
                                   "norm": math.hypot(*vector)}
                                  for identity, vector in zip(identities, received, strict=True)]
            current["usage"] = validate_usage(payload.get("usage"))
            current["elapsed_ms"] = round((time.monotonic() - request_started) * 1000, 3)
            cost = current["usage"]["prompt_tokens"] * config["unit_price_cny_per_million"] / 1_000_000
            state["known_estimated_cost_cny"] = known_cost + cost
            state["estimated_cost_cny"] = known_cost + cost
            current["status"] = "complete"
            if state["estimated_cost_cny"] > config["budget_cny"]:
                raise ProbeError("budget", "budget_exceeded")
            vectors.extend(received)
            emit(json.loads(json.dumps(state)))
        state["cosine_scores"] = [{"input_id": identity, "score": cosine(vectors[2], vector)}
                                  for identity, vector in zip(["S1", "S2"], vectors[:2], strict=True)]
        state["status"] = "complete"
    except ProbeError as error:
        state["status"], state["sanitized_error"] = "error", error.record()
        if current is not None:
            current["status"], current["sanitized_error"] = "error", error.record()
            if error.http_status is not None:
                current["http_status"] = error.http_status
            current["elapsed_ms"] = round((time.monotonic() - request_started) * 1000, 3)
    except Exception:
        # Protocol envelope: preserve failure, never serialize exception text or credentials.
        state["status"] = "error"
        state["sanitized_error"] = ProbeError("worker", "unexpected_error").record()
    state["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    return state


def supervise(config, started):
    remaining = config["deadline_seconds"] - (time.monotonic() - started)
    if remaining <= 0:
        state = initial_summary(config)
        state["status"] = "error"
        state["sanitized_error"] = ProbeError("deadline", "deadline_exceeded").record()
        return state
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "experiments.embedding_probe", "--worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=Path(__file__).resolve().parents[1], env=dict(os.environ),
        )
    except OSError:
        raise ProbeError("supervisor", "spawn_error") from None
    timed_out = False
    try:
        remaining = config["deadline_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired("embedding-worker", 0)
        output, _ = child.communicate(input=json.dumps(config), timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        output, _ = child.communicate()
    state, final_received = initial_summary(config), False
    for line in output.splitlines():
        try:
            event = json.loads(line)
            if event["event"] in ("checkpoint", "result"):
                state = event["summary"]
                final_received = event["event"] == "result"
        except (ValueError, TypeError, KeyError):
            state["status"] = "error"
            state["sanitized_error"] = ProbeError("supervisor", "invalid_worker_output").record()
            final_received = False
            break
    if timed_out or not final_received or child.returncode not in (0, 2):
        state["status"] = "error"
        category = "deadline_exceeded" if timed_out else "worker_failed"
        state["sanitized_error"] = ProbeError("supervisor", category).record()
        # A reserved/in-flight attempt may have reached the service without a usage response.
        if any(row["usage"] is None for row in state["requests"]) or not state["requests"]:
            state["estimated_cost_cny"] = None
    return state


def build_report(state):
    def cost_text(value):
        return "unknown" if value is None else f"{value:.9f}".rstrip("0").rstrip(".")
    lines = ["# Embedding API实际核验", "", f"状态：{state['status']}",
             f"模型：{state['config']['model']}；维度：{state['config']['dimensions']}",
             f"客户端尝试：{state['attempt_count']}；耗时ms：{state['elapsed_ms']}", "",
             f"按输入token标价估算费用（元）：{cost_text(state['estimated_cost_cny'])}",
             f"已知部分估算费用（元）：{cost_text(state['known_estimated_cost_cny'])}",
             f"供应商实际账单（元）：{cost_text(state['provider_billed_cost_cny'])}（未提供）", "",
             "| 输入 | HTTP | 维度 | 范数 | prompt tokens（批次） |",
             "| --- | --- | --- | --- | --- |"]
    for row in state["requests"]:
        for vector in row["vectors"] or []:
            usage = row["usage"]["prompt_tokens"] if row["usage"] else "unknown"
            lines.append(f"| {vector['input_id']} | {row['http_status']} | {vector['dimensions']} | "
                         f"{vector['norm']} | {usage} |")
    lines.extend(["", "余弦结果：", "", json.dumps(state["cosine_scores"], ensure_ascii=False),
                  "", "错误：", "", json.dumps(state["sanitized_error"], ensure_ascii=False),
                  "", "输入完全合成。短文本接口核验与相似度算例，不证明知识库召回或最终选型。"])
    return "\n".join(lines) + "\n"


def run(config):
    started = time.monotonic()
    validate_config(config)
    if not os.environ.get(KEY_ENV, "").strip():
        raise ProbeError("preflight", "missing_key")
    folder = Path(config["output_root"]).resolve() / new_run_id()
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except OSError:
        raise ProbeError("output", "output_error") from None
    state = supervise(config, started)
    state["output_dir"] = str(folder)
    state["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    try:
        with (folder / "report.md").open("x", encoding="utf-8") as handle:
            handle.write(build_report(state))
        with (folder / "summary.json").open("x", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError):
        raise ProbeError("output", "output_error") from None
    return state


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ["--worker"]:
        try:
            config = json.load(sys.stdin)
            def emit(state):
                print(json.dumps({"event": "checkpoint", "summary": state}), flush=True)
            state = run_worker(config, emit)
            print(json.dumps({"event": "result", "summary": state}), flush=True)
            return 0 if state["status"] == "complete" else 2
        except Exception:
            print("worker: invalid_input", file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["endpoint", "model", "output-root"]:
        parser.add_argument("--" + name, required=True)
    for name in ["dimensions", "timeout-seconds", "deadline-seconds", "max-requests"]:
        parser.add_argument("--" + name, type=int, required=True)
    for name in ["budget-cny", "unit-price-cny-per-million"]:
        parser.add_argument("--" + name, type=float, required=True)
    config = vars(parser.parse_args(args))
    try:
        state = run(config)
    except ProbeError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"status={state['status']} attempts={state['attempt_count']} output={state['output_dir']}")
    if state["sanitized_error"]:
        error = state["sanitized_error"]
        print(f"{error['stage']}: {error['category']} http_status={error['http_status']}", file=sys.stderr)
    return 0 if state["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
