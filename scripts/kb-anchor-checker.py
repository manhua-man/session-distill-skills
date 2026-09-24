#!/usr/bin/env python3
"""
Knowledge Base Code Anchor & Evidence Health Checker
Validates that code references, file paths, line numbers, and symbols in session-knowledge-base.md
remain valid, fresh, and synchronized with the target codebase HEAD.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AnchorResult:
    rule_idx: int
    rule_title: str
    reference_type: str  # 'link', 'file_path', 'symbol'
    raw_reference: str
    resolved_path: Path | None
    line_number: int | None
    status: str  # 'VALID', 'STALE_FILE', 'STALE_LINE', 'STALE_SYMBOL', 'AMBIGUOUS'
    details: str = ""


@dataclass
class CheckerReport:
    total_rules: int = 0
    total_anchors: int = 0
    valid_count: int = 0
    stale_file_count: int = 0
    stale_line_count: int = 0
    stale_symbol_count: int = 0
    results: list[AnchorResult] = field(default_factory=list)


FILE_EXTENSIONS = {
    ".ts", ".js", ".json", ".yml", ".yaml", ".ps1", ".sh", ".bat", ".cmd",
    ".md", ".sql", ".conf", ".env", ".proto", ".cs", ".py", ".html", ".css",
}

# Regex for markdown links: [text](target)
LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)")
# Regex for backtick code: `code`
BACKTICK_PATTERN = re.compile(r"`(?P<code>[^`]+)`")
# Regex for line numbers: :L123 or #L123 or L123-L145
LINE_PATTERN = re.compile(r"[:#]L(?P<start>\d+)(?:-L(?P<end>\d+))?", re.IGNORECASE)


def find_default_codebase(start_dir: Path | None = None) -> Path:
    """Find default codebase root (e.g. servers repository or current parent)."""
    candidates = [
        Path.cwd(),
        Path.home() / "project" / "servers",
        Path(__file__).resolve().parents[2] / "servers",
    ]
    if start_dir:
        candidates.insert(0, start_dir)
    for c in candidates:
        if c.exists() and (c / ".git").exists():
            return c.resolve()
        if c.exists() and (c / "server").exists():
            return c.resolve()
    return Path.cwd().resolve()


def find_default_kb_file(codebase_root: Path) -> Path | None:
    """Find default session-knowledge-base.md file."""
    candidates = [
        codebase_root / "server" / "word-warrior" / "notes" / "session-knowledge-base.md",
        codebase_root / ".cursor" / "notes" / "conversations" / "session-knowledge-base.md",
        codebase_root / "notes" / "session-knowledge-base.md",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    # Search recursively for session-knowledge-base.md
    found = list(codebase_root.glob("**/session-knowledge-base.md"))
    if found:
        return found[0].resolve()
    return None


EXCLUDED_DIRS = {".git", "node_modules", "dist", "build", ".cache", "coverage", ".turbo", ".next"}



HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
CRON_MARKERS = {"@Cron", "*/", "0 *", "0 0"}


def is_likely_file_path(text: str) -> bool:
    """Determine if a backticked string is intended to be a file/script path."""
    t = text.strip()
    if not t or len(t) < 3:
        return False
    # Exclude HTTP routes and commands
    if any(t.startswith(f"{m} ") for m in HTTP_METHODS):
        return False
    if t.startswith("/") and not any(t.endswith(ext) for ext in FILE_EXTENSIONS):
        return False
    if t.startswith("@Cron") or t.startswith("--") or t.startswith("\\b") or t.startswith("{") or t.startswith("`"):
        return False
    if "*" in t or "..." in t or "<" in t or ">" in t:
        return False
    if t.startswith("@shared/"):
        return False
    # Must have a recognizable file extension or path separator with extension
    ext = Path(t.split(":")[0]).suffix.lower()
    return ext in FILE_EXTENSIONS


def is_likely_symbol(text: str) -> bool:
    """Determine if a string is likely a code symbol (Class, Function, Const, Enum)."""
    t = text.strip()
    if not t or len(t) < 4 or " " in t or "/" in t or "\\" in t or ":" in t:
        return False
    # PascalCase or camelCase or UPPER_CASE constants
    if re.match(r"^[A-Z][a-zA-Z0-9_]+$", t) or re.match(r"^[a-z][a-zA-Z0-9]+[A-Z][a-zA-Z0-9]+$", t) or re.match(r"^[A-Z][A-Z0-9_]{3,}$", t):
        if not t.startswith("HTTP_") and not t in {"TRUE", "FALSE", "NULL", "NONE"}:
            return True
    return False


class KnowledgeBaseAnchorChecker:
    def __init__(self, codebase_root: Path, kb_file: Path):
        self.codebase_root = codebase_root.resolve()
        self.kb_file = kb_file.resolve()
        self._file_cache: dict[str, list[Path]] = {}
        self._symbol_cache: set[str] = set()
        self._build_file_index()

    def _build_file_index(self) -> None:
        """Index all files in codebase for fast basename lookup using pruned os.walk."""
        for root, dirs, files in os.walk(self.codebase_root):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]
            root_path = Path(root)
            for f in files:
                name = f.lower()
                if name not in self._file_cache:
                    self._file_cache[name] = []
                self._file_cache[name].append(root_path / f)

    def resolve_file(self, raw_path: str, reference_base_dir: Path | None = None) -> Path | None:
        """Resolve a raw path string or URL to an existing Path in codebase."""
        # 1. Handle file:/// URLs
        if raw_path.startswith("file:///"):
            cleaned = raw_path[8:].split("#")[0].replace("\\", "/")
            p = Path(cleaned)
            if p.exists():
                return p.resolve()
            # Try resolving relative to codebase
            rel_candidate = self.codebase_root / cleaned
            if rel_candidate.exists():
                return rel_candidate.resolve()

        # 2. Strip line number anchor
        cleaned_path = raw_path.split("#")[0].split(":")[0].strip().replace("\\", "/")
        if not cleaned_path:
            return None

        # 3. Check direct relative to reference_base_dir
        if reference_base_dir and (reference_base_dir / cleaned_path).exists():
            return (reference_base_dir / cleaned_path).resolve()

        # 4. Check relative to codebase_root
        candidate = self.codebase_root / cleaned_path
        if candidate.exists():
            return candidate.resolve()

        # 5. Check in sub-packages (e.g. server/word-warrior, server/kousuan-guard-server)
        for sub in ["server/word-warrior", "server/kousuan-guard-server", "front", "server"]:
            sub_cand = self.codebase_root / sub / cleaned_path
            if sub_cand.exists():
                return sub_cand.resolve()

        # 6. Fallback: match by filename
        fname = Path(cleaned_path).name.lower()
        if fname in self._file_cache:
            matches = self._file_cache[fname]
            if matches:
                return matches[0].resolve()

        return None

    def search_symbol(self, symbol: str) -> bool:
        """Quickly check if a symbol appears in indexed source files."""
        if symbol in self._symbol_cache:
            return True
        # Search relevant source files
        pattern = symbol.encode("utf-8")
        for paths in self._file_cache.values():
            for p in paths:
                if p.suffix.lower() in {".ts", ".js", ".json", ".sql", ".ps1", ".py"}:
                    try:
                        if pattern in p.read_bytes():
                            self._symbol_cache.add(symbol)
                            return True
                    except Exception:
                        pass
        return False

    def check(self) -> CheckerReport:
        content = self.kb_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        report = CheckerReport()

        rule_idx = 0
        for line_no, line in enumerate(lines, start=1):
            line_str = line.strip()
            if not line_str.startswith("- **["):
                continue

            rule_idx += 1
            title_match = re.match(r"^-\s*\*\*\[(?P<tag>[^\]]+)\]\s*(?P<title>[^*]+)\*\*:\s*(?P<desc>.*)$", line_str)
            rule_title = title_match.group("title").strip() if title_match else f"Rule #{rule_idx}"

            # 1. Check explicit markdown links: [label](url)
            for m in LINK_PATTERN.finditer(line_str):
                label = m.group("label").strip()
                url = m.group("url").strip()

                line_no_start = None
                line_match = LINE_PATTERN.search(url) or LINE_PATTERN.search(label)
                if line_match:
                    line_no_start = int(line_match.group("start"))

                resolved = self.resolve_file(url, reference_base_dir=self.kb_file.parent)
                report.total_anchors += 1

                if resolved is None:
                    report.stale_file_count += 1
                    report.results.append(
                        AnchorResult(
                            rule_idx=rule_idx,
                            rule_title=rule_title,
                            reference_type="link",
                            raw_reference=f"[{label}]({url})",
                            resolved_path=None,
                            line_number=line_no_start,
                            status="STALE_FILE",
                            details=f"File could not be found: {url}",
                        )
                    )
                else:
                    if line_no_start is not None:
                        try:
                            total_lines = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
                            if line_no_start > total_lines:
                                report.stale_line_count += 1
                                report.results.append(
                                    AnchorResult(
                                        rule_idx=rule_idx,
                                        rule_title=rule_title,
                                        reference_type="link",
                                        raw_reference=f"[{label}]({url})",
                                        resolved_path=resolved,
                                        line_number=line_no_start,
                                        status="STALE_LINE",
                                        details=f"Line L{line_no_start} exceeds file length ({total_lines} lines)",
                                    )
                                )
                                continue
                        except Exception:
                            pass

                    report.valid_count += 1
                    report.results.append(
                        AnchorResult(
                            rule_idx=rule_idx,
                            rule_title=rule_title,
                            reference_type="link",
                            raw_reference=f"[{label}]({url})",
                            resolved_path=resolved,
                            line_number=line_no_start,
                            status="VALID",
                            details=f"Resolved to {resolved.relative_to(self.codebase_root)}",
                        )
                    )

            # 2. Check backtick file references and key symbols
            for m in BACKTICK_PATTERN.finditer(line_str):
                code = m.group("code").strip()
                if is_likely_file_path(code):
                    report.total_anchors += 1
                    resolved = self.resolve_file(code, reference_base_dir=self.kb_file.parent)
                    if resolved is None:
                        report.stale_file_count += 1
                        report.results.append(
                            AnchorResult(
                                rule_idx=rule_idx,
                                rule_title=rule_title,
                                reference_type="file_path",
                                raw_reference=f"`{code}`",
                                resolved_path=None,
                                line_number=None,
                                status="STALE_FILE",
                                details=f"Referenced file `{code}` not found",
                            )
                        )
                    else:
                        report.valid_count += 1
                        report.results.append(
                            AnchorResult(
                                rule_idx=rule_idx,
                                rule_title=rule_title,
                                reference_type="file_path",
                                raw_reference=f"`{code}`",
                                resolved_path=resolved,
                                line_number=None,
                                status="VALID",
                                details=f"Resolved to {resolved.relative_to(self.codebase_root)}",
                            )
                        )
                elif is_likely_symbol(code):
                    # Validate symbol exists in codebase
                    if not self.search_symbol(code):
                        report.stale_symbol_count += 1
                        report.results.append(
                            AnchorResult(
                                rule_idx=rule_idx,
                                rule_title=rule_title,
                                reference_type="symbol",
                                raw_reference=f"`{code}`",
                                resolved_path=None,
                                line_number=None,
                                status="STALE_SYMBOL",
                                details=f"Symbol `{code}` not found in codebase",
                            )
                        )

        report.total_rules = rule_idx
        return report


def run_self_test() -> int:
    """Unit test for KnowledgeBaseAnchorChecker."""
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        src_dir = temp_root / "src"
        src_dir.mkdir()
        test_file = src_dir / "payment.service.ts"
        test_file.write_text("export class PaymentService {\n  refund() {}\n}\n", encoding="utf-8")

        notes_dir = temp_root / "notes"
        notes_dir.mkdir()
        kb_file = notes_dir / "session-knowledge-base.md"
        kb_content = (
            "# Session KB\n\n"
            "- **[Payment/Refund] 微信支付退款幂等**: 必须加锁 [payment.service.ts:L1](file:///"
            + str(test_file).replace("\\", "/")
            + "#L1) (verified 2026-08-01).\n"
            "- **[Payment/Stale] 历史无效文件**: 无效文件引用 [non-existent.ts:L10](file:///E:/invalid/non-existent.ts#L10).\n"
            "- **[Script/Valid] 部署脚本路径**: 检查 `src/payment.service.ts` 运行逻辑.\n"
        )
        kb_file.write_text(kb_content, encoding="utf-8")

        checker = KnowledgeBaseAnchorChecker(codebase_root=temp_root, kb_file=kb_file)
        report = checker.check()

        assert report.total_rules == 3, f"Expected 3 rules, got {report.total_rules}"
        assert report.total_anchors == 3, f"Expected 3 anchors, got {report.total_anchors}"
        assert report.valid_count == 2, f"Expected 2 valid anchors, got {report.valid_count}"
        assert report.stale_file_count == 1, f"Expected 1 stale file, got {report.stale_file_count}"

    print("kb-anchor-checker self-test: OK (All anchor resolution and stale checks passed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and verify codebase anchors in session-knowledge-base.md")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "self-test"], help="Action to run")
    parser.add_argument("--codebase", type=Path, default=None, help="Root path of target codebase")
    parser.add_argument("--kb-file", type=Path, default=None, help="Path to session-knowledge-base.md")
    parser.add_argument("--strict", action="store_true", help="Exit with non-zero code if any stale anchors exist")

    args = parser.parse_args(argv)

    if args.action == "self-test":
        return run_self_test()

    codebase_root = args.codebase or find_default_codebase()
    kb_file = args.kb_file or find_default_kb_file(codebase_root)

    if not kb_file or not kb_file.exists():
        print(f"Error: Could not locate session-knowledge-base.md in {codebase_root}")
        return 1

    print(f"Auditing Code Anchors in: {kb_file}")
    print(f"Target Codebase: {codebase_root}")
    print("-" * 70)

    checker = KnowledgeBaseAnchorChecker(codebase_root=codebase_root, kb_file=kb_file)
    report = checker.check()

    print(f"Total Rules Analyzed:     {report.total_rules}")
    print(f"Total Code Anchors:       {report.total_anchors}")
    print(f"Valid Code Anchors:       {report.valid_count}")
    print(f"Stale File References:    {report.stale_file_count}")
    print(f"Stale Line References:    {report.stale_line_count}")
    print("-" * 70)

    if report.stale_file_count > 0 or report.stale_line_count > 0:
        print("\nStale Anchor Details:")
        for r in report.results:
            if r.status != "VALID":
                print(f"  [Rule #{r.rule_idx}] {r.rule_title}")
                print(f"    - Type:    {r.reference_type}")
                print(f"    - Raw:     {r.raw_reference}")
                print(f"    - Status:  {r.status}")
                print(f"    - Details: {r.details}\n")

        if args.strict:
            return 1

    print("Knowledge base anchor health check completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
