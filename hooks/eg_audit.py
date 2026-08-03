#!/usr/bin/env python3
"""evidence-gate v2 auditor — Claude Code Stop hook.

Implements the declare/enforce split described in
docs/DESIGN_declare_enforce_split.md: SKILL.md v2 declares the ledger
contract (Section 5), this script mechanically enforces it (Section 6,
rules R1-R6) by diffing the final assistant message of the current turn
against the session transcript.

Design contract (canonical, do not drift without updating the doc):
    docs/DESIGN_declare_enforce_split.md
        Section 5   — ledger grammar
        Section 6   — check rules R1-R6
        Section 7   — explicit limitations (semantic checks are out of
                      scope; this script only checks existence, timing,
                      and provenance)
        Appendix A  — ledger regex spec
        Appendix B  — mutation/delegation heuristics

Hard requirements from the contract:
    - stdlib only. No third-party imports.
    - fail-open: any exception, schema mismatch, or missing file must
      result in a clean exit(0). This hook must never brick a session.
    - warn mode never writes to stdout; it only appends to audit.log.
    - block mode writes {"decision": "block", "reason": "..."} to
      stdout and still exits 0 (Claude Code reads stdout, not the exit
      code, for the block decision).
    - stop_hook_active=true always downgrades block to warn (R6).

Stdin contract (Stop hook payload): a JSON object on stdin containing at
least {"session_id": str, "transcript_path": str, "stop_hook_active":
bool}. The real payload carries more fields (prompt_id, permission
mode, etc. — confirmed against Claude Code's own transcript files and
against the sibling Stop hook already registered in this environment,
~/.claude/hooks/evidence_gate.py) but this script only reads the three
above and ignores everything else defensively.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = "~/.claude/evidence-gate"
CONFIG_FILENAME = "config.json"
AUDIT_LOG_FILENAME = "audit.log"

# Safety cap: skip parsing (fail-open) rather than risk a pathological
# hang on a corrupted or absurdly large transcript. Real sessions in
# this workspace top out around ~1.8MB; 50MB is a generous margin.
MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024


def get_config_dir() -> str:
    d = os.environ.get("EG_CONFIG_DIR")
    if d:
        return os.path.expanduser(d)
    return os.path.expanduser(DEFAULT_CONFIG_DIR)


def load_config(config_dir: str) -> dict:
    """Load ~/.claude/evidence-gate/config.json. Defaults to warn mode.

    Any read/parse failure or malformed shape falls back to the default
    (fail-open — a broken config must not crash the hook or silently
    escalate to block).
    """
    default = {"mode": "warn", "extra_delegation_bash": [], "extra_write_hints": []}
    path = os.path.join(config_dir, CONFIG_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default
    if not isinstance(data, dict):
        return default
    mode = data.get("mode")
    if mode not in ("warn", "block"):
        mode = "warn"
    extra_delegation_bash = data.get("extra_delegation_bash")
    if not isinstance(extra_delegation_bash, list) or not all(isinstance(x, str) for x in extra_delegation_bash):
        extra_delegation_bash = []
    extra_write_hints = data.get("extra_write_hints")
    if not isinstance(extra_write_hints, list) or not all(isinstance(x, str) for x in extra_write_hints):
        extra_write_hints = []
    return {
        "mode": mode,
        "extra_delegation_bash": extra_delegation_bash,
        "extra_write_hints": extra_write_hints,
    }


def append_audit_log(config_dir: str, entry: dict) -> None:
    """Append one JSON line to audit.log. Never raises."""
    try:
        os.makedirs(config_dir, exist_ok=True)
        path = os.path.join(config_dir, AUDIT_LOG_FILENAME)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Appendix B — mutation / delegation heuristics (initial list, extensible
# via config.json's extra_delegation_bash / extra_write_hints)
# ---------------------------------------------------------------------------

MUTATION_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})

BASH_WRITE_HINTS = [
    r"(?<![2&])>(?!/dev/null)",
    r"\btee\b",
    r"\bsed\s+-i\b",
    r"^\s*(mv|cp|rm|mkdir|touch|chmod|ln)\b",
    r"\bgit\s+(commit|checkout|reset|merge|rebase|apply|cherry-pick|stash|push)\b",
    r"\b(npm\s+(i|install|update)|pip3?\s+install)\b",
]

DELEGATION_TOOLS = frozenset({"Agent", "Task", "Workflow"})
DELEGATION_MCP_PREFIXES = ("mcp__codex__", "mcp__gemini__")

DELEGATION_BASH = [
    r"^\s*(grok|codex|gemini)\b",
    r"^\s*claude\s+(-p|--print)\b",
    r"\borca\s+orchestration\b",
]


def _compile_patterns(patterns: list) -> list:
    compiled = []
    for p in patterns:
        if not isinstance(p, str):
            continue
        try:
            compiled.append(re.compile(p))
        except re.error:
            continue
    return compiled


# ---------------------------------------------------------------------------
# Appendix A — ledger regex spec (verbatim from the design doc)
# ---------------------------------------------------------------------------

BLOCK_START_RE = re.compile(r"^\[evidence-gate\]\s*$")
CHANGED_RE = re.compile(r"^Changed:\s*(없음|`[^`]+`(?:,\s*`[^`]+`)*)\s*$")
SCALE_RE = re.compile(r"^Scale:\s*(LIGHT|FULL)\s*—\s*(.+)$")
COVERAGE_RE = re.compile(r"^Coverage:\s*(.+)$")
CLAIM_RE = re.compile(
    r"^-\s*(C\d+)\s+(VERIFIED|INSPECTED|UNVERIFIED|FAILED)"
    r"(?:\s+—\s+(E\d+(?:,\s*E\d+)*))?\s*\((.*)\)\s*$"
)
EV_CMD_RE = re.compile(
    r"^-\s*(E\d+)\s*(\(reused\))?\s*`(.+?)`\s*"
    r"\((?:cwd:\s*`([^`]+)`,\s*)?exit\s+(\d+)\)\s*—\s*\"(.*)\"\s*$"
)
EV_READ_RE = re.compile(
    r"^-\s*(E\d+)\s*(\(reused\))?\s*Read\s+`([^`]+)`\s*—\s*\"(.*)\"\s*$"
)
EMPTY_SECTION_RE = re.compile(
    r"^(Claims|Evidence|Unverified/failed):\s*없음\s*$", re.IGNORECASE
)
SECTION_HEADERS = {
    "claims:": "claims",
    "evidence:": "evidence",
    "unverified/failed:": "unverified",
}


def normalize_ws(s: Optional[str]) -> str:
    return " ".join((s or "").split())


# ---------------------------------------------------------------------------
# Transcript parsing primitives
# ---------------------------------------------------------------------------


def read_transcript_lines(path: str) -> list:
    """Read + JSON-parse each line. Malformed lines become None so line
    indices stay aligned with the original file (used as the ordering
    proxy for freshness comparisons). Fail-open on any I/O error or an
    oversized file.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size > MAX_TRANSCRIPT_BYTES:
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except OSError:
        return []
    parsed = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            parsed.append(None)
            continue
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            parsed.append(None)
            continue
        parsed.append(obj if isinstance(obj, dict) else None)
    return parsed


