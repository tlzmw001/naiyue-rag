"""Observe three pinned Markdown splitters without building a RAG pipeline."""

import argparse
import hashlib
import json
import platform
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from experiments.markdown_checks import inspect_document, source_span

SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]


def load_sources(dataset_root):
    root = Path(dataset_root).resolve()
    knowledge = (root / "knowledge").resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        documents = manifest["documents"]
        if not isinstance(documents, list) or not documents:
            raise ValueError("documents must be a nonempty list")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"read_manifest: {type(exc).__name__}: {exc}") from exc
    if not knowledge.is_relative_to(root):
        raise ValueError("path_outside_knowledge: knowledge root escapes dataset")
    sources, identities = [], set()
    for doc in documents:
        try:
            given = Path(doc["path"])
            target = (root / given).resolve()
            if given.is_absolute() or not target.is_relative_to(knowledge):
                raise ValueError(f"path_outside_knowledge: {given}")
            relative = target.relative_to(knowledge).as_posix()
            doc_id = doc["document_id"]
            if doc_id in identities:
                raise ValueError(f"duplicate_document_id: {doc_id}")
            identities.add(doc_id)
            try:
                raw = target.read_bytes()
            except OSError as exc:
                raise ValueError(f"read_source: {relative}: {type(exc).__name__}") from exc
            digest = hashlib.sha256(raw).hexdigest()
            if digest != doc["sha256"]:
                raise ValueError(f"hash_mismatch: {relative}")
            try:
                text = raw.decode("utf-8")
            except UnicodeError as exc:
                raise ValueError(f"invalid_utf8: {relative}") from exc
            starts = [0] if text else []
            starts.extend(i + 1 for i, char in enumerate(text) if char == "\n" and i + 1 < len(text))
            sources.append({
                "document_id": doc_id, "relative_path": relative, "role": doc["role"],
                "semantic_level": doc["semantic_level"], "directory_level": doc["directory_level"],
                "source_sha256": digest, "text": text, "line_starts": starts,
            })
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid_source_record: {type(exc).__name__}") from exc
    return sources


def map_exact_source(source, chunk_text):
    if not chunk_text:
        return "unmapped", []
    spans, cursor = [], 0
    while True:
        start = source["text"].find(chunk_text, cursor)
        if start < 0:
            break
        end = start + len(chunk_text)
        spans.append(source_span(source, start, end))
        cursor = start + 1
    if not spans:
        return "unmapped", []
    return ("exact" if len(spans) == 1 else "ambiguous"), spans


def split_candidate(source, candidate, size, overlap):
    if not source["text"]:
        return []
    if candidate in ("C0", "C1"):
        from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
        recursive = RecursiveCharacterTextSplitter(
            chunk_size=size, chunk_overlap=overlap, separators=SEPARATORS,
            length_function=len, is_separator_regex=False,
        )
        if candidate == "C0":
            native = [(part, {}) for part in recursive.split_text(source["text"])]
        else:
            headings = MarkdownHeaderTextSplitter(
                headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
                strip_headers=False, return_each_line=False,
            )
            grouped = headings.split_text(source["text"])
            native = [(doc.page_content, doc.metadata) for doc in recursive.split_documents(grouped)]
    elif candidate == "C2":
        from llama_index.core import Document
        from llama_index.core.node_parser import MarkdownNodeParser
        parser = MarkdownNodeParser.from_defaults(include_metadata=True, include_prev_next_rel=False)
        nodes = parser.get_nodes_from_documents([Document(text=source["text"])])
        native = [(node.text, node.metadata) for node in nodes]
    else:
        raise ValueError(f"unknown_candidate: {candidate}")
    chunks = []
    for ordinal, (text, metadata) in enumerate(native):
        state, spans = map_exact_source(source, text)
        chunks.append({
            "candidate": candidate, "variant": "native" if candidate == "C2" else str(size),
            "document_id": source["document_id"], "ordinal": ordinal,
            "chunk_text": text, "native_metadata": metadata, "character_count": len(text),
            "mapping_status": state, "source_spans": spans,
        })
    return chunks


