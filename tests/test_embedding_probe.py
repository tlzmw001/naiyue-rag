"""Spec 0002: offline contracts; no real credentials or network."""

import importlib
import json
import math
import socket
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real network forbidden in tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setenv("NAIYUE_RAG_ZHIPU_API_KEY", "offline-secret-sentinel")


@pytest.fixture
def probe():
    return importlib.import_module("experiments.embedding_probe")


@pytest.fixture
def config(tmp_path):
    return {
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        "model": "embedding-3", "dimensions": 2048,
        "timeout_seconds": 30, "deadline_seconds": 120,
        "max_requests": 2, "budget_cny": 1,
        "unit_price_cny_per_million": 0.5,
        "output_root": str(tmp_path / "output"),
    }


def response(count=2, dimensions=2048):
    return {
        "model": "embedding-3",
        "data": [{"index": i, "embedding": [float(i + 1)] * dimensions}
                 for i in reversed(range(count))],
        "usage": {"prompt_tokens": 20, "total_tokens": 20, "completion_tokens": 0},
    }


def test_vectors_reordered_by_index(probe):
    vectors = probe.validate_vectors(response(), 2, 2048, "embedding-3")
    assert vectors[0][0] == 1
    assert vectors[1][0] == 2
    assert probe.validate_usage(response()["usage"])["prompt_tokens"] == 20


@pytest.mark.parametrize("fault", ["model", "count", "duplicate", "negative_index",
                                  "bool_index", "dimension", "bool", "nan", "inf", "zero"])
def test_invalid_vectors_fail(probe, fault):
    payload = response()
    if fault == "model":
        payload["model"] = "other"
    elif fault == "count":
        payload["data"].pop()
    elif fault == "duplicate":
        payload["data"][0]["index"] = payload["data"][1]["index"]
    elif fault == "negative_index":
        payload["data"][0]["index"] = -1
    elif fault == "bool_index":
        payload["data"][0]["index"] = True
    elif fault == "dimension":
        payload["data"][0]["embedding"].pop()
    elif fault == "zero":
        payload["data"][0]["embedding"] = [0.0] * 2048
    else:
        payload["data"][0]["embedding"][0] = {"bool": True, "nan": math.nan, "inf": math.inf}[fault]
    with pytest.raises(probe.ProbeError):
        probe.validate_vectors(payload, 2, 2048, "embedding-3")


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": -1, "total_tokens": 1},
                                  {"prompt_tokens": True, "total_tokens": 1},
                                  {"prompt_tokens": 2, "total_tokens": 1},
                                  {"prompt_tokens": 1, "total_tokens": 1, "completion_tokens": -1}])
def test_invalid_usage_is_not_zero(probe, usage):
    with pytest.raises(probe.ProbeError, match="usage_unknown"):
        probe.validate_usage(usage)


@pytest.mark.parametrize("field,value", [
    ("endpoint", "http://open.bigmodel.cn/api/paas/v4/embeddings"),
    ("endpoint", "https://attacker.example/embeddings"),
    ("endpoint", "https://user@open.bigmodel.cn/api/paas/v4/embeddings"),
    ("endpoint", "https://open.bigmodel.cn/api/paas/v4/embeddings?key=x"),
    ("endpoint", "https://open.bigmodel.cn/api/paas/v4/embeddings#x"),
    ("model", "other"), ("dimensions", 1024), ("timeout_seconds", 31),
    ("deadline_seconds", 121), ("max_requests", 3), ("budget_cny", 2),
    ("budget_cny", math.nan), ("unit_price_cny_per_million", math.inf),
])
def test_config_rejected_before_network(probe, config, field, value):
    config[field] = value
    with pytest.raises(probe.ProbeError, match="invalid_config"):
        probe.validate_config(config)


def test_missing_key_and_insufficient_budget_preflight(probe, config, monkeypatch):
    monkeypatch.delenv("NAIYUE_RAG_ZHIPU_API_KEY")
    with pytest.raises(probe.ProbeError, match="missing_key"):
        probe.run(config)
    monkeypatch.setenv("NAIYUE_RAG_ZHIPU_API_KEY", "offline-secret-sentinel")
    config["budget_cny"] = 0.00001
    with pytest.raises(probe.ProbeError, match="insufficient_budget"):
        probe.run(config)