def _get_content(obj: dict) -> Any:
    message = obj.get("message")
    if isinstance(message, dict) and "content" in message:
        return message.get("content")
    return obj.get("content")


def is_assistant_line(obj: dict) -> bool:
    if obj.get("type") in ("assistant", "ai"):
        return True
    message = obj.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def is_user_line(obj: dict) -> bool:
    if obj.get("type") == "user":
        return True
    message = obj.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def _is_tool_result_only_content(content: Any) -> bool:
    if not isinstance(content, list) or not content:
        return False
    saw = False
    for item in content:
        if not isinstance(item, dict):
            return False
        if item.get("type") == "tool_result":
            saw = True
            continue
        return False
    return saw


def is_real_user_message(obj: dict) -> bool:
    """Turn-boundary predicate (Appendix A): a user-role line whose
    content is NOT purely tool_result blocks. A plain string is always
    real; a list is real unless every block in it is a tool_result.
    """
    if not is_user_line(obj):
        return False
    content = _get_content(obj)
    if isinstance(content, str):
        return True
    if isinstance(content, list) and content:
        return not _is_tool_result_only_content(content)
    return False


def line_has_tool_result(obj: dict) -> bool:
    content = _get_content(obj)
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


def _extract_block_text(content: Any) -> str:
    """Text of a single block's `content` (tool_result) or a message's
    `content` list (assistant text blocks). Handles both the string
    and list-of-blocks shapes seen in real transcripts (str ~68%,
    list-of-{text,image,tool_reference} blocks ~32% empirically).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
        return "".join(parts)
    return ""


def find_turn_boundary_idx(parsed_lines: list) -> int:
    """Index of the last real user message. -1 if none found (defensive
    fallback: treat the whole transcript as "this turn").
    """
    boundary = -1
    for idx, obj in enumerate(parsed_lines):
        if not isinstance(obj, dict):
            continue
        if is_real_user_message(obj):
            boundary = idx
    return boundary


def extract_final_assistant_text(parsed_lines: list, turn_boundary_idx: int) -> str:
    """Concatenate text blocks of the assistant's final reply: scan
    backward from EOF, stop at the most recent tool_result (everything
    after that tool_result is the model's final, un-interrupted answer)
    or at the turn boundary, whichever comes first.
    """
    line_texts = []
    for idx in range(len(parsed_lines) - 1, turn_boundary_idx, -1):
        obj = parsed_lines[idx]
        if not isinstance(obj, dict):
            continue
        if line_has_tool_result(obj):
            break
        if is_assistant_line(obj):
            text = _extract_block_text(_get_content(obj))
            if text:
                line_texts.append(text)
    line_texts.reverse()
    return "".join(line_texts)


def extract_ledger_block_lines(final_text: str) -> Optional[list]:
    """Lines from the LAST `[evidence-gate]` marker to the end of the
    final assistant text, or None if no marker line exists.
    """
    lines = final_text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if BLOCK_START_RE.match(ln):
            start = i
    if start is None:
        return None
    return lines[start:]


# ---------------------------------------------------------------------------
# Tool event collection (whole session — R2 "reused" evidence can point
# at an earlier turn, so freshness/provenance matching cannot be scoped
# to the current turn alone).
# ---------------------------------------------------------------------------


@dataclass
class ToolEvent:
    line_idx: int
    tool_use_id: str
    name: str
    input: Any
    result_text: str = ""
    result_line_idx: int = -1
    is_error: Optional[bool] = None
    has_result: bool = False


def collect_tool_events(parsed_lines: list) -> list:
    events: list = []
    by_id: dict = {}
    for idx, obj in enumerate(parsed_lines):
        if not isinstance(obj, dict):
            continue
        if is_assistant_line(obj):
            content = _get_content(obj)
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    tid = block.get("id")
                    if not isinstance(name, str) or not isinstance(tid, str):
                        continue
                    ev = ToolEvent(line_idx=idx, tool_use_id=tid, name=name, input=block.get("input"))
                    events.append(ev)
                    by_id[tid] = ev
        content = _get_content(obj)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tid = block.get("tool_use_id")
                if not isinstance(tid, str):
                    continue
                ev = by_id.get(tid)
                if ev is None:
                    continue
                text = _extract_block_text(block.get("content"))
                tur = obj.get("toolUseResult")
                if isinstance(tur, dict):
                    for key in ("stdout", "stderr"):
                        v = tur.get(key)
                        if isinstance(v, str) and v:
                            text = (text + "\n" + v) if text else v
                ev.result_text = text
                ev.result_line_idx = idx
                ev.has_result = True
                is_err = block.get("is_error")
                ev.is_error = is_err if isinstance(is_err, bool) else None
    return events


def build_mutation_last_idx_by_path(tool_events: list) -> dict:
    """Last (highest line index) mutation per path, Edit/Write/NotebookEdit
    only. Bash write-heuristic hits are not path-addressable and are used
    only for R1's turn-level existence check, not this freshness map.
    """
    result: dict = {}
    for ev in tool_events:
        if ev.name not in MUTATION_TOOLS or not isinstance(ev.input, dict):
            continue
        path = ev.input.get("file_path")
        if not isinstance(path, str) or not path:
            path = ev.input.get("notebook_path")  # defensive: NotebookEdit key name unconfirmed empirically
        if not isinstance(path, str) or not path:
            continue
        path = path.strip()
        if ev.line_idx > result.get(path, -1):
            result[path] = ev.line_idx
    return result


def turn_has_mutation(tool_events: list, turn_boundary_idx: int, config: dict) -> bool:
    write_hints = _compile_patterns(BASH_WRITE_HINTS + config.get("extra_write_hints", []))
    for ev in tool_events:
        if ev.line_idx <= turn_boundary_idx:
            continue
        if ev.name in MUTATION_TOOLS and isinstance(ev.input, dict):
            fp = ev.input.get("file_path")
            nb = ev.input.get("notebook_path")
            if (isinstance(fp, str) and fp) or (isinstance(nb, str) and nb):
                return True
        elif ev.name == "Bash" and isinstance(ev.input, dict):
            cmd = ev.input.get("command")
            if isinstance(cmd, str) and any(p.search(cmd) for p in write_hints):
                return True
    return False


# ---------------------------------------------------------------------------
# Ledger parsing (Section 5 / Appendix A)
# ---------------------------------------------------------------------------


def parse_ledger(block_lines: list) -> dict:
    """block_lines[0] is the `[evidence-gate]` marker line itself.

    Lenient by design: lines that don't match a known pattern are kept
    in parse_notes but never treated as a violation. Section 2 (비목표)
    explicitly rules out format perfectionism — only R1-R6 (existence /
    timing / provenance) are enforced.
    """
    ledger: dict = {
        "changed_paths": None,
        "scale": None,
        "coverage_raw": None,
        "claims": [],
        "evidence": {},
        "unverified_raw": [],
        "parse_notes": [],
    }
    section = None
    for raw_line in block_lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            continue

        if EMPTY_SECTION_RE.match(stripped):
            continue

        header = SECTION_HEADERS.get(stripped.lower())
        if header:
            section = header
            continue

        m = CHANGED_RE.match(stripped)
        if m:
            raw = m.group(1)
            ledger["changed_paths"] = [] if raw == "없음" else re.findall(r"`([^`]+)`", raw)
            continue

        m = SCALE_RE.match(stripped)
        if m:
            ledger["scale"] = (m.group(1), m.group(2))
            continue

        m = COVERAGE_RE.match(stripped)
        if m:
            ledger["coverage_raw"] = m.group(1)
            continue

        if section == "claims":
            m = CLAIM_RE.match(stripped)
            if m:
                cid, status, ev_refs, reason = m.groups()
                evidence_ids = [e.strip() for e in ev_refs.split(",")] if ev_refs else []
                ledger["claims"].append(
                    {"id": cid, "status": status, "evidence_ids": evidence_ids, "reason": reason, "raw": stripped}
                )
                continue

        if section == "evidence":
            m = EV_CMD_RE.match(stripped)
            if m:
                eid, reused, command, cwd, exit_code, quote = m.groups()
                ledger["evidence"][eid] = {
                    "id": eid, "kind": "cmd", "reused": bool(reused),
                    "command": command, "cwd": cwd, "exit": exit_code, "quote": quote, "raw": stripped,
                }
                continue
            m = EV_READ_RE.match(stripped)
            if m:
                eid, reused, path, quote = m.groups()
                ledger["evidence"][eid] = {
                    "id": eid, "kind": "read", "reused": bool(reused),
                    "path": path, "quote": quote, "raw": stripped,
                }
                continue

        if section == "unverified":
            ledger["unverified_raw"].append(stripped)
            continue

        ledger["parse_notes"].append(stripped)

    return ledger


# ---------------------------------------------------------------------------
# R2 / R3 / R5 matching
# ---------------------------------------------------------------------------


@dataclass
class MatchCandidate:
    event: ToolEvent
    is_loose: bool
    is_delegated: bool


def is_delegated_bash(cmd: str, config: dict) -> bool:
    patterns = _compile_patterns(DELEGATION_BASH + config.get("extra_delegation_bash", []))
    return any(p.search(cmd) for p in patterns)


def is_delegated_source(ev: ToolEvent, config: dict) -> bool:
    if ev.name in DELEGATION_TOOLS:
        return True
    if ev.name.startswith(DELEGATION_MCP_PREFIXES):
        return True
    if ev.name == "Bash" and isinstance(ev.input, dict):
        cmd = ev.input.get("command")
        if isinstance(cmd, str) and is_delegated_bash(cmd, config):
            return True
    return False


def extract_command_text(name: str, tool_input: Any) -> Optional[str]:
    """Best-effort "what did this tool_use actually do" string, used to
    match against a ledger's cited command. Bash uses its literal
    command. Delegation tools (Agent/Task/Workflow, mcp__codex__*,
    mcp__gemini__*) have no natural "command" field, but a model could
    still dress up a delegated call as `- E1 `<description>` (exit 0)
    — "..."` to smuggle a worker's report in as VERIFIED evidence; this
    is exactly what R5 exists to catch, so those tools' description/
    prompt fields are made matchable too (otherwise R5's first clause —
    "matched tool_result is a delegation tool's result" — would be
    unreachable, since nothing would ever match those tool_use blocks).
    """
    if not isinstance(tool_input, dict):
        return None
    if name == "Bash":
        c = tool_input.get("command")
        return c if isinstance(c, str) and c else None
    if name in DELEGATION_TOOLS:
        for key in ("description", "prompt"):
            v = tool_input.get(key)
            if isinstance(v, str) and v:
                return v
        return None
    if name.startswith(DELEGATION_MCP_PREFIXES):
        v = tool_input.get("prompt")
        return v if isinstance(v, str) and v else None
    return None


def find_command_matches(cited: str, tool_events: list, config: dict) -> list:
    """R2 matching for EV_CMD evidence: normalize + exact match first,
    fall back to substring ("loose") containment either direction.
    Exact-match candidates are returned before loose ones.
    """
    cited_norm = normalize_ws(cited)
    exact, loose = [], []
    for ev in tool_events:
        if not ev.has_result:
            continue
        text = extract_command_text(ev.name, ev.input)
        if text is None:
            continue
        text_norm = normalize_ws(text)
        if not text_norm:
            continue
        delegated = is_delegated_source(ev, config)
        if text_norm == cited_norm:
            exact.append(MatchCandidate(ev, False, delegated))
        elif cited_norm and (cited_norm in text_norm or text_norm in cited_norm):
            loose.append(MatchCandidate(ev, True, delegated))
    return exact + loose


def find_read_matches(cited_path: str, tool_events: list, config: dict) -> list:
    """R2 matching for EV_READ evidence (Read tool only)."""
    cited_norm = normalize_ws(cited_path)
    exact, loose = [], []
    for ev in tool_events:
        if ev.name != "Read" or not ev.has_result or not isinstance(ev.input, dict):
            continue
        path = ev.input.get("file_path")
        if not isinstance(path, str) or not path:
            continue
        path_norm = normalize_ws(path)
        if path_norm == cited_norm:
            exact.append(MatchCandidate(ev, False, False))
        elif cited_norm and (cited_norm in path_norm or path_norm in cited_norm):
            loose.append(MatchCandidate(ev, True, False))
    return exact + loose


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    rule: str
    claim: Optional[str]
    detail: str
    blocking: bool = True
    kind: str = "violation"  # "violation" | "note" (notes are logged, never block)


def check_claim_evidence(
    cid: str, status: str, ev: dict, tool_events: list, changed_required_idx: int, config: dict
) -> list:
    findings: list = []
    eid = ev["id"]

    if ev["kind"] == "cmd":
        candidates = find_command_matches(ev["command"], tool_events, config)
    else:
        candidates = find_read_matches(ev["path"], tool_events, config)

    if not candidates:
        findings.append(Finding(
            "R2", cid,
            f"{eid} 실행 근거 없음 — 세션 기록에 일치하는 완료된 실행/Read가 없다. "
            f"실제로 실행한 뒤 그 결과를 인용하거나 {cid}을 UNVERIFIED로 정정하라.",
        ))
        return findings

    non_delegated = [c for c in candidates if not c.is_delegated]
    if not non_delegated:
        findings.append(Finding(
            "R5", cid,
            f"{eid}과 일치하는 실행이 전부 위임 도구(Agent/Task/Workflow, mcp__codex__*, "
            f"mcp__gemini__*) 또는 위임 CLI(grok/codex/gemini/claude -p/orca orchestration) 결과다 — "
            f"위임 결과는 {status} 증거로 인정되지 않는다. 직접 실행해 확인하거나 {cid}을 낮춰라.",
        ))
        return findings

    quote_norm = normalize_ws(ev["quote"])
    exact_pool = [c for c in non_delegated if not c.is_loose]
    loose_pool = [c for c in non_delegated if c.is_loose]

    def satisfies(c: MatchCandidate) -> bool:
        return bool(quote_norm) and quote_norm in normalize_ws(c.event.result_text)

    exact_hits = [c for c in exact_pool if satisfies(c)]
    loose_hits = [c for c in loose_pool if satisfies(c)]
    chosen_pool = exact_hits or loose_hits

    if not chosen_pool:
        findings.append(Finding(
            "R3", cid,
            f"{eid} 인용 줄이 실제 tool 결과 어디에도 없음(위조 의심) — 인용을 실제 출력과 "
            f"일치시키거나 {cid}을 UNVERIFIED로 정정하라.",
        ))
        return findings

    if loose_hits and not exact_hits:
        findings.append(Finding(
            "R2_LOOSE_MATCH", cid,
            f"{eid}의 command/path가 세션 기록과 정확히 일치하지 않고 포함 관계로만 확인됨 "
            f"(참고용 기록, 위반 아님).",
            blocking=False, kind="note",
        ))

    chosen = max(chosen_pool, key=lambda c: c.event.line_idx)

    if status == "VERIFIED":
        if ev["reused"]:
            findings.append(Finding(
                "R4", cid,
                f"{eid}가 (reused)로 표시됨 — 재사용된 관찰은 VERIFIED를 뒷받침할 수 없다"
                f"(INSPECTED까지만 가능). status를 INSPECTED로 낮추거나 다시 실행해 새 근거로 교체하라.",
            ))
        elif chosen.event.line_idx < changed_required_idx:
            findings.append(Finding(
                "R4", cid,
                f"{eid}의 실행이 Changed: 경로의 마지막 수정보다 앞선다(재탕 의심) — "
                f"수정 이후 다시 실행하고 새 근거로 {cid}을 갱신하라.",
            ))
        # INSPECTED freshness is explicitly out of scope (§7.5).

    return findings


def check_claims(ledger: dict, tool_events: list, mutation_last_idx_by_path: dict, config: dict) -> list:
    findings: list = []
    changed_paths = ledger.get("changed_paths") or []
    changed_required_idx = -1
    for p in changed_paths:
        changed_required_idx = max(changed_required_idx, mutation_last_idx_by_path.get(p.strip(), -1))

    for claim in ledger["claims"]:
        cid = claim["id"]
        status = claim["status"]
        if status not in ("VERIFIED", "INSPECTED"):
            continue  # UNVERIFIED/FAILED carry no verification burden
        if not claim["evidence_ids"]:
            findings.append(Finding(
                "R2", cid,
                f"{cid} {status}인데 증거(E#) 인용이 없다 — 실제로 확인했다면 Evidence에 E#을 "
                f"추가해 인용하거나, 아니라면 {cid}을 UNVERIFIED로 정정하라.",
            ))
            continue
        for eid in claim["evidence_ids"]:
            ev = ledger["evidence"].get(eid)
            if ev is None:
                findings.append(Finding(
                    "R2", cid,
                    f"{cid}이 인용한 {eid}가 Evidence 섹션에 없다 — {eid}를 Evidence에 추가하거나 "
                    f"인용을 제거하라.",
                ))
                continue
            findings.extend(check_claim_evidence(cid, status, ev, tool_events, changed_required_idx, config))

    return findings


def check_r1(ledger_found: bool, any_mutation_in_turn: bool) -> list:
    """R1 is capped at warn severity per the design doc's own table
    (labelled "warn급", distinct from R2-R5's plain "violation") — its
    stated purpose is closing the "just omit the ledger" escape hatch,
    not hard-blocking every trivial turn that forgets the block.
    """
    if any_mutation_in_turn and not ledger_found:
        return [Finding(
            "R1", None,
            "이번 턴에 파일을 수정했지만 최종 메시지에 [evidence-gate] ledger 블록이 없다 — "
            "최종 메시지 끝에 ledger 블록을 추가하라.",
            blocking=False,
        )]
    return []


# ---------------------------------------------------------------------------
# Top-level audit
# ---------------------------------------------------------------------------


def audit_turn(transcript_path: str, config: dict) -> list:
    parsed_lines = read_transcript_lines(transcript_path)
    if not parsed_lines:
        return []

    turn_boundary_idx = find_turn_boundary_idx(parsed_lines)
    tool_events = collect_tool_events(parsed_lines)
    mutation_last_idx_by_path = build_mutation_last_idx_by_path(tool_events)
    any_mutation = turn_has_mutation(tool_events, turn_boundary_idx, config)

    final_text = extract_final_assistant_text(parsed_lines, turn_boundary_idx)
    block_lines = extract_ledger_block_lines(final_text)

    if block_lines is None:
        return check_r1(False, any_mutation)

    ledger = parse_ledger(block_lines)
    return check_claims(ledger, tool_events, mutation_last_idx_by_path, config)


def format_block_reason(findings: list) -> str:
    lines = []
    for f in findings:
        claim_part = f"{f.claim} " if f.claim else ""
        lines.append(f"{f.rule} 위반: {claim_part}{f.detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def process_stop_payload(payload: dict) -> Optional[str]:
    """Returns the stdout string to emit (block decision JSON), or None
    for silent success. Never raises — callers still wrap this, but the
    logic itself is defensive at every field access.
    """
    config_dir = get_config_dir()

    session_id = payload.get("session_id")
    session_id = session_id if isinstance(session_id, str) else ""
    transcript_path = payload.get("transcript_path")
    transcript_path = transcript_path if isinstance(transcript_path, str) else ""
    stop_hook_active = bool(payload.get("stop_hook_active"))

    config = load_config(config_dir)

    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    try:
        findings = audit_turn(transcript_path, config)
    except Exception as exc:  # fail-open: parsing bugs must not crash the hook
        append_audit_log(config_dir, {
            "ts": time.time(), "session_id": session_id, "rule": "INTERNAL_ERROR",
            "claim": None, "detail": f"audit_turn raised {type(exc).__name__}: {exc}",
        })
        return None

    ts = time.time()
    for f in findings:
        append_audit_log(config_dir, {
            "ts": ts, "session_id": session_id, "rule": f.rule,
            "claim": f.claim, "detail": f.detail, "kind": f.kind,
        })

    blocking = [f for f in findings if f.kind == "violation" and f.blocking]
    if config["mode"] == "block" and blocking and not stop_hook_active:
        return json.dumps({"decision": "block", "reason": format_block_reason(blocking)}, ensure_ascii=False)
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
    except BaseException:
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        out = process_stop_payload(payload)
    except Exception:
        try:
            append_audit_log(get_config_dir(), {
                "ts": time.time(), "session_id": "", "rule": "INTERNAL_ERROR",
                "claim": None, "detail": "unexpected exception in process_stop_payload",
            })
        except Exception:
            pass
        return 0
    if out:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        raise SystemExit(0)