def new_run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def build_report(summary, chunks):
    lines = ["# Markdown组件实际诊断", "", f"运行：{summary['run_id']}；状态：{summary['status']}",
             "", "输入完全合成；pass/fail只描述结构探针，不是检索质量或框架最终选择。",
             "C2为原生章节节点，没有与C0/C1相同的字符预算。", "",
             "| 配置 | 片段数 | exact / ambiguous / unmapped | 完整用例行 | 行+表头 | 行+表头+维度 | 行+来源说明 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    groups = {}
    for result in summary["results"]:
        groups.setdefault((result["candidate"], result["variant"]), []).append(result)
    for (candidate, variant), results in groups.items():
        selected = [c for c in chunks if c["candidate"] == candidate and c["variant"] == variant]
        mapping = Counter(c["mapping_status"] for c in selected)
        probes = [p for r in results for p in r["probes"]]
        stats = []
        for prefix in ["case_row/", "case_header/", "case_dimension/", "case_context/"]:
            applicable = [p for p in probes if p["probe_id"].startswith(prefix)
                          and p["status"] != "not_applicable"]
            stats.append(f"{sum(p['status'] == 'pass' for p in applicable)}/{len(applicable)}")
        lines.append(f"| {candidate}/{variant} | {len(selected)} | "
                     f"{mapping['exact']} / {mapping['ambiguous']} / {mapping['unmapped']} | "
                     + " | ".join(stats) + " |")
        if any(r["status"] == "error" for r in results):
            lines.append(f"\n**{candidate}/{variant} error**：部分组件配置执行失败，见summary.json。\n")
    for (candidate, variant), results in groups.items():
        selected = [c for c in chunks if c["candidate"] == candidate and c["variant"] == variant]
        lines.extend(["", f"## {candidate}/{variant} 代表性证据", ""])
        # Prefer a broken row, then context/position problems; show actual data.
        candidates = [(r, p) for r in results for p in r["probes"] if p["status"] == "fail"]
        candidates.sort(key=lambda pair: (not pair[1]["probe_id"].startswith("case_row/"),
                                          not pair[1]["probe_id"].startswith("case_header/")))
        if candidates:
            result, item = candidates[0]
            same_doc = [c for c in selected if c["document_id"] == result["document_id"]]
            probe_text = item["expected_text"]
            excerpt_key = probe_text[:20]
            related = [c for c in same_doc if excerpt_key and excerpt_key in c["chunk_text"]]
            if not related:
                related = same_doc[:1]
            lines.extend([f"fail：{result['relative_path']}；{item['probe_id']}；{item['reason']}",
                          "", "源探针（附加上下文的出处分列于summary.json）：", "", "````markdown",
                          probe_text, "````", "", "实际组件片段（显示前1000字符，完整文本见chunks.jsonl）："])
            for chunk in related[:2]:
                lines.extend(["", f"ordinal={chunk['ordinal']}；chars={chunk['character_count']}；"
                              f"mapping={chunk['mapping_status']}；metadata={json.dumps(chunk['native_metadata'], ensure_ascii=False)}",
                              "", "````markdown", chunk["chunk_text"][:1000], "````"])
        unmapped = next((c for c in selected if c["mapping_status"] == "unmapped"), None)
        if unmapped:
            lines.extend(["", f"无法精确定位：document={unmapped['document_id']} ordinal={unmapped['ordinal']}；"
                          "输出未找到完全相同的源子串，不强填行号。", "", "````markdown",
                          unmapped["chunk_text"][:1000], "````"])
    lines.extend(["", "## 状态与限制", "",
                  f"诊断计数：{json.dumps(summary['probe_counts'], ensure_ascii=False)}",
                  "实际耗时包含首次组件初始化，不能作为性能排名。",
                  "Markdown识别仅覆盖本Spec的Mock语法；尚无生产解析器、索引、Embedding、图或检索评测。",
                  "模型调用：0；模型token/费用：不适用。", ""])
    return "\n".join(lines)


def run(dataset_root, sizes, overlap, output_root):
    if not sizes or any(size <= 0 for size in sizes) or overlap < 0 or overlap >= min(sizes):
        raise ValueError("invalid_parameters: sizes>0 and 0<=overlap<min(sizes) required")
    if len(set(sizes)) != len(sizes):
        raise ValueError("invalid_parameters: duplicate sizes")
    sources = load_sources(dataset_root)
    run_id = new_run_id()
    folder = Path(output_root).resolve() / run_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(f"output_exists: {folder}") from exc
    except OSError as exc:
        raise ValueError(f"write_report: create_directory: {type(exc).__name__}") from exc
    versions = {name: version(name) for name in ["langchain-text-splitters", "llama-index-core", "pytest"]}
    configs = [(candidate, size) for candidate in ["C0", "C1"] for size in sizes] + [("C2", None)]
    summary = {
        "schema_version": 1, "run_id": run_id, "status": "complete", "output_dir": str(folder),
        "python": platform.python_version(), "versions": versions,
        "parameters": {"sizes": sizes, "overlap": overlap, "length_unit": "python_characters",
                       "separators": SEPARATORS, "is_separator_regex": False,
                       "recursive_defaults": {"keep_separator": True, "strip_whitespace": True},
                       "headers": [["#", "h1"], ["##", "h2"], ["###", "h3"]],
                       "strip_headers": False, "return_each_line": False,
                       "include_metadata": True, "include_prev_next_rel": False},
        "sources": [{key: value for key, value in s.items() if key not in ("text", "line_starts")}
                    for s in sources], "results": [],
    }
    all_chunks = []
    began = time.perf_counter()
    for candidate, size in configs:
        variant = "native" if candidate == "C2" else str(size)
        for source in sources:
            print(f"split {candidate}/{variant} {source['relative_path']}", file=sys.stderr)
            started = time.perf_counter()
            result = {"candidate": candidate, "variant": variant, "document_id": source["document_id"],
                      "relative_path": source["relative_path"], "status": "complete", "probes": []}
            try:
                chunks = split_candidate(source, candidate, size, overlap)
                if source["text"] and not chunks:
                    raise ValueError("nonempty_zero_chunks")
                result["probes"] = inspect_document(source, chunks)
                result["chunk_count"] = len(chunks)
                result["max_characters"] = max((c["character_count"] for c in chunks), default=0)
                result["mapping_counts"] = dict(Counter(c["mapping_status"] for c in chunks))
                result["oversize_counts"] = {str(limit): sum(c["character_count"] > limit for c in chunks)
                                             for limit in sizes}
                all_chunks.extend(chunks)
            except Exception as exc:
                # Keep a failed configuration distinct from empty successful data.
                result["status"] = "error"
                result["error"] = f"{type(exc).__name__}: {exc}"
                summary["status"] = "error"
                print(f"component_error {candidate}/{variant} {source['relative_path']}: {result['error']}",
                      file=sys.stderr)
            result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            summary["results"].append(result)
    counts = Counter(p["status"] for r in summary["results"] for p in r["probes"])
    summary["probe_counts"] = {state: counts[state] for state in ["pass", "fail", "not_applicable"]}
    summary["elapsed_ms"] = round((time.perf_counter() - began) * 1000, 3)
    try:
        with (folder / "chunks.jsonl").open("x", encoding="utf-8") as handle:
            for chunk in all_chunks:
                handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        (folder / "report.md").write_text(build_report(summary, all_chunks), encoding="utf-8")
        # Commit the completion/error summary last; partial writes are not success.
        with (folder / "summary.json").open("x", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"write_report: {type(exc).__name__}: {exc}") from exc
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", required=True)
    parser.add_argument("--overlap", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run(args.dataset, args.sizes, args.overlap, args.output_root)
    except (ValueError, OSError) as exc:
        print(f"experiment_error: {exc}", file=sys.stderr)
        return 2
    print(f"status={summary['status']} document_configs={len(summary['results'])} "
          f"probes={summary['probe_counts']} output={summary['output_dir']}")
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