def test_fixed_input_limit(probe, config):
    with pytest.raises(probe.ProbeError, match="invalid_input"):
        probe.send_embedding(config, ["x" * 201], "offline-secret-sentinel")
    with pytest.raises(probe.ProbeError, match="invalid_input"):
        probe.send_embedding(config, [], "offline-secret-sentinel")


def test_http_auth_body_timeout_and_redirect_handler(probe, config, monkeypatch):
    captured = {}
    class Reply:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps(response()).encode()
    class Opener:
        def open(self, request, timeout):
            captured.update(url=request.full_url, body=json.loads(request.data),
                            auth=request.get_header("Authorization"), timeout=timeout)
            return Reply()
    def build(handler):
        assert isinstance(handler, probe.NoRedirect)
        return Opener()
    monkeypatch.setattr(probe, "build_opener", build)
    probe.send_embedding(config, ["合成一", "合成二"], "offline-secret-sentinel")
    assert captured["auth"] == "Bearer offline-secret-sentinel"
    assert captured["body"] == {"model": "embedding-3", "dimensions": 2048, "input": ["合成一", "合成二"]}
    assert captured["timeout"] == 30
    assert captured["url"] == config["endpoint"]
    with pytest.raises(probe.ProbeError, match="redirect_rejected"):
        probe.NoRedirect().redirect_request(None, None, 302, "raw secret", {}, "https://other.example")


@pytest.mark.parametrize("fault", ["http", "timeout", "url", "json"])
def test_transport_failures_sanitized(probe, config, monkeypatch, fault):
    class Reply:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b"offline-secret-sentinel: invalid JSON"
    class Opener:
        def open(self, *args, **kwargs):
            if fault == "http":
                raise HTTPError(config["endpoint"], 401, "offline-secret-sentinel", {}, None)
            if fault == "timeout":
                raise TimeoutError("offline-secret-sentinel")
            if fault == "url":
                raise URLError("offline-secret-sentinel")
            return Reply()
    monkeypatch.setattr(probe, "build_opener", lambda handler: Opener())
    with pytest.raises(probe.ProbeError) as caught:
        probe.send_embedding(config, ["合成"], "offline-secret-sentinel")
    assert "offline-secret-sentinel" not in str(caught.value)
    if fault == "http":
        assert caught.value.http_status == 401


def test_worker_two_requests_reports_real_diagnostics(probe, config, monkeypatch):
    calls, checkpoints = [], []
    def send(cfg, texts, key):
        calls.append(texts)
        assert key == "offline-secret-sentinel"
        return response(len(texts))
    monkeypatch.setattr(probe, "send_embedding", send)
    result = probe.run_worker(config, checkpoints.append)
    assert [len(texts) for texts in calls] == [2, 1]
    assert result["status"] == "complete"
    assert result["attempt_count"] == 2
    assert result["estimated_cost_cny"] == pytest.approx(0.00002)
    assert result["provider_billed_cost_cny"] is None
    assert len(result["cosine_scores"]) == 2
    assert all(score["score"] == pytest.approx(1) for score in result["cosine_scores"])
    assert [v["input_id"] for v in result["requests"][0]["vectors"]] == ["S1", "S2"]
    assert all(v["dimensions"] == 2048 for row in result["requests"] for v in row["vectors"])
    assert "offline-secret-sentinel" not in json.dumps(result)
    assert "embedding" not in result["requests"][0]["vectors"][0]
    assert checkpoints[0]["attempt_count"] == 1


@pytest.mark.parametrize("fault", ["transport", "usage", "vectors", "limit"])
def test_worker_stops_without_retry_and_preserves_unknown(probe, config, monkeypatch, fault):
    calls = []
    def send(cfg, texts, key):
        calls.append(texts)
        if fault == "transport":
            raise probe.ProbeError("http", "transport_error", http_status=429)
        payload = response(len(texts))
        if fault == "usage":
            payload.pop("usage")
        if fault == "vectors":
            payload["data"][0]["embedding"] = []
        return payload
    if fault == "limit":
        config["max_requests"] = 1
    monkeypatch.setattr(probe, "send_embedding", send)
    result = probe.run_worker(config, lambda state: None)
    assert result["status"] == "error"
    assert len(calls) == result["attempt_count"] == 1
    assert result["cosine_scores"] is None
    if fault != "limit":
        assert result["estimated_cost_cny"] is None
    if fault == "usage":
        assert len(result["requests"][0]["vectors"]) == 2
        assert result["requests"][0]["usage"] is None


