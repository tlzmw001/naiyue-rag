"""Source-based diagnostics for the explicitly bounded Markdown experiment."""

import re
from bisect import bisect_right


def source_span(source, start, end):
    """Offsets are Unicode characters; line numbers refer to the untouched file."""
    return {
        "start_char": start, "end_char": end,
        "line_start": bisect_right(source["line_starts"], start),
        "line_end": bisect_right(source["line_starts"], end - 1),
        "source_sha256": source["source_sha256"],
    }


def table_cells(line):
    """Single physical pipe row only; escaped pipes remain inside their cell."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells, buffer, escaped = [], [], False
    for char in stripped[1:-1]:
        if char == "|" and not escaped:
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
        escaped = char == "\\" and not escaped
    cells.append("".join(buffer).strip())
    return cells


def inspect_document(source, chunks):
    """Return observations, including failures; never repair component output."""
    text = source["text"]
    if not text:
        return [{"probe_id": "empty_source", "scope": "document", "status": "not_applicable",
                 "expected_text": "", "expected_source_spans": [],
                 "observed_chunk_ordinals": [], "reason": "empty_source"}]
    probes = []

    def add(probe_id, expected, start, end, required=None, extra_spans=None,
            reason="source_text_preserved", force_failure=False):
        requirements = required if required is not None else [expected]
        found = [c["ordinal"] for c in chunks
                 if all(part in c["chunk_text"] for part in requirements)]
        probes.append({
            "probe_id": probe_id,
            "scope": "case" if probe_id.startswith("case_") else "block",
            "status": "pass" if found and not force_failure else "fail",
            "expected_text": expected,
            "expected_source_spans": [source_span(source, start, end)] + (extra_spans or []),
            "observed_chunk_ordinals": found,
            "reason": reason if found or force_failure else "required_source_text_not_in_one_chunk",
        })

    heading = None
    contexts = []
    header = None
    fence_start = None
    offset = 0
    for line_number, physical in enumerate(text.splitlines(keepends=True), 1):
        line = physical.rstrip("\r\n")
        start, end = offset, offset + len(line)
        offset += len(physical)
        if line.lstrip().startswith("```"):
            if fence_start is None:
                fence_start = start
            else:
                block = text[fence_start:end]
                add(f"code_block/L{line_number}", block, fence_start, end)
                fence_start = None
            continue
        if fence_start is not None:
            continue
        if re.match(r"^#{1,6}\s", line):
            heading = (line, start, end)
            contexts, header = [], None
        if line.lstrip().startswith(">"):
            contexts.append((line, start, end))

        for match in re.finditer(r"(?<![\w-])L(\d+)-L?(\d+)(?![\w-])", line):
            low, high = map(int, match.groups())
            if low < 1 or high < low or high > len(source["line_starts"]):
                add(f"source_warning/L{line_number}/{match.start()}", match.group(),
                    start + match.start(), start + match.end(),
                    reason="stale_header_line_range", force_failure=True)

        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", line):
            if "://" not in match.group(1) and not match.group(1).startswith("#"):
                add(f"link/L{line_number}/{match.start()}", match.group(),
                    start + match.start(), start + match.end())
        for match in re.finditer(r"`[^`]+`", line):
            add(f"inline_code/L{line_number}/{match.start()}", match.group(),
                start + match.start(), start + match.end())
        for match in re.finditer(r"\\\|", line):
            # Include surrounding cell text to distinguish this occurrence.
            left, right = max(0, match.start() - 12), min(len(line), match.end() + 12)
            add(f"escaped_pipe/L{line_number}/{match.start()}", line[left:right],
                start + left, start + right)

        cells = table_cells(line)
        # Breaks are checked in the complete containing cell, not by global counts.
        inline_parts = cells if cells is not None else [line]
        cursor = 0
        for part_number, part in enumerate(inline_parts):
            at = line.find(part, cursor)
            cursor = at + len(part)
            if "<br>" in part:
                add(f"inline_break/L{line_number}/{part_number}", part, start + at, start + cursor)
        if source["role"] != "historical_test_cases":
            continue
        if cells and cells[0] == "序号":
            header = (line, start, end) if len(cells) == 9 else None
            if header is None:
                add(f"source_warning/L{line_number}", line, start, end,
                    reason="unsupported_structure: expected nine header columns", force_failure=True)
        if not re.match(r"^\s*\|\s*TC-[A-Za-z0-9-]+\s*\|", line):
            continue
        if cells is None or len(cells) != 9:
            add(f"source_warning/L{line_number}", line, start, end,
                reason="unsupported_structure: expected one physical nine-column case row",
                force_failure=True)
            continue
        case_id = cells[0]
        suffix = f"{case_id}/L{line_number}"
        row_span = source_span(source, start, end)
        add(f"case_row/{suffix}", line, start, end)
        for kind, item in [("case_header", header), ("case_dimension", heading)]:
            if item is None or (kind == "case_dimension" and header is None):
                add(f"{kind}/{suffix}", line, start, end,
                    reason=f"missing_source_{kind}", force_failure=True)
            else:
                value, lo, hi = item
                required = [line, value]
                extra = [row_span]
                if kind == "case_dimension":
                    required.append(header[0])
                    extra.append(source_span(source, header[1], header[2]))
                add(f"{kind}/{suffix}", value, lo, hi, required=required, extra_spans=extra)
        if contexts:
            value = "\n".join(item[0] for item in contexts)
            spans = [source_span(source, item[1], item[2]) for item in contexts]
            add(f"case_context/{suffix}", value, contexts[0][1], contexts[0][2],
                required=[line] + [item[0] for item in contexts], extra_spans=spans[1:] + [row_span])
        else:
            probes.append({"probe_id": f"case_context/{suffix}", "scope": "case",
                           "status": "not_applicable", "expected_text": "",
                           "expected_source_spans": [row_span], "observed_chunk_ordinals": [],
                           "reason": "no_source_context"})
        condition = cells[2]
        if re.search(r"TC-[A-Za-z0-9-]+", condition):
            at = line.index(condition)
            add(f"case_reference/{suffix}", condition, start + at, start + at + len(condition))
    if fence_start is not None:
        add("source_warning/unclosed_fence", text[fence_start:], fence_start, len(text),
            reason="unsupported_structure: unclosed code fence", force_failure=True)
    return probes
