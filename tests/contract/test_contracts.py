"""Contract tests for seven platform adapters (portable, repo-local)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def load_contract(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    platform_id = re.search(r"^platform_id:\s*(.+)$", text, re.M)
    adapter_script = re.search(r"^adapter_script:\s*(.+)$", text, re.M)
    growth_test = re.search(r"^growth_test:\s*(.+)$", text, re.M)
    lossless_rebuild_test = re.search(r"^lossless_rebuild_test:\s*(.+)$", text, re.M)
    commands: list[str] = []
    capture = False
    for line in text.splitlines():
        if line.strip() == "required_commands:":
            capture = True
            continue
        if capture:
            if not line.startswith("  - "):
                break
            commands.append(line[4:].strip())
    return {
        "platform_id": platform_id.group(1).strip() if platform_id else "",
        "adapter_script": adapter_script.group(1).strip() if adapter_script else "",
        "required_commands": commands,
        "growth_test": growth_test.group(1).strip() if growth_test else "",
        "lossless_rebuild_test": lossless_rebuild_test.group(1).strip() if lossless_rebuild_test else "",
    }


class PlatformContractTests(unittest.TestCase):
    def test_all_platform_contracts_present(self):
        expected = {
            "cursor",
            "codex",
            "grok",
            "claude",
            "hermes",
            "antigravity",
            "opencode",
        }
        found = {path.stem for path in CONTRACTS_DIR.glob("*.yaml")}
        self.assertEqual(expected, found)

    def test_contract_files_are_valid(self):
        for path in sorted(CONTRACTS_DIR.glob("*.yaml")):
            with self.subTest(platform=path.stem):
                contract = load_contract(path)
                self.assertEqual(contract["platform_id"], path.stem)
                adapter = REPO_ROOT / contract["adapter_script"]
                self.assertTrue(adapter.exists(), adapter)
                source = adapter.read_text(encoding="utf-8")
                for command in contract["required_commands"]:
                    self.assertIn(f'"{command}"', source, msg=f"missing command {command}")
                growth = REPO_ROOT / contract["growth_test"]
                lossless = REPO_ROOT / contract["lossless_rebuild_test"]
                self.assertTrue(growth.exists(), growth)
                self.assertTrue(lossless.exists(), lossless)


if __name__ == "__main__":
    unittest.main()
