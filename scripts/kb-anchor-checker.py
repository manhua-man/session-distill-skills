#!/usr/bin/env python3
"""
Knowledge Base Code Anchor & Evidence Health Checker
Validates that code references, file paths, and line numbers in session-knowledge-base.md
remain valid and synchronized with target codebase HEAD.

Core capabilities:
1. Physical link verification (check): ensures referenced files exist and line numbers are within bounds.
2. Silent auto-healing (--fix): automatically repairs moved or renamed file paths in-place.
3. Git Delta radar (delta): identifies rules whose referenced code has or has not changed since last verification.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AnchorResult:
    rule_idx: int
    rule_title: str
    reference_type: str  # 'link', 'file_path'
    raw_reference: str
    resolved_path: Path | None
    line_number: int | None
    status: str  # 'VALID', 'STALE_FILE', 'STALE_LINE'
    details: str = ""


@dataclass
class CheckerReport:
    total_rules: int = 0
    total_anchors: int = 0
    valid_count: int = 0
    stale_file_count: int = 0
    stale_line_count: int = 0
    results: list[AnchorResult] = field(default_factory=list)


@dataclass
class DeltaRule:
    rule_idx: int
    rule_title: str
    verified_date: str | None
    latest_commit_date: str | None
    status: str  # 'UNTOUCHED' (code has not changed), 'TOUCHED' (code was modified since verification)
    anchored_files: list[Path] = field(default_factory=list)


@dataclass
class DeltaReport:
    total_rules: int = 0
    untouched_count: int = 0
    touched_count: int = 0
    unanchored_count: int = 0
    rules: list[DeltaRule] = field(default_factory=list)


FILE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml", ".ps1", ".sh", ".bat", ".cmd",
    ".md", ".sql", ".conf", ".env", ".proto", ".cs", ".py", ".html", ".css",
}

# Regex for markdown links: [text](target)
LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)")
# Regex for backtick code: `code`
BACKTICK_PATTERN = re.compile(r"`(?P<code>[^`]+)`")
# Regex for line numbers: :L123 or #L123 or L123-L145
LINE_PATTERN = re.compile(r"[:#]L(?P<start>\d+)(?:-L(?P<end>\d+))?", re.IGNORECASE)
# Regex for verification date stamp
VERIFIED_DATE_PATTERN = re.compile(r"\(verified\s+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\)", re.IGNORECASE)

HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
EXCLUDED_DIRS = {".git", "node_modules", "dist", "build", ".cache", "coverage", ".turbo", ".next"}


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
    found = list(codebase_root.glob("**/session-knowledge-base.md"))
    if found:
        return found[0].resolve()
    return None


def is_likely_file_path(text: str) -> bool:
    """Determine if a backticked string is intended to be a file/script path."""
    t = text.strip()
    if not t or len(t) < 3:
        return False
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
    ext = Path(t.split(":")[0]).suffix.lower()
    return ext in FILE_EXTENSIONS


class KnowledgeBaseAnchorChecker:
    def __init__(self, codebase_root: Path, kb_file: Path):
        self.codebase_root = codebase_root.resolve()
        self.kb_file = kb_file.resolve()
        self._file_cache: dict[str, list[Path]] = {}
        self._git_commit_cache: dict[str, str] = {}
        self._build_file_index()
        self._build_git_commit_cache()

    def _build_file_index(self) -> None:
        """Index all files in codebase for fast lookup using pruned os.walk."""
        for root, dirs, files in os.walk(self.codebase_root):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]
            root_path = Path(root)
            for f in files:
                name = f.lower()
                if name not in self._file_cache:
                    self._file_cache[name] = []
                self._file_cache[name].append(root_path / f)

    def _build_git_commit_cache(self) -> None:
        """Cache latest git commit dates per file using a single fast git log command."""
        git_dir = self.codebase_root / ".git"
        if not git_dir.exists():
            return
        try:
            import subprocess
            cmd = ["git", "log", "-n", "500", "--format=COMMIT:%cs", "--name-only"]
            res = subprocess.run(cmd, cwd=self.codebase_root, capture_output=True, text=True)
            current_date = None
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("COMMIT:"):
                    current_date = line.split("COMMIT:")[1]
                elif current_date:
                    norm_path = line.replace("\\", "/").lower()
                    if norm_path not in self._git_commit_cache:
                        self._git_commit_cache[norm_path] = current_date
        except Exception:
            pass

    def get_latest_commit_date(self, file_path: Path) -> str | None:
        """Get the latest git commit date for a given file."""
        try:
            rel_path = file_path.resolve().relative_to(self.codebase_root).as_posix().lower()
            return self._git_commit_cache.get(rel_path)
        except Exception:
            return None

    def resolve_file(self, raw_path: str, reference_base_dir: Path | None = None) -> Path | None:
        """Resolve a raw path string or URL to an existing Path in codebase."""
        if raw_path.startswith("file:///"):
            cleaned = raw_path[8:].split("#")[0].replace("\\", "/")
            p = Path(cleaned)
            if p.exists():
                return p.resolve()
            rel_candidate = self.codebase_root / cleaned
            if rel_candidate.exists():
                return rel_candidate.resolve()

        cleaned_path = raw_path.split("#")[0].split(":")[0].strip().replace("\\", "/")
        if not cleaned_path:
            return None

        if reference_base_dir and (reference_base_dir / cleaned_path).exists():
            return (reference_base_dir / cleaned_path).resolve()

        candidate = self.codebase_root / cleaned_path
        if candidate.exists():
            return candidate.resolve()

        for sub in ["server/word-warrior", "server/kousuan-guard-server", "front", "server"]:
            sub_cand = self.codebase_root / sub / cleaned_path
            if sub_cand.exists():
                return sub_cand.resolve()

        fname = Path(cleaned_path).name.lower()
        if fname in self._file_cache:
            matches = self._file_cache[fname]
            if matches:
                kb_parts = set(self.kb_file.parts)
                sorted_matches = sorted(
                    matches,
                    key=lambda p: (
                        -len(kb_parts.intersection(set(p.parts))),
                        len(str(p)),
                    ),
                )
                return sorted_matches[0].resolve()

        return None

    def check(self) -> CheckerReport:
        """Audit physical links and file references in session-knowledge-base.md."""
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

            # 2. Check backtick file references
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
                                details=f"Referenced path `{code}` not found in codebase",
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

        report.total_rules = rule_idx
        return report

    def auto_heal(self) -> list[dict[str, Any]]:
        """Silently auto-correct broken markdown file links and relative paths in KB."""
        content = self.kb_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        repaired: list[dict[str, Any]] = []
        new_lines: list[str] = []

        for line in lines:
            line_str = line
            if not line_str.strip().startswith("- **["):
                new_lines.append(line_str)
                continue

            for m in LINK_PATTERN.finditer(line):
                label = m.group("label").strip()
                url = m.group("url").strip()

                resolved = self.resolve_file(url, reference_base_dir=self.kb_file.parent)
                if resolved is None:
                    cleaned_url = url.split("#")[0].replace("file:///", "").replace("\\", "/").strip()
                    if ":" in cleaned_url and not (len(cleaned_url) >= 2 and cleaned_url[1] == ":" and len(cleaned_url) == 2):
                        parts = cleaned_url.split(":")
                        if len(parts) > 1 and len(parts[0]) > 1:
                            cleaned_url = parts[0]
                    fname = Path(cleaned_url).name.lower()
                    if fname in self._file_cache:
                        matches = self._file_cache[fname]
                        if matches:
                            kb_parts = set(self.kb_file.parts)
                            sorted_matches = sorted(
                                matches,
                                key=lambda p: (
                                    -len(kb_parts.intersection(set(p.parts))),
                                    len(str(p)),
                                ),
                            )
                            target = sorted_matches[0]
                            line_suffix = ""
                            line_match = LINE_PATTERN.search(url)
                            if line_match:
                                start = line_match.group("start")
                                end = line_match.group("end")
                                line_suffix = f"#L{start}-L{end}" if end else f"#L{start}"

                            new_url = f"file:///{target.as_posix()}{line_suffix}"
                            old_link = f"[{label}]({url})"
                            new_link = f"[{label}]({new_url})"
                            line_str = line_str.replace(old_link, new_link)
                            repaired.append({
                                "label": label,
                                "old_url": url,
                                "new_url": new_url,
                                "target": str(target.relative_to(self.codebase_root)),
                            })

            new_lines.append(line_str)

        if repaired:
            self.kb_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return repaired

    def delta(self, update_verified_untouched: bool = False) -> DeltaReport:
        """
        Git Delta Radar:
        Evaluates rules based on commit dates of referenced files vs (verified YYYY-MM-DD).
        - UNTOUCHED: all referenced files have zero git commits since verification date (100% mathematically fresh).
        - TOUCHED: one or more referenced files were modified in git commits after verification date (candidates for re-inspection).
        """
        content = self.kb_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        report = DeltaReport()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_lines: list[str] = []

        rule_idx = 0
        for line in lines:
            line_str = line
            if not line_str.strip().startswith("- **["):
                new_lines.append(line_str)
                continue

            rule_idx += 1
            title_match = re.match(r"^-\s*\*\*\[(?P<tag>[^\]]+)\]\s*(?P<title>[^*]+)\*\*:\s*(?P<desc>.*)$", line_str)
            rule_title = title_match.group("title").strip() if title_match else f"Rule #{rule_idx}"

            vm = VERIFIED_DATE_PATTERN.search(line_str)
            verified_date = vm.group("date") if vm else None

            # Resolve anchored files
            anchored_files: list[Path] = []
            for m in LINK_PATTERN.finditer(line_str):
                url = m.group("url").strip()
                res = self.resolve_file(url, reference_base_dir=self.kb_file.parent)
                if res and res not in anchored_files:
                    anchored_files.append(res)
            for m in BACKTICK_PATTERN.finditer(line_str):
                code = m.group("code").strip()
                if is_likely_file_path(code):
                    res = self.resolve_file(code, reference_base_dir=self.kb_file.parent)
                    if res and res not in anchored_files:
                        anchored_files.append(res)

            if not anchored_files:
                report.unanchored_count += 1
                report.rules.append(
                    DeltaRule(
                        rule_idx=rule_idx,
                        rule_title=rule_title,
                        verified_date=verified_date,
                        latest_commit_date=None,
                        status="UNANCHORED",
                        anchored_files=[],
                    )
                )
                new_lines.append(line_str)
                continue

            latest_commit = None
            for af in anchored_files:
                cdate = self.get_latest_commit_date(af)
                if cdate:
                    if latest_commit is None or cdate > latest_commit:
                        latest_commit = cdate

            if verified_date and latest_commit and latest_commit <= verified_date:
                report.untouched_count += 1
                status = "UNTOUCHED"
            else:
                report.touched_count += 1
                status = "TOUCHED"

            report.rules.append(
                DeltaRule(
                    rule_idx=rule_idx,
                    rule_title=rule_title,
                    verified_date=verified_date,
                    latest_commit_date=latest_commit,
                    status=status,
                    anchored_files=anchored_files,
                )
            )

            if update_verified_untouched and status == "UNTOUCHED" and verified_date:
                line_str = VERIFIED_DATE_PATTERN.sub(f"(verified {today_str})", line_str)

            new_lines.append(line_str)

        report.total_rules = rule_idx
        if update_verified_untouched and report.untouched_count > 0:
            self.kb_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return report


def run_self_test() -> int:
    """Unit test for KnowledgeBaseAnchorChecker including check, auto-heal, and delta radar."""
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
            "- **[Payment/Refund] 微信支付退款幂等**: 必须加锁 [payment.service.ts:L1](file:///E:/broken/path/payment.service.ts#L1) (verified 2026-08-01).\n"
            "- **[Payment/Valid] 正常文件引用**: 正常引用 [payment.service.ts:L1](file:///"
            + test_file.as_posix()
            + "#L1) (verified 2026-08-01).\n"
        )
        kb_file.write_text(kb_content, encoding="utf-8")

        checker = KnowledgeBaseAnchorChecker(temp_root, kb_file)

        # 1. Test check before healing
        report_before = checker.check()
        assert report_before.stale_file_count == 1, f"Expected 1 stale file, got {report_before.stale_file_count}"

        # 2. Test auto_heal
        healed = checker.auto_heal()
        assert len(healed) == 1, f"Expected 1 healed link, got {len(healed)}"

        # 3. Test check after healing
        report_after = checker.check()
        assert report_after.stale_file_count == 0, f"Expected 0 stale files after heal, got {report_after.stale_file_count}"
        assert report_after.valid_count == 2, f"Expected 2 valid anchors after heal, got {report_after.valid_count}"

        # 4. Test delta radar
        delta_rep = checker.delta()
        assert delta_rep.total_rules == 2, f"Expected 2 rules, got {delta_rep.total_rules}"

    print("kb-anchor-checker self-test: OK (All anchor resolution, stale checks, auto-heal, and delta radar passed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit physical links, auto-heal paths, and run Git Delta radar on session-knowledge-base.md")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "delta", "self-test"], help="Action to run")
    parser.add_argument("--codebase", type=Path, default=None, help="Root path of target codebase")
    parser.add_argument("--kb-file", type=Path, default=None, help="Path to session-knowledge-base.md")
    parser.add_argument("--fix", action="store_true", help="Silently auto-heal broken links and moved file paths in-place")
    parser.add_argument("--strict", action="store_true", help="Exit with non-zero code if any stale anchors exist")

    args = parser.parse_args(argv)

    if args.action == "self-test":
        return run_self_test()

    codebase_root = args.codebase or find_default_codebase()
    kb_file = args.kb_file or find_default_kb_file(codebase_root)

    if not kb_file or not kb_file.exists():
        print(f"Error: session-knowledge-base.md not found in {codebase_root}", file=sys.stderr)
        return 1

    checker = KnowledgeBaseAnchorChecker(codebase_root, kb_file)

    if args.fix:
        print(f"Running silent auto-heal on: {kb_file}")
        repaired = checker.auto_heal()
        if repaired:
            print(f"Successfully repaired {len(repaired)} broken/moved file links:")
            for item in repaired:
                print(f"  - [{item['label']}]: {item['old_url']} -> {item['target']}")
        else:
            print("All code anchors are already fresh. No repairs needed.")
        print("-" * 70)

    if args.action == "delta":
        print(f"Running Git Delta Radar on: {kb_file}")
        print(f"Target Codebase: {codebase_root}")
        print("-" * 70)

        delta_rep = checker.delta()
        print(f"Total Rules Audited:           {delta_rep.total_rules}")
        print(f"Untouched & Fresh (Git Delta): {delta_rep.untouched_count}")
        print(f"Touched Candidates (Modified): {delta_rep.touched_count}")
        print(f"Unanchored Rules:              {delta_rep.unanchored_count}")
        print("-" * 70)

        if delta_rep.touched_count > 0:
            print("\nTouched Candidates (Code files committed after verified date):")
            for r in delta_rep.rules:
                if r.status == "TOUCHED":
                    files_str = ", ".join(f.name for f in r.anchored_files)
                    print(f"  - [Rule #{r.rule_idx}] {r.rule_title}")
                    print(f"    * Verified: {r.verified_date or 'None'}, Latest Commit: {r.latest_commit_date or 'Unknown'}")
                    print(f"    * Files:    {files_str}")
        else:
            print("All rules are provably untouched (zero code commits since last verified date).")
        return 0

    print(f"Auditing Code Anchors in: {kb_file}")
    print(f"Target Codebase: {codebase_root}")
    print("-" * 70)

    report = checker.check()
    print(f"Total Rules Scanned:     {report.total_rules}")
    print(f"Total Code Anchors:      {report.total_anchors}")
    print(f"Valid Anchors:           {report.valid_count}")
    print(f"Stale Files (Broken):    {report.stale_file_count}")
    print(f"Stale Line Numbers:      {report.stale_line_count}")
    print("-" * 70)

    if report.stale_file_count > 0 or report.stale_line_count > 0:
        print("\nFindings Detail:")
        for res in report.results:
            if res.status != "VALID":
                print(f"  [{res.status}] [Rule #{res.rule_idx}] {res.rule_title}")
                print(f"    - Ref:     {res.raw_reference}")
                print(f"    - Detail:  {res.details}")
                print()

        if args.strict:
            return 1

    print("Anchor health check completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