def test_cosine_zero_and_nonfinite_fail(probe):
    assert probe.cosine([1, 0], [0, 1]) == 0
    for vector in [[0, 0], [math.nan, 1]]:
        with pytest.raises(probe.ProbeError):
            probe.cosine(vector, [1, 0])


def test_parent_cli_supervision_and_unique_outputs(probe, config, monkeypatch, capsys):
    processes = []
    class Child:
        returncode = 0
        def __init__(self, command, **kwargs):
            assert command[-3:] == ["-m", "experiments.embedding_probe", "--worker"]
            assert "offline-secret-sentinel" not in str(command)
            processes.append(self)
        def communicate(self, input=None, timeout=None):
            assert 0 < timeout <= 120
            cfg = json.loads(input)
            monkeypatch.setattr(probe, "send_embedding", lambda c, t, k: response(len(t)))
            result = probe.run_worker(cfg, lambda state: None)
            return json.dumps({"event": "result", "summary": result}) + "\n", ""
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    first = probe.run(config)
    second = probe.run(config)
    assert first["output_dir"] != second["output_dir"]
    for item in [first, second]:
        folder = Path(item["output_dir"])
        assert json.loads((folder / "summary.json").read_text())["status"] == "complete"
        assert "0.00002" in (folder / "report.md").read_text()
    args = []
    for key, value in config.items():
        args.extend(["--" + key.replace("_", "-"), str(value)])
    assert probe.main(args) == 0
    assert "status=complete" in capsys.readouterr().out


def test_deadline_kills_child_and_keeps_attempt_unknown(probe, config, monkeypatch):
    state = probe.initial_summary(config)
    state["attempt_count"] = 1
    checkpoint = json.dumps({"event": "checkpoint", "summary": state}) + "\n"
    class Child:
        returncode = -9
        killed = False
        def __init__(self, *args, **kwargs):
            pass
        def communicate(self, input=None, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("safe-command", timeout, output=checkpoint)
            return checkpoint, "offline-secret-sentinel must not be printed"
        def kill(self):
            self.killed = True
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    result = probe.run(config)
    assert result["status"] == "error"
    assert result["attempt_count"] == 1
    assert result["sanitized_error"]["category"] == "deadline_exceeded"
    assert result["provider_billed_cost_cny"] is None
    assert "offline-secret-sentinel" not in json.dumps(result)


def test_total_deadline_includes_child_startup(probe, config, monkeypatch):
    moments = iter([1.0, 4.0])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(moments))
    state = probe.initial_summary(config)
    state["status"] = "complete"
    class Child:
        returncode = 0
        def __init__(self, *args, **kwargs):
            pass
        def communicate(self, input=None, timeout=None):
            assert timeout == 116
            return json.dumps({"event": "result", "summary": state}), ""
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    assert probe.supervise(config, 0)["status"] == "complete"


def test_output_conflict_and_write_failure(probe, config, monkeypatch):
    monkeypatch.setattr(probe, "new_run_id", lambda: "fixed")
    folder = Path(config["output_root"]) / "fixed"
    folder.mkdir(parents=True)
    marker = folder / "summary.json"
    marker.write_text("preserve")
    with pytest.raises(probe.ProbeError, match="output_error"):
        probe.run(config)
    assert marker.read_text() == "preserve"
    monkeypatch.setattr(probe, "new_run_id", lambda: "write-failure")
    monkeypatch.setattr(probe, "supervise", lambda cfg, start: probe.initial_summary(cfg))
    original = Path.open
    def fail_report(self, *args, **kwargs):
        if self.name == "report.md":
            raise PermissionError("offline-secret-sentinel")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_report)
    with pytest.raises(probe.ProbeError, match="output_error") as caught:
        probe.run(config)
    assert "offline-secret-sentinel" not in str(caught.value)


def test_worker_main_and_parent_missing_key_error(probe, config, monkeypatch, capsys):
    import io
    monkeypatch.setattr(probe.sys, "stdin", io.StringIO(json.dumps(config)))
    monkeypatch.setattr(probe, "send_embedding", lambda c, t, k: response(len(t)))
    assert probe.main(["--worker"]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[-1]["event"] == "result"
    assert records[-1]["summary"]["attempt_count"] == 2
    monkeypatch.delenv("NAIYUE_RAG_ZHIPU_API_KEY")
    args = []
    for key, value in config.items():
        args.extend(["--" + key.replace("_", "-"), str(value)])
    assert probe.main(args) == 2
    assert "missing_key" in capsys.readouterr().err
