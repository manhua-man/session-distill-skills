"""Executable contracts for the repository's platform adapters.

The contracts intentionally describe repository-local evidence.  They do not
claim that an arbitrary host has any platform installed.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EXPECTED_PLATFORMS = {
    "cursor",
    "codex",
    "grok",
    "claude",
    "hermes",
    "antigravity",
    "opencode",
}
REQUIRED_FIELDS = {
    "platform_id",
    "transcript_support",
    "hook_support",
    "hook_paths",
    "source_roots",
    "adapter_script",
    "required_commands",
    "project_match_rules",
    "sample_fixture",
    "growth_test",
    "lossless_rebuild_test",
}
TEST_REFERENCE_FIELDS = ("sample_fixture", "growth_test", "lossless_rebuild_test")
PROJECT_MATCH_MODES = {"all_sessions", "list_only", "normalized_project_alias", "path_contains"}


def _scalar(value: str) -> str | bool | list[str]:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "[]":
        return []
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_contract(path: Path) -> dict[str, Any]:
    """Parse the deliberately small YAML subset used by adapter contracts.

    Keeping this parser local avoids adding PyYAML solely for a portable test
    suite.  Do not add YAML constructs without extending this parser and its
    coverage first.
    """

    contract: dict[str, Any] = {}
    section = ""
    current_item: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"invalid contract line in {path}: {raw_line}")
            section = key
            current_item = None
            contract[key] = _scalar(value) if value.strip() else None
            continue
        if indent == 2 and line.startswith("- "):
            if section not in {"source_roots", "required_commands"}:
                raise ValueError(f"unexpected list in {section}: {raw_line}")
            if contract.get(section) is None:
                contract[section] = []
            item = line[2:]
            if ":" not in item:
                contract[section].append(_scalar(item))
                current_item = None
                continue
            key, _, value = item.partition(":")
            current_item = {key: _scalar(value)}
            contract[section].append(current_item)
            continue
        if indent == 2:
            if section not in {"project_match_rules", *TEST_REFERENCE_FIELDS}:
                raise ValueError(f"unexpected mapping in {section}: {raw_line}")
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"invalid contract line in {path}: {raw_line}")
            if contract.get(section) is None:
                contract[section] = {}
            contract[section][key] = _scalar(value)
            continue
        if indent == 4 and current_item is not None:
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"invalid source root in {path}: {raw_line}")
            current_item[key] = _scalar(value)
            continue
        raise ValueError(f"unsupported indentation in {path}: {raw_line}")
    return contract


def adapter_string_literals(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def split_session_fields(value: object) -> list[str]:
    return [field.strip() for field in str(value).split(",") if field.strip()]


class PlatformContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = {path.stem: load_contract(path) for path in CONTRACTS_DIR.glob("*.yaml")}

    def test_all_platform_contracts_present(self):
        self.assertEqual(EXPECTED_PLATFORMS, set(self.contracts))

    def test_contract_schema_and_repo_evidence(self):
        for platform, contract in sorted(self.contracts.items()):
            with self.subTest(platform=platform):
                self.assertEqual(REQUIRED_FIELDS, set(contract))
                self.assertEqual(platform, contract["platform_id"])
                self.assertIn(contract["transcript_support"], {"full", "partial", "none"})
                self.assertIsInstance(contract["hook_support"], bool)
                self.assertIsInstance(contract["hook_paths"], list)
                if contract["hook_support"]:
                    self.assertTrue(contract["hook_paths"], "hook-enabled adapters need a repo hook path")
                    for hook_path in contract["hook_paths"]:
                        self.assertTrue((REPO_ROOT / hook_path).exists(), hook_path)
                else:
                    self.assertEqual([], contract["hook_paths"], "unsupported hooks must not be implied")

                adapter = REPO_ROOT / str(contract["adapter_script"])
                self.assertTrue(adapter.is_file(), adapter)
                self.assertEqual(".py", adapter.suffix)
                source_text = adapter.read_text(encoding="utf-8")
                literals = adapter_string_literals(adapter)
                for command in contract["required_commands"]:
                    self.assertIn(command, literals, f"{adapter} does not dispatch {command!r}")

                source_roots = contract["source_roots"]
                self.assertIsInstance(source_roots, list)
                self.assertTrue(source_roots, "transcript support requires concrete source roots")
                for source_root in source_roots:
                    self.assertIsInstance(source_root, dict)
                    self.assertEqual({"path", "evidence"}, set(source_root))
                    declared_path = source_root["path"]
                    self.assertIsInstance(declared_path, str)
                    self.assertTrue(declared_path.startswith(("~", "${")), declared_path)
                    self.assertNotRegex(declared_path, r"^[A-Za-z]:[\\/]")
                    self.assertIn(source_root["evidence"], source_text)

                rule = contract["project_match_rules"]
                self.assertEqual({"mode", "cli_flag", "session_fields", "evidence"}, set(rule))
                self.assertIn(rule["mode"], PROJECT_MATCH_MODES)
                self.assertTrue(split_session_fields(rule["session_fields"]))
                self.assertIn(rule["evidence"], source_text)
                if rule["cli_flag"] != "none":
                    self.assertIn(rule["cli_flag"], literals)

                for field in TEST_REFERENCE_FIELDS:
                    reference = contract[field]
                    self.assertEqual({"path", "test"}, set(reference))
                    test_path = REPO_ROOT / str(reference["path"])
                    self.assertTrue(test_path.is_file(), test_path)
                    class_name, separator, method_name = str(reference["test"]).partition(".")
                    self.assertTrue(separator and class_name and method_name, reference["test"])
                    test_text = test_path.read_text(encoding="utf-8")
                    self.assertRegex(test_text, rf"class\s+{re.escape(class_name)}\b")
                    self.assertIn(f"def {method_name}(", test_text)

    def test_contract_referenced_samples_and_regressions_run(self):
        executed: set[tuple[Path, str]] = set()
        for platform, contract in sorted(self.contracts.items()):
            for field in TEST_REFERENCE_FIELDS:
                reference = contract[field]
                test_path = REPO_ROOT / str(reference["path"])
                test_id = str(reference["test"])
                key = (test_path, test_id)
                if key in executed:
                    continue
                executed.add(key)
                with self.subTest(platform=platform, contract_field=field, test=test_id):
                    completed = subprocess.run(
                        [sys.executable, str(test_path), test_id],
                        cwd=REPO_ROOT,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(
                        0,
                        completed.returncode,
                        f"{test_path} {test_id} failed:\n{completed.stdout}\n{completed.stderr}",
                    )

    def test_codex_raw_retention_docs_match_the_command_contract(self):
        docs = [
            REPO_ROOT / "adapters/codex-session-distill" / "SKILL.md",
            REPO_ROOT / "adapters/codex-session-distill" / "references" / "deep-distill-workflow.md",
            REPO_ROOT / "adapters/codex-session-distill" / "references" / "output-layout.md",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in docs)
        self.assertIn("prune-raw", combined)
        self.assertNotIn("--keep-raw", combined)
        self.assertNotIn("(deletes raw JSONL)", combined)

    def test_install_script_has_preview_and_backup_guards(self):
        installer = (REPO_ROOT / "shared" / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$WhatIf", installer)
        self.assertIn("BackupRoot", installer)
        self.assertIn("Move-Item", installer)

    def test_packet_memory_export_uses_the_canonical_codex_path(self):
        skill = (REPO_ROOT / "helpers/packet-memory-export" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("~/.codex/session-distill/packets", skill)
        self.assertNotIn("~/.Codex", skill)


if __name__ == "__main__":
    unittest.main()
