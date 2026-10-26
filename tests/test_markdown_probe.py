"""Offline experiment contracts; red first, without implementation imports at collection."""

import hashlib
import importlib
import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "examples/mock-v1"


@pytest.fixture
def probe():
    return importlib.import_module("experiments.markdown_probe")


@pytest.fixture
def dataset(tmp_path):
    def create(raw=b"# Heading\n\nContent.\n", role="module"):
        base = tmp_path / "dataset"
        folder = base / "knowledge"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sample.md").write_bytes(raw)
        doc = {
            "document_id": "D1", "path": "knowledge/sample.md",
            "role": role, "semantic_level": "L1", "directory_level": "L1",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        (base / "manifest.json").write_text(json.dumps({"documents": [doc]}))
        return base
    return create


def test_reads_manifest_only_and_keeps_actual_crlf(probe, dataset):
    base = dataset("# 中文\r\n\r\n正文\r\n".encode())
    (base / "tasks.json").write_text("not valid JSON; must not be consumed")
    (base / "knowledge/extra.md").write_text("not listed")
    sources = probe.load_sources(base)
    assert len(sources) == 1
    source = sources[0]
    assert source["text"] == "# 中文\r\n\r\n正文\r\n"
    assert source["relative_path"] == "sample.md"
    state, spans = probe.map_exact_source(source, "正文")
    assert state == "exact"
    assert spans[0]["line_start"] == spans[0]["line_end"] == 3
    assert source["text"][spans[0]["start_char"]:spans[0]["end_char"]] == "正文"


def test_mapping_ambiguous_and_unmapped(probe, dataset):
    source = probe.load_sources(dataset("重复\n重复\n".encode()))[0]
    state, spans = probe.map_exact_source(source, "重复")
    assert state == "ambiguous"
    assert [p["line_start"] for p in spans] == [1, 2]
    assert probe.map_exact_source(source, "重 复") == ("unmapped", [])
    assert probe.map_exact_source(source, "") == ("unmapped", [])


def test_hash_mismatch_rejected(probe, dataset):
    base = dataset()
    (base / "knowledge/sample.md").write_text("changed")
    with pytest.raises(ValueError, match="hash_mismatch"):
        probe.load_sources(base)


def test_invalid_utf8_rejected(probe, dataset):
    with pytest.raises(ValueError, match="invalid_utf8"):
        probe.load_sources(dataset(b"\xff"))


@pytest.mark.parametrize("path", ["../outside.md", "/absolute.md"])
def test_manifest_path_escape_rejected(probe, dataset, path):
    base = dataset()
    manifest = json.loads((base / "manifest.json").read_text())
    manifest["documents"][0]["path"] = path
    (base / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="path_outside_knowledge"):
        probe.load_sources(base)


def test_symlink_escape_rejected(probe, dataset, tmp_path):
    base = dataset()
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    (base / "knowledge/sample.md").unlink()
    (base / "knowledge/sample.md").symlink_to(outside)
    with pytest.raises(ValueError, match="path_outside_knowledge"):
        probe.load_sources(base)


def test_missing_source_and_manifest_observable(probe, dataset, tmp_path):
    with pytest.raises(ValueError, match="read_manifest"):
        probe.load_sources(tmp_path / "missing")
    base = dataset()
    (base / "knowledge/sample.md").unlink()
    with pytest.raises(ValueError, match="read_source"):
        probe.load_sources(base)


@pytest.mark.parametrize("sizes,overlap", [([0], 0), ([-1], 0), ([512], -1), ([512], 512)])
def test_invalid_parameters_fail_before_execution(probe, dataset, tmp_path, sizes, overlap):
    with pytest.raises(ValueError, match="invalid_parameters"):
        probe.run(dataset(), sizes, overlap, tmp_path / "output")


@pytest.mark.parametrize("candidate", ["C0", "C1", "C2"])
def test_empty_document_has_no_fabricated_chunks(probe, dataset, candidate):
    source = probe.load_sources(dataset(b""))[0]
    assert probe.split_candidate(source, candidate, 512, 0) == []


def test_component_failure_is_not_empty_success(probe, dataset, tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("injected component failure")
    monkeypatch.setattr(probe, "split_candidate", fail)
    summary = probe.run(dataset(), [512, 1024], 0, tmp_path / "output")
    assert summary["status"] == "error"
    assert len(summary["results"]) == 5
    assert all(r["status"] == "error" and "injected" in r["error"] for r in summary["results"])


def test_nonempty_zero_chunks_is_error(probe, dataset, tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "split_candidate", lambda *args: [])
    summary = probe.run(dataset(), [512], 0, tmp_path / "output")
    assert summary["status"] == "error"
    assert all("nonempty_zero_chunks" in r["error"] for r in summary["results"])


def test_output_conflict_and_write_failure_are_observable(probe, dataset, tmp_path, monkeypatch):
    base = dataset()
    monkeypatch.setattr(probe, "new_run_id", lambda: "same-run")
    output = tmp_path / "output"
    (output / "same-run").mkdir(parents=True)
    with pytest.raises(ValueError, match="output_exists"):
        probe.run(base, [512], 0, output)
    monkeypatch.setattr(probe, "new_run_id", lambda: "write-failure")
    original = Path.write_text
    def fail_report(self, *args, **kwargs):
        if self.name == "report.md":
            raise PermissionError("injected write failure")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail_report)
    with pytest.raises(ValueError, match="write_report"):
        probe.run(base, [512], 0, output)


def test_main_rejects_bad_input(probe, tmp_path, capsys):
    code = probe.main(["--dataset", str(tmp_path / "absent"), "--sizes", "512",
                       "--overlap", "0", "--output-root", str(tmp_path / "output")])
    assert code == 2
    assert "read_manifest" in capsys.readouterr().err


def test_main_returns_error_for_component_failure(probe, dataset, tmp_path, monkeypatch, capsys):
    def fail(*args):
        raise RuntimeError("broken component")
    monkeypatch.setattr(probe, "split_candidate", fail)
    code = probe.main(["--dataset", str(dataset()), "--sizes", "512", "--overlap", "0",
                       "--output-root", str(tmp_path / "output")])
    assert code == 2
    assert "status=error" in capsys.readouterr().out


def test_all_candidates_offline_reports_reproducible_and_sources_unchanged(probe, tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network access forbidden in offline probe")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (MOCK / "knowledge").rglob("*.md")}
    first = probe.run(MOCK, [512, 1024], 0, tmp_path / "output")
    second = probe.run(MOCK, [512, 1024], 0, tmp_path / "output")
    assert first["status"] == second["status"] == "complete"
    assert len(first["results"]) == 60
    assert first["versions"]["langchain-text-splitters"] == "1.1.3"
    assert first["versions"]["llama-index-core"] == "0.14.25"
    assert first["output_dir"] != second["output_dir"]
    chunks = []
    for run in [first, second]:
        folder = Path(run["output_dir"])
        assert json.loads((folder / "summary.json").read_text())["status"] == "complete"
        rows = [json.loads(line) for line in (folder / "chunks.jsonl").read_text().splitlines()]
        assert {c["candidate"] for c in rows} == {"C0", "C1", "C2"}
        assert run["probe_counts"]["fail"] > 0
        assert "fail" in (folder / "report.md").read_text()
        chunks.append(rows)
    assert chunks[0] == chunks[1]
    assert [r["probes"] for r in first["results"]] == [r["probes"] for r in second["results"]]
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert before == after
    sources = {s["document_id"]: s for s in probe.load_sources(MOCK)}
    for chunk in chunks[0]:
        if chunk["mapping_status"] == "exact":
            assert len(chunk["source_spans"]) == 1
        for span in chunk["source_spans"]:
            source = sources[chunk["document_id"]]
            assert source["text"][span["start_char"]:span["end_char"]] == chunk["chunk_text"]
            assert span["source_sha256"] == source["source_sha256"]
