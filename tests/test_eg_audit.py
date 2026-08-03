#!/usr/bin/env python3
"""Tests for hooks/eg_audit.py (evidence-gate v2 auditor).

Two layers, per the task brief:
    - subprocess/integration tests (primary): spawn eg_audit.py exactly
      like Claude Code's Stop hook would, feeding it a JSON payload on
      stdin and a fixture transcript, and inspect stdout + audit.log.
    - internal function unit tests (supporting): import the module
      directly and exercise the regex/matching helpers in isolation.

Every test isolates EG_CONFIG_DIR to a tempdir so nothing here ever
touches the real ~/.claude/evidence-gate.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "eg_audit.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_module():
    spec = importlib.util.spec_from_file_location("eg_audit", str(HOOK_PATH))
    module = importlib.util.module_from_spec(spec)
    # Must register in sys.modules before exec: eg_audit.py's dataclasses
    # (with `from __future__ import annotations`) resolve cls.__module__
    # via sys.modules during class creation on 3.14+.
    sys.modules["eg_audit"] = module
    spec.loader.exec_module(module)
    return module


eg_audit = _load_module()


def write_config(config_dir, mode="warn", extra_delegation_bash=None, extra_write_hints=None):
    os.makedirs(config_dir, exist_ok=True)
    cfg = {"mode": mode}
    if extra_delegation_bash is not None:
        cfg["extra_delegation_bash"] = extra_delegation_bash
    if extra_write_hints is not None:
        cfg["extra_write_hints"] = extra_write_hints
    with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def read_audit_log(config_dir):
    path = os.path.join(config_dir, "audit.log")
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def run_hook_raw(stdin_text, config_dir, timeout=20):
    env = dict(os.environ)
    env["EG_CONFIG_DIR"] = str(config_dir)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def run_hook(transcript_path, config_dir, session_id="test-session", stop_hook_active=False, extra_payload=None):
    payload = {
        "session_id": session_id,
        "transcript_path": str(transcript_path),
        "stop_hook_active": stop_hook_active,
    }
    if extra_payload:
        payload.update(extra_payload)
    return run_hook_raw(json.dumps(payload), config_dir)


# ---------------------------------------------------------------------------
# (a)-(h): required fixture-driven cases
# ---------------------------------------------------------------------------


class TestEgAuditFixtures(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_a_normal_verified_no_violations(self):
        write_config(self.config_dir, mode="warn")
        proc = run_hook(FIXTURES_DIR / "normal_verified.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")
        log = read_audit_log(self.config_dir)
        violations = [e for e in log if e.get("kind") != "note"]
        self.assertEqual(violations, [], f"expected zero violations, got: {log}")

    def test_b_forged_citation_triggers_r3(self):
        write_config(self.config_dir, mode="warn")
        proc = run_hook(FIXTURES_DIR / "forged_citation.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "", "warn mode must never write to stdout")
        log = read_audit_log(self.config_dir)
        rules = [e["rule"] for e in log]
        self.assertIn("R3", rules, f"expected R3 in log, got: {log}")
        r3 = next(e for e in log if e["rule"] == "R3")
        self.assertEqual(r3["claim"], "C1")

    def test_c_stale_evidence_triggers_r4(self):
        write_config(self.config_dir, mode="warn")
        proc = run_hook(FIXTURES_DIR / "stale_evidence.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        log = read_audit_log(self.config_dir)
        rules = [e["rule"] for e in log]
        self.assertIn("R4", rules, f"expected R4 (stale) in log, got: {log}")

    def test_d_worker_agent_citation_triggers_r5(self):
        write_config(self.config_dir, mode="warn")
        proc = run_hook(FIXTURES_DIR / "worker_citation.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        log = read_audit_log(self.config_dir)
        rules = [e["rule"] for e in log]
        self.assertIn("R5", rules, f"expected R5 (delegated source) in log, got: {log}")

    def test_e_mutation_without_ledger_triggers_r1_and_never_blocks(self):
        # R1 is capped at warn severity in the design doc's own table
        # ("warn급", distinct from R2-R5's plain "violation") — verify
        # this holds even when mode=block.
        write_config(self.config_dir, mode="block")
        proc = run_hook(FIXTURES_DIR / "mutation_no_ledger.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "", "R1 must never produce a block decision")
        log = read_audit_log(self.config_dir)
        rules = [e["rule"] for e in log]
        self.assertIn("R1", rules, f"expected R1 in log, got: {log}")

    def test_f_broken_jsonl_fails_open(self):
        write_config(self.config_dir, mode="block")
        proc = run_hook(FIXTURES_DIR / "broken.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "", f"must not print to stderr, got: {proc.stderr!r}")

    def test_g_reused_evidence_backing_verified_triggers_r4(self):
        write_config(self.config_dir, mode="warn")
        proc = run_hook(FIXTURES_DIR / "reused_verified.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        log = read_audit_log(self.config_dir)
        rules = [e["rule"] for e in log]
        self.assertIn("R4", rules, f"expected R4 ((reused) can't back VERIFIED) in log, got: {log}")

    def test_h_block_mode_emits_decision_block(self):
        write_config(self.config_dir, mode="block")
        proc = run_hook(FIXTURES_DIR / "forged_citation.jsonl", self.config_dir, stop_hook_active=False)
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("R3", out["reason"])

    def test_h_stop_hook_active_downgrades_block_to_warn(self):
        write_config(self.config_dir, mode="block")
        proc = run_hook(FIXTURES_DIR / "forged_citation.jsonl", self.config_dir, stop_hook_active=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "", "stop_hook_active=true must downgrade block to warn (R6)")
        log = read_audit_log(self.config_dir)
        rules = [e["rule"] for e in log]
        self.assertIn("R3", rules, "violation must still be logged even when downgraded")


# ---------------------------------------------------------------------------
# Defensive / fail-open edge cases beyond the fixture set
# ---------------------------------------------------------------------------


class TestEgAuditEdgeCases(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_missing_transcript_file_fails_open(self):
        write_config(self.config_dir, mode="block")
        payload = {"session_id": "s", "transcript_path": "/nonexistent/does/not/exist.jsonl", "stop_hook_active": False}
        proc = run_hook_raw(json.dumps(payload), self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_malformed_stdin_json_fails_open(self):
        proc = run_hook_raw("not json at all {{{", self.config_dir)
        self.assertEqual(proc.returncode, 0)

    def test_empty_stdin_fails_open(self):
        proc = run_hook_raw("", self.config_dir)
        self.assertEqual(proc.returncode, 0)

    def test_stdin_not_a_json_object_fails_open(self):
        proc = run_hook_raw(json.dumps([1, 2, 3]), self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_missing_config_json_defaults_to_warn(self):
        # No config.json written at all in this tempdir.
        proc = run_hook(FIXTURES_DIR / "forged_citation.jsonl", self.config_dir)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "", "default mode must be warn (no stdout output)")

    def test_malformed_config_json_fails_open_to_warn(self):
        os.makedirs(self.config_dir, exist_ok=True)
        with open(os.path.join(self.config_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{not valid json")
        proc = run_hook(FIXTURES_DIR / "forged_citation.jsonl", self.config_dir, extra_payload={})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "", "malformed config must fail open to warn, not crash/block")

    def test_no_mutation_no_ledger_no_violation(self):
        # Pure Q&A turn fixture built inline: a real user message and a
        # plain assistant text reply, no tool calls at all. R1 must not
        # fire when nothing was mutated.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "qa_only.jsonl")
            lines = [
                {"type": "user", "message": {"role": "user", "content": "안녕"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "안녕하세요"}]}},
            ]
            with open(path, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            write_config(self.config_dir, mode="block")
            proc = run_hook(path, self.config_dir)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout.strip(), "")
            log = read_audit_log(self.config_dir)
            self.assertEqual(log, [])

    def test_verified_claim_with_no_evidence_ref_is_a_violation(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "no_ref.jsonl")
            ledger = "\n".join([
                "완료.",
                "",
                "[evidence-gate]",
                "Changed: 없음",
                "Claims:",
                "- C1 VERIFIED (증거 인용 없이 확신)",
                "Evidence: 없음",
                "Unverified/failed: 없음",
            ])
            lines = [
                {"type": "user", "message": {"role": "user", "content": "확인해줘"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": ledger}]}},
            ]
            with open(path, "w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            write_config(self.config_dir, mode="warn")
            proc = run_hook(path, self.config_dir)
            self.assertEqual(proc.returncode, 0)
            log = read_audit_log(self.config_dir)
            rules = [e["rule"] for e in log]
            self.assertIn("R2", rules)


# ---------------------------------------------------------------------------
# Internal function unit tests
# ---------------------------------------------------------------------------


class TestInternalFunctions(unittest.TestCase):
    def test_normalize_ws_collapses_whitespace(self):
        self.assertEqual(eg_audit.normalize_ws("  a   b\tc\n"), "a b c")
        self.assertEqual(eg_audit.normalize_ws(None), "")

    def test_claim_re_matches_verified_with_evidence(self):
        m = eg_audit.CLAIM_RE.match("- C1 VERIFIED — E1 (some claim)")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "C1")
        self.assertEqual(m.group(2), "VERIFIED")
        self.assertEqual(m.group(3), "E1")
        self.assertEqual(m.group(4), "some claim")

    def test_claim_re_matches_multi_evidence_refs(self):
        m = eg_audit.CLAIM_RE.match("- C2 INSPECTED — E1, E2 (checked two things)")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3), "E1, E2")

    def test_claim_re_matches_unverified_without_evidence(self):
        m = eg_audit.CLAIM_RE.match("- C3 UNVERIFIED (haven't checked yet)")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(3))

    def test_ev_cmd_re_matches_with_cwd_and_reused(self):
        m = eg_audit.EV_CMD_RE.match('- E3 (reused) `ls -la` (cwd: `/tmp`, exit 0) — "total 0"')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "E3")
        self.assertEqual(m.group(2), "(reused)")
        self.assertEqual(m.group(3), "ls -la")
        self.assertEqual(m.group(4), "/tmp")
        self.assertEqual(m.group(5), "0")
        self.assertEqual(m.group(6), "total 0")

    def test_ev_cmd_re_matches_without_cwd_or_reused(self):
        m = eg_audit.EV_CMD_RE.match('- E1 `python3 -m pytest -q` (exit 0) — "1 passed"')
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(2))
        self.assertIsNone(m.group(4))

    def test_ev_read_re_matches(self):
        m = eg_audit.EV_READ_RE.match('- E2 Read `/tmp/foo.py` — "def foo(): pass"')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3), "/tmp/foo.py")
        self.assertEqual(m.group(4), "def foo(): pass")

    def test_changed_re_none(self):
        m = eg_audit.CHANGED_RE.match("Changed: 없음")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "없음")

    def test_changed_re_multiple_paths(self):
        m = eg_audit.CHANGED_RE.match("Changed: `/a.py`, `/b.py`")
        self.assertIsNotNone(m)
        paths = __import__("re").findall(r"`([^`]+)`", m.group(1))
        self.assertEqual(paths, ["/a.py", "/b.py"])

    def test_is_delegated_bash_builtin_patterns(self):
        config = {"extra_delegation_bash": []}
        self.assertTrue(eg_audit.is_delegated_bash("grok -p 'do something'", config))
        self.assertTrue(eg_audit.is_delegated_bash("codex exec 'task'", config))
        self.assertTrue(eg_audit.is_delegated_bash("claude -p 'hello'", config))
        self.assertTrue(eg_audit.is_delegated_bash("orca orchestration task-create", config))
        self.assertFalse(eg_audit.is_delegated_bash("python3 -m pytest", config))

    def test_is_delegated_bash_extra_config_pattern(self):
        config = {"extra_delegation_bash": [r"^\s*mycustomcli\b"]}
        self.assertTrue(eg_audit.is_delegated_bash("mycustomcli run", config))

    def test_is_delegated_bash_invalid_extra_pattern_does_not_crash(self):
        config = {"extra_delegation_bash": ["("]}  # invalid regex
        # must not raise
        self.assertFalse(eg_audit.is_delegated_bash("python3 -m pytest", config))

    def test_find_command_matches_exact(self):
        ev = eg_audit.ToolEvent(line_idx=0, tool_use_id="t1", name="Bash",
                                 input={"command": "python3 -m pytest -q"},
                                 result_text="1 passed", has_result=True)
        config = {"extra_delegation_bash": []}
        candidates = eg_audit.find_command_matches("python3 -m pytest -q", [ev], config)
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0].is_loose)
        self.assertFalse(candidates[0].is_delegated)

    def test_find_command_matches_loose_containment(self):
        ev = eg_audit.ToolEvent(line_idx=0, tool_use_id="t1", name="Bash",
                                 input={"command": "python3 -m pytest tests/ -q -k test_add"},
                                 result_text="1 passed", has_result=True)
        config = {"extra_delegation_bash": []}
        candidates = eg_audit.find_command_matches("python3 -m pytest tests/ -q", [ev], config)
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].is_loose)

    def test_find_command_matches_no_result_yet_excluded(self):
        ev = eg_audit.ToolEvent(line_idx=0, tool_use_id="t1", name="Bash",
                                 input={"command": "python3 -m pytest -q"},
                                 has_result=False)
        config = {"extra_delegation_bash": []}
        candidates = eg_audit.find_command_matches("python3 -m pytest -q", [ev], config)
        self.assertEqual(candidates, [])

    def test_extract_command_text_agent_uses_description(self):
        text = eg_audit.extract_command_text("Agent", {"description": "do the thing", "prompt": "long prompt"})
        self.assertEqual(text, "do the thing")

    def test_extract_command_text_bash_uses_command(self):
        text = eg_audit.extract_command_text("Bash", {"command": "ls"})
        self.assertEqual(text, "ls")

    def test_extract_command_text_unrelated_tool_returns_none(self):
        text = eg_audit.extract_command_text("Read", {"file_path": "/a.py"})
        self.assertIsNone(text)

    def test_is_real_user_message_excludes_tool_result_only(self):
        obj = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "y"}
        ]}}
        self.assertFalse(eg_audit.is_real_user_message(obj))

    def test_is_real_user_message_includes_plain_string(self):
        obj = {"type": "user", "message": {"role": "user", "content": "hello"}}
        self.assertTrue(eg_audit.is_real_user_message(obj))

    def test_is_real_user_message_false_for_assistant(self):
        obj = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}}
        self.assertFalse(eg_audit.is_real_user_message(obj))

    def test_extract_ledger_block_lines_none_when_absent(self):
        self.assertIsNone(eg_audit.extract_ledger_block_lines("just prose, no marker"))

    def test_extract_ledger_block_lines_takes_last_marker(self):
        text = "[evidence-gate]\nold block\n\nmore prose\n\n[evidence-gate]\nChanged: 없음"
        lines = eg_audit.extract_ledger_block_lines(text)
        self.assertIsNotNone(lines)
        self.assertEqual(lines[0], "[evidence-gate]")
        self.assertEqual(lines[1], "Changed: 없음")

    def test_parse_ledger_empty_section_shorthand(self):
        block_lines = ["[evidence-gate]", "Changed: 없음", "Claims: 없음", "Evidence: 없음", "Unverified/failed: 없음"]
        ledger = eg_audit.parse_ledger(block_lines)
        self.assertEqual(ledger["changed_paths"], [])
        self.assertEqual(ledger["claims"], [])
        self.assertEqual(ledger["evidence"], {})


if __name__ == "__main__":
    unittest.main()
