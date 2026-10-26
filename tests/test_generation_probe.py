"""Spec 0003: network-blocked contracts, synthetic expectations only."""

import copy
import importlib
import io
import json
import socket
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

SOURCE_LINES = ["派生分由概率原始值与价值原始值相乘得到。", "新需求取消派生分校准。", "基础分继续校准。"]
DATA = {
    "entities": [{"name": name, "quote": quote} for name, quote in [
        ("派生分", SOURCE_LINES[0]), ("概率原始值", SOURCE_LINES[0]),
        ("价值原始值", SOURCE_LINES[0]), ("校准", SOURCE_LINES[1]), ("基础分", SOURCE_LINES[2])]],
    "relations": [{"subject": subject, "predicate": predicate, "object": target, "quote": quote}
                  for subject, predicate, target, quote in [
                      ("派生分", "computed_from", "概率原始值", SOURCE_LINES[0]),
                      ("派生分", "computed_from", "价值原始值", SOURCE_LINES[0]),
                      ("派生分", "calibration_removed", "校准", SOURCE_LINES[1]),
                      ("基础分", "calibration_retained", "校准", SOURCE_LINES[2])]],
    "keywords": ["派生分", "基础分", "校准"],
}


def payload():
    return {"model": "glm-5.2", "choices": [{"index": 0, "finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(DATA, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("real network forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid)
    monkeypatch.setenv("NAIYUE_RAG_ZHIPU_API_KEY", "offline-secret-sentinel")


@pytest.fixture
def probe():
    return importlib.import_module("experiments.generation_probe")


@pytest.fixture
def config(tmp_path):
    return {"endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-5.2",
            "max_tokens": 1024, "timeout_seconds": 30, "deadline_seconds": 120, "max_requests": 1,
            "input_price_cny_per_million": 8, "output_price_cny_per_million": 28,
            "output_root": str(tmp_path / "runs")}


@pytest.mark.parametrize("field,value", [
    ("endpoint", "http://open.bigmodel.cn/api/paas/v4/chat/completions"),
    ("endpoint", "https://example.com/chat/completions"), ("model", "glm-4.7"),
    ("max_tokens", 1025), ("max_tokens", True), ("timeout_seconds", 31),
    ("deadline_seconds", 121), ("max_requests", 2), ("max_requests", 0),
    ("input_price_cny_per_million", float("nan")), ("output_price_cny_per_million", -1),
    ("output_root", "")])
def test_invalid_config_before_network(probe, config, field, value):
    config[field] = value
    with pytest.raises(probe.ProbeError, match="invalid_config"):
        probe.validate_config(config)


def test_request_body_is_explicit_and_contains_no_key(probe, config):
    body = probe.build_request(config)
    assert body["model"] == "glm-5.2"
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 1024 and body["stream"] is False
    assert "tools" not in body and "reasoning_effort" not in body
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert all(line in body["messages"][1]["content"] for line in SOURCE_LINES)
    assert "offline-secret-sentinel" not in json.dumps(body)


def test_prompt_defines_calibration_object_and_literal_quote(probe, config):
    instruction = probe.build_request(config)["messages"][0]["content"]
    assert "校准类关系的subject为被校准对象，object必须为原词“校准”" in instruction
    assert "逐字复制quote，保留原文换行，不删除换行或拼接改写" in instruction


def test_valid_extraction_and_synthetic_fact_checks(probe):
    result = probe.validate_extraction(json.dumps(DATA, ensure_ascii=False))
    assert result == DATA
    checks = probe.assess_extraction(result)
    assert checks["passed"] is True
    assert checks["matched_relation_count"] == checks["required_relation_count"] == 4
    assert checks["missing_relations"] == checks["unsupported_relations"] == []
    assert checks["missing_keywords"] == []


def test_valid_schema_does_not_prove_semantics(probe):
    data = copy.deepcopy(DATA)
    data["relations"][-1]["predicate"] = "calibration_removed"
    data["keywords"] = ["回归"]
    checked = probe.validate_extraction(json.dumps(data, ensure_ascii=False))
    checks = probe.assess_extraction(checked)
    assert checks["passed"] is False and checks["matched_relation_count"] == 3
    assert len(checks["unsupported_relations"]) == len(checks["missing_relations"]) == 1
    assert set(checks["missing_keywords"]) == {"派生分", "基础分", "校准"}


@pytest.mark.parametrize("fault", ["top", "extra", "empty_entities", "entity_name", "quote",
    "duplicate_entity", "endpoint", "predicate", "relation_quote", "keyword", "keyword_duplicate"])
def test_invalid_extraction_is_explicit(probe, fault):
    data = copy.deepcopy(DATA)
    if fault == "top":
        data = []
    elif fault == "extra":
        data["answer"] = "extra"
    elif fault == "empty_entities":
        data["entities"] = []
    elif fault == "entity_name":
        data["entities"][0]["name"] = "不存在的实体"
    elif fault == "quote":
        data["entities"][0]["quote"] = "无出处"
    elif fault == "duplicate_entity":
        data["entities"].append(data["entities"][0])
    elif fault == "endpoint":
        data["relations"][0]["object"] = "未列实体"
    elif fault == "predicate":
        data["relations"][0]["predicate"] = "invented"
    elif fault == "relation_quote":
        data["relations"][0]["quote"] = SOURCE_LINES[2]
    elif fault == "keyword":
        data["keywords"] = [""]
    else:
        data["keywords"].append("派生分")
    with pytest.raises(probe.ProbeError, match="invalid_extraction"):
        probe.validate_extraction(json.dumps(data, ensure_ascii=False))


@pytest.mark.parametrize("text", ['{"entities": [], "entities": []}', '```json\n{}\n```', '{'])
def test_duplicate_keys_and_non_json_are_rejected(probe, text):
    with pytest.raises(probe.ProbeError, match="invalid_extraction"):
        probe.validate_extraction(text)


@pytest.mark.parametrize("fault", ["model", "choices", "index", "role", "tool", "length", "empty"])
def test_response_envelope_validation(probe, fault):
    response = payload()
    choice = response["choices"][0]
    if fault == "model":
        response["model"] = "other"
    elif fault == "choices":
        response["choices"] = []
    elif fault == "index":
        choice["index"] = True
    elif fault == "role":
        choice["message"]["role"] = "tool"
    elif fault == "tool":
        choice["message"]["tool_calls"] = [{"type": "function"}]
    elif fault == "length":
        choice["finish_reason"] = "length"
    else:
        choice["message"]["content"] = ""
    with pytest.raises(probe.ProbeError):
        probe.validate_response(response, "glm-5.2")


@pytest.mark.parametrize("usage", [None, {"prompt_tokens": 100, "total_tokens": 100},
    {"prompt_tokens": True, "completion_tokens": 50, "total_tokens": 51},
    {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 100}])
def test_unknown_or_inconsistent_usage(probe, usage):
    with pytest.raises(probe.ProbeError, match="usage_unknown"):
        probe.generation_usage(usage)


def test_actual_http_request_contract(probe, config, monkeypatch):
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            assert limit == 1024 * 1024 + 1
            return json.dumps(payload()).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == config["endpoint"] and request.method == "POST"
            assert request.get_header("Authorization") == "Bearer offline-secret-sentinel"
            assert json.loads(request.data) == probe.build_request(config)
            assert timeout == 30
            return Reply()
    def opener(handler):
        assert isinstance(handler, probe.NoRedirect)
        return Opener()
    monkeypatch.setattr(probe, "build_opener", opener)
    assert probe.send_generation(config, "offline-secret-sentinel") == payload()


@pytest.mark.parametrize("fault", ["http", "timeout", "url", "json", "large", "secret"])
def test_http_failure_never_leaks_key(probe, config, monkeypatch, fault):
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            if fault == "large": return b"x" * limit
            if fault == "secret": return b'{"value":"offline-secret-sentinel"}'
            return b"{"
    class Opener:
        def open(self, *args, **kwargs):
            if fault == "http": raise HTTPError(config["endpoint"], 401, "offline-secret-sentinel", {}, None)
            if fault == "timeout": raise TimeoutError("offline-secret-sentinel")
            if fault == "url": raise URLError("offline-secret-sentinel")
            return Reply()
    monkeypatch.setattr(probe, "build_opener", lambda handler: Opener())
    with pytest.raises(probe.ProbeError) as caught:
        probe.send_generation(config, "offline-secret-sentinel")
    assert "offline-secret-sentinel" not in str(caught.value)


def test_worker_single_request_records_real_usage_and_output(probe, config, monkeypatch):
    calls, checkpoints = [], []
    def send(cfg, key):
        calls.append(cfg)
        assert key == "offline-secret-sentinel"
        return payload()
    monkeypatch.setattr(probe, "send_generation", send)
    result = probe.run_worker(config, checkpoints.append)
    assert result["status"] == "complete" and len(calls) == result["attempt_count"] == 1
    assert checkpoints[0]["attempt_count"] == 1 and checkpoints[0]["usage"] is None
    assert result["extraction"] == DATA and result["quality_checks"]["passed"]
    assert result["estimated_cost_cny"] == pytest.approx(0.0022)
    assert result["provider_billed_cost_cny"] is None
    assert "offline-secret-sentinel" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["http", "usage", "length", "schema", "model", "thinking"])
def test_worker_failure_no_retry_usage_preserved(probe, config, monkeypatch, fault):
    calls = []
    def send(cfg, key):
        calls.append(1)
        if fault == "http": raise probe.ProbeError("http", "http_error", 429)
        response = payload()
        if fault == "usage": response.pop("usage")
        if fault == "length": response["choices"][0]["finish_reason"] = "length"
        if fault == "schema": response["choices"][0]["message"]["content"] = "{}"
        if fault == "model": response["model"] = "other"
        if fault == "thinking": response["choices"][0]["message"]["reasoning_content"] = "unexpected reasoning"
        return response
    monkeypatch.setattr(probe, "send_generation", send)
    result = probe.run_worker(config, lambda state: None)
    assert len(calls) == result["attempt_count"] == 1 and result["status"] == "error"
    assert result["sanitized_error"] and result["extraction"] is None
    if fault in ["http", "usage"]:
        assert result["estimated_cost_cny"] is None
    else:
        assert result["estimated_cost_cny"] == pytest.approx(0.0022)
    if fault == "length": assert result["finish_reason"] == "length"
    if fault == "thinking": assert result["reasoning_characters"] == 20


def test_semantic_failure_is_observed_without_fake_success(probe, config, monkeypatch):
    response = payload()
    data = copy.deepcopy(DATA)
    data["relations"] = []
    response["choices"][0]["message"]["content"] = json.dumps(data)
    monkeypatch.setattr(probe, "send_generation", lambda cfg, key: response)
    result = probe.run_worker(config, lambda state: None)
    assert result["status"] == "complete" and result["quality_checks"]["passed"] is False
    assert len(result["quality_checks"]["missing_relations"]) == 4


def test_failed_extraction_keeps_synthetic_content_and_specific_rule(probe, config, monkeypatch):
    response = payload()
    data = copy.deepcopy(DATA)
    data["entities"][0]["quote"] = "不存在于来源的引用"
    content = json.dumps(data, ensure_ascii=False)
    response["choices"][0]["message"]["content"] = content
    monkeypatch.setattr(probe, "send_generation", lambda cfg, key: response)
    result = probe.run_worker(config, lambda state: None)
    assert result["status"] == "error" and result["extraction"] is None
    assert result["completion_content"] == content
    assert result["sanitized_error"]["category"] == "invalid_extraction_entity_quote"
    assert content in probe.build_report(result)


def test_decoded_secret_rejected_before_diagnostics(probe, config, monkeypatch):
    response = payload()
    response["choices"][0]["message"]["content"] = "offline-secret-sentinel"
    monkeypatch.setattr(probe, "send_generation", lambda cfg, key: response)
    result = probe.run_worker(config, lambda state: None)
    assert result["status"] == "error"
    assert result["sanitized_error"]["category"] == "secret_in_response"
    assert "offline-secret-sentinel" not in json.dumps(result)


def test_valid_response_content_field_is_serialized(probe, config, monkeypatch):
    response = payload()
    monkeypatch.setattr(probe, "send_generation", lambda cfg, key: response)
    result = probe.run_worker(config, lambda state: None)
    assert result["schema_version"] == 2
    assert result["completion_content"] == response["choices"][0]["message"]["content"]


def test_cli_outputs_and_worker_dispatch(probe, config, monkeypatch, capsys):
    class Child:
        returncode = 0
        def __init__(self, command, **kwargs):
            assert command[-3:] == ["-m", "experiments.generation_probe", "--worker"]
            assert "offline-secret-sentinel" not in str(command)
        def communicate(self, input=None, timeout=None):
            assert 0 < timeout <= 120
            monkeypatch.setattr(probe, "send_generation", lambda cfg, key: payload())
            result = probe.run_worker(json.loads(input), lambda state: None)
            return json.dumps({"event": "result", "summary": result}), ""
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    first, second = probe.run(config), probe.run(config)
    assert first["output_dir"] != second["output_dir"]
    assert json.loads((Path(first["output_dir"]) / "summary.json").read_text())["extraction"] == DATA
    report = (Path(first["output_dir"]) / "report.md").read_text()
    assert "0.0022" in report and "unknown" in report and "派生分" in report
    args = [part for key, value in config.items() for part in ["--" + key.replace("_", "-"), str(value)]]
    assert probe.main(args) == 0
    assert "status=complete" in capsys.readouterr().out
    monkeypatch.setattr(probe.sys, "stdin", io.StringIO(json.dumps(config)))
    assert probe.main(["--worker"]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[-1]["summary"]["attempt_count"] == 1


def test_deadline_retains_inflight_attempt_and_unknown_cost(probe, config, monkeypatch):
    checkpoint = probe.initial_summary(config)
    checkpoint["attempt_count"] = 1
    class Child:
        returncode = -9
        killed = False
        def __init__(self, *args, **kwargs): pass
        def communicate(self, input=None, timeout=None):
            if not self.killed: raise subprocess.TimeoutExpired("worker", timeout)
            return json.dumps({"event": "checkpoint", "summary": checkpoint}), "offline-secret-sentinel"
        def kill(self): self.killed = True
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    result = probe.run(config)
    assert result["attempt_count"] == 1 and result["estimated_cost_cny"] is None
    assert result["sanitized_error"]["category"] == "deadline_exceeded"
    assert "offline-secret-sentinel" not in json.dumps(result)


def test_startup_time_is_deducted(probe, config, monkeypatch):
    times = iter([1.0, 4.0])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(times))
    class Child:
        returncode = 2
        def __init__(self, *args, **kwargs): pass
        def communicate(self, input=None, timeout=None):
            assert timeout == 116
            return json.dumps({"event": "result", "summary": probe.initial_summary(config)}), ""
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    probe.supervise(config, 0)


def test_missing_key_and_output_conflict(probe, config, monkeypatch):
    monkeypatch.delenv("NAIYUE_RAG_ZHIPU_API_KEY")
    with pytest.raises(probe.ProbeError, match="missing_key"): probe.run(config)
    monkeypatch.setenv("NAIYUE_RAG_ZHIPU_API_KEY", "offline-secret-sentinel")
    monkeypatch.setattr(probe, "new_run_id", lambda: "fixed")
    folder = Path(config["output_root"]) / "fixed"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text("preserve")
    with pytest.raises(probe.ProbeError, match="output_error"): probe.run(config)
    assert (folder / "summary.json").read_text() == "preserve"


def test_write_failure_has_safe_error_and_no_completion_marker(probe, config, monkeypatch):
    monkeypatch.setattr(probe, "new_run_id", lambda: "write-failure")
    monkeypatch.setattr(probe, "supervise", lambda cfg, started: probe.initial_summary(cfg))
    original_open = Path.open
    def failed_open(path, *args, **kwargs):
        if path.name == "report.md": raise PermissionError("offline-secret-sentinel")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", failed_open)
    with pytest.raises(probe.ProbeError, match="output_error") as caught:
        probe.run(config)
    assert "offline-secret-sentinel" not in str(caught.value)
    assert not (Path(config["output_root"]) / "write-failure" / "summary.json").exists()


def test_invalid_worker_output_is_explicit(probe, config, monkeypatch):
    class Child:
        returncode = 0
        def __init__(self, *args, **kwargs): pass
        def communicate(self, **kwargs): return "not-json", "offline-secret-sentinel"
    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    result = probe.run(config)
    assert result["status"] == "error" and result["attempt_count"] == 0
    assert result["sanitized_error"]["category"] == "invalid_worker_output"
    assert "offline-secret-sentinel" not in json.dumps(result)


def test_spawn_error_and_expired_deadline(probe, config, monkeypatch):
    def failed_spawn(*args, **kwargs): raise OSError("offline-secret-sentinel")
    monkeypatch.setattr(probe.subprocess, "Popen", failed_spawn)
    with pytest.raises(probe.ProbeError, match="spawn_error") as caught:
        probe.supervise(config, probe.time.monotonic())
    assert "offline-secret-sentinel" not in str(caught.value)
    monkeypatch.setattr(probe.time, "monotonic", lambda: 121)
    result = probe.supervise(config, 0)
    assert result["attempt_count"] == 0 and result["sanitized_error"]["category"] == "deadline_exceeded"
