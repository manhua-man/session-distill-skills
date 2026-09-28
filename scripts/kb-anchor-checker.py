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


EXCLUDED_SYMBOL_WORDS = {
    "true", "false", "null", "none", "unknown", "android", "huawei", "ios",
    "test", "prod", "default", "type", "file", "http", "https", "limit",
    "order", "orders", "users", "action", "error", "warn", "info", "debug",
    "undefined", "void", "any", "never",
}


def is_likely_symbol(text: str) -> bool:
    """Determine if a string is likely a code symbol (Class, Function, Const, Enum)."""
    t = text.strip()
    if not t or len(t) < 3 or " " in t or "/" in t or "\\" in t or ":" in t or "=" in t:
        return False
    if t.lower() in EXCLUDED_SYMBOL_WORDS:
        return False
    # PascalCase or camelCase or UPPER_CASE constants
    if re.match(r"^[A-Z][a-zA-Z0-9_]+$", t) or re.match(r"^[a-z][a-zA-Z0-9]+[A-Z][a-zA-Z0-9]+$", t) or re.match(r"^[A-Z][A-Z0-9_]{2,}$", t):
        if not t.startswith("HTTP_"):
            return True
    return False


VERIFIED_DATE_PATTERN = re.compile(r"\(verified\s+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\)", re.IGNORECASE)
CONSTANT_ASSIGN_PATTERN = re.compile(r"\b(?P<key>[A-Z][A-Z0-9_]{2,})\s*=\s*(?P<val>[a-zA-Z0-9_.-]+)")


def is_value_equivalent(claimed: str, found: str) -> bool:
    """Check if claimed constant value is equivalent to found code value."""
    if claimed.lower() == found.lower():
        return True
    # Human time shorthand like 6h vs 6 (e.g. 6 * 60 * 60)
    if claimed.lower().endswith(("h", "m", "d", "s")):
        unit_prefix = claimed[:-1]
        if unit_prefix == found:
            return True
    return False


def extract_title_keywords(title: str) -> list[str]:
    """Extract key Chinese 2-4 char subsegments and English words from rule title."""
    kws = set()
    for m in re.finditer(r"[A-Za-z0-9_]{3,}", title):
        w = m.group(0).lower()
        if w not in EXCLUDED_SYMBOL_WORDS:
            kws.add(m.group(0))
    chinese_blocks = re.findall(r"[\u4e00-\u9fff]+", title)
    for block in chinese_blocks:
        if len(block) <= 4:
            kws.add(block)
        else:
            for wlen in (2, 3):
                for i in range(len(block) - wlen + 1):
                    kws.add(block[i : i + wlen])
    return list(kws)


@dataclass
class SemanticVerdict:
    rule_idx: int
    rule_title: str
    verified_date: str | None
    latest_commit_date: str | None
    status: str  # 'UNTOUCHED_FRESH', 'ANSWERED', 'CONTRADICTED', 'MOVED', 'STALE'
    target_file: Path | None
    evidence: str = ""
    suggested_fix: str | None = None


@dataclass
class SemanticReport:
    total_rules: int = 0
    untouched_fresh_count: int = 0
    answered_count: int = 0
    contradicted_count: int = 0
    moved_count: int = 0
    stale_count: int = 0
    verdicts: list[SemanticVerdict] = field(default_factory=list)


class KnowledgeBaseAnchorChecker:
    def __init__(self, codebase_root: Path, kb_file: Path):
        self.codebase_root = codebase_root.resolve()
        self.kb_file = kb_file.resolve()
        self._file_cache: dict[str, list[Path]] = {}
        self._symbol_cache: set[str] = set()
        self._git_commit_cache: dict[str, str] = {}
        self._build_file_index()
        self._build_git_commit_cache()

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

        # 6. Fallback: match by filename (preferring files in same subproject tree as kb_file)
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

    def resolve_constant_value(self, symbol: str, context_file: Path | None = None) -> str | None:
        """Resolve an uppercase constant symbol to its literal string or numeric value."""
        pat = re.compile(rf"\b{re.escape(symbol)}\s*[:=]\s*['\"]?([^'\"\s,;)]+)")
        if context_file and context_file.exists():
            try:
                m = pat.search(context_file.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    val = m.group(1).rstrip(";,").strip()
                    if val != symbol:
                        return val
            except Exception:
                pass

        for pths in self._file_cache.values():
            for p in pths:
                if p.suffix.lower() in {".ts", ".tsx", ".js", ".env", ".template"}:
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        if symbol in content:
                            m = pat.search(content)
                            if m:
                                val = m.group(1).rstrip(";,").strip()
                                if val != symbol and not re.match(r"^[A-Z][A-Z0-9_]{3,}$", val):
                                    return val
                    except Exception:
                        pass
        return None

    def find_constant_definition_file(self, symbol: str) -> Path | None:
        """Find the file defining an uppercase constant symbol."""
        pat = re.compile(rf"\b{re.escape(symbol)}(?:_DEFAULT)?\s*[:=]\s*['\"]?([^'\"\s,;)]+)")
        kb_parts = set(self.kb_file.parts)
        candidates: list[Path] = []
        for pths in self._file_cache.values():
            for p in pths:
                if p.suffix.lower() in {".ts", ".tsx", ".js", ".env", ".template"}:
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        if symbol in content and pat.search(content):
                            candidates.append(p)
                    except Exception:
                        pass
        if candidates:
            candidates.sort(key=lambda p: (-len(kb_parts.intersection(set(p.parts))), len(str(p))))
            return candidates[0]
        return None

    def search_symbol(self, symbol: str) -> bool:
        """Quickly check if a symbol appears in indexed source files."""
        if symbol in self._symbol_cache:
            return True
        pattern = symbol.encode("utf-8")
        searchable_exts = {".ts", ".tsx", ".js", ".jsx", ".json", ".sql", ".ps1", ".py", ".cs", ".sh", ".yml", ".yaml", ".conf"}
        for paths in self._file_cache.values():
            for p in paths:
                if p.suffix.lower() in searchable_exts:
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

    def reverify_semantic(self, auto_update_verified: bool = False) -> SemanticReport:
        """Apply Answer-Me three-state verification to KB rules with Git delta acceleration."""
        from datetime import datetime, timezone
        content = self.kb_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        report = SemanticReport()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_lines: list[str] = []

        rule_idx = 0
        for line_no, line in enumerate(lines, start=1):
            line_str = line
            if not line_str.strip().startswith("- **["):
                new_lines.append(line_str)
                continue

            rule_idx += 1
            title_match = re.match(r"^-\s*\*\*\[(?P<tag>[^\]]+)\]\s*(?P<title>[^*]+)\*\*:\s*(?P<desc>.*)$", line_str)
            rule_title = title_match.group("title").strip() if title_match else f"Rule #{rule_idx}"

            # Extract verified date
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

            # Include definition files of asserted constants so their git deltas are checked
            for km in CONSTANT_ASSIGN_PATTERN.finditer(line_str):
                ckey = km.group("key")
                cdef_file = self.find_constant_definition_file(ckey)
                if cdef_file and cdef_file not in anchored_files:
                    anchored_files.append(cdef_file)

            # Check commit date of anchored files
            latest_commit = None
            for af in anchored_files:
                cdate = self.get_latest_commit_date(af)
                if cdate:
                    if latest_commit is None or cdate > latest_commit:
                        latest_commit = cdate

            # If code has not changed since verified date -> UNTOUCHED_FRESH
            if verified_date and latest_commit and latest_commit <= verified_date:
                report.untouched_fresh_count += 1
                report.verdicts.append(
                    SemanticVerdict(
                        rule_idx=rule_idx,
                        rule_title=rule_title,
                        verified_date=verified_date,
                        latest_commit_date=latest_commit,
                        status="UNTOUCHED_FRESH",
                        target_file=anchored_files[0] if anchored_files else None,
                        evidence=f"Code untainted (commit {latest_commit} <= verified {verified_date})",
                    )
                )
                new_lines.append(line_str)
                continue

            # Code was modified or unverified -> Perform Semantic Truth Audit
            # 1. Check constants / values asserted in rule
            contradiction_found = None
            for km in CONSTANT_ASSIGN_PATTERN.finditer(line_str):
                ckey = km.group("key")
                cval = km.group("val")
                found_match = False
                matched_valid = False
                first_conflict = None
                for af in anchored_files:
                    try:
                        ftext = af.read_text(encoding="utf-8", errors="ignore")
                        pat = re.compile(rf"\b{re.escape(ckey)}(?:_DEFAULT)?\s*[:=](?![=])\s*['\"]?([^'\"\s,;)]+)")
                        for match in pat.finditer(ftext):
                            found_match = True
                            found_val = match.group(1).rstrip(";,").strip()
                            if is_value_equivalent(cval, found_val):
                                matched_valid = True
                                break
                            if re.match(r"^[A-Z][A-Z0-9_]{3,}$", found_val):
                                alias_val = self.resolve_constant_value(found_val, af)
                                if alias_val and is_value_equivalent(cval, alias_val):
                                    matched_valid = True
                                    break
                            if not first_conflict:
                                first_conflict = (ckey, cval, found_val, af)
                        if matched_valid:
                            break
                    except Exception:
                        pass
                if matched_valid:
                    continue
                if first_conflict:
                    contradiction_found = first_conflict
                    break
                if not found_match:
                    codebase_val = self.resolve_constant_value(ckey)
                    if codebase_val and not is_value_equivalent(cval, codebase_val):
                        target = self.find_constant_definition_file(ckey) or (anchored_files[0] if anchored_files else None)
                        contradiction_found = (ckey, cval, codebase_val, target)
                        break

            if contradiction_found:
                ckey, claimed_val, found_val, target_file = contradiction_found
                report.contradicted_count += 1
                report.verdicts.append(
                    SemanticVerdict(
                        rule_idx=rule_idx,
                        rule_title=rule_title,
                        verified_date=verified_date,
                        latest_commit_date=latest_commit,
                        status="CONTRADICTED",
                        target_file=target_file,
                        evidence=f"Value conflict in {target_file.name if target_file else 'codebase'}: claimed '{ckey}={claimed_val}' but code has '{found_val}'",
                        suggested_fix=f"Update rule to reflect '{ckey}={found_val}'",
                    )
                )
                new_lines.append(line_str)
                continue

            # 2. Check if symbols are still present or moved
            moved_symbol = None
            stale_symbol = None
            extracted_symbols: list[str] = []
            for km in CONSTANT_ASSIGN_PATTERN.finditer(line_str):
                extracted_symbols.append(km.group("key"))
            for m in BACKTICK_PATTERN.finditer(line_str):
                code = m.group("code").strip()
                if is_likely_symbol(code):
                    extracted_symbols.append(code)

            if extracted_symbols and anchored_files:
                symbols_in_anchor: list[str] = []
                missing_symbols: list[str] = []
                for sym in extracted_symbols:
                    found = False
                    for af in anchored_files:
                        try:
                            if sym in af.read_text(encoding="utf-8", errors="ignore"):
                                symbols_in_anchor.append(sym)
                                found = True
                                break
                        except Exception:
                            pass
                    if not found:
                        missing_symbols.append(sym)

                title_keywords = extract_title_keywords(rule_title)
                anchor_has_title_kw = any(
                    kw in af.read_text(encoding="utf-8", errors="ignore")
                    for kw in title_keywords
                    for af in anchored_files
                )

                if not symbols_in_anchor or (missing_symbols and not anchor_has_title_kw):
                    anchor_score = len(symbols_in_anchor) + (1 if anchor_has_title_kw else 0)
                    for sym in (missing_symbols or extracted_symbols):
                        if self.search_symbol(sym):
                            kb_parts = set(self.kb_file.parts)
                            candidate_files = []
                            for pths in self._file_cache.values():
                                for p in pths:
                                    if p.suffix.lower() in {".ts", ".js", ".ps1"} and sym.encode() in p.read_bytes():
                                        try:
                                            cand_text = p.read_text(encoding="utf-8", errors="ignore")
                                            cand_score = sum(1 for s in extracted_symbols if s in cand_text) + (
                                                1 if any(kw in cand_text for kw in title_keywords) else 0
                                            )
                                            if cand_score > anchor_score:
                                                candidate_files.append((p, cand_score))
                                        except Exception:
                                            pass
                            if candidate_files:
                                candidate_files.sort(
                                    key=lambda item: (
                                        -item[1],
                                        -len(kb_parts.intersection(set(item[0].parts))),
                                    )
                                )
                                moved_symbol = (sym, candidate_files[0][0])
                                break
                        else:
                            stale_symbol = sym
                            break

            if stale_symbol:
                report.stale_count += 1
                report.verdicts.append(
                    SemanticVerdict(
                        rule_idx=rule_idx,
                        rule_title=rule_title,
                        verified_date=verified_date,
                        latest_commit_date=latest_commit,
                        status="STALE",
                        target_file=anchored_files[0] if anchored_files else None,
                        evidence=f"Referenced symbol `{stale_symbol}` deleted from codebase",
                    )
                )
                new_lines.append(line_str)
                continue

            if moved_symbol:
                report.moved_count += 1
                sym, new_file = moved_symbol
                report.verdicts.append(
                    SemanticVerdict(
                        rule_idx=rule_idx,
                        rule_title=rule_title,
                        verified_date=verified_date,
                        latest_commit_date=latest_commit,
                        status="MOVED",
                        target_file=new_file,
                        evidence=f"Symbol `{sym}` relocated to {new_file.relative_to(self.codebase_root)}",
                        suggested_fix=f"Relink to {new_file.name}",
                    )
                )
                new_lines.append(line_str)
                continue

            # 3. Everything verified still true! -> ANSWERED
            report.answered_count += 1
            if auto_update_verified and verified_date:
                line_str = VERIFIED_DATE_PATTERN.sub(f"(verified {today_str})", line_str)

            report.verdicts.append(
                SemanticVerdict(
                    rule_idx=rule_idx,
                    rule_title=rule_title,
                    verified_date=verified_date,
                    latest_commit_date=latest_commit,
                    status="ANSWERED",
                    target_file=anchored_files[0] if anchored_files else None,
                    evidence=f"Code verified (latest commit {latest_commit})",
                )
            )
            new_lines.append(line_str)

        report.total_rules = rule_idx
        if auto_update_verified and report.answered_count > 0:
            self.kb_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return report

    def auto_heal(self) -> list[dict[str, Any]]:
        """Silently auto-correct broken markdown file links and relative paths in KB."""
        content = self.kb_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        repairs: list[dict[str, Any]] = []

        new_lines: list[str] = []
        for line_no, line in enumerate(lines, start=1):
            line_str = line
            if not line_str.strip().startswith("- **["):
                new_lines.append(line_str)
                continue

            # Process explicit markdown links: [label](url)
            for m in LINK_PATTERN.finditer(line_str):
                label = m.group("label").strip()
                url = m.group("url").strip()
                resolved = self.resolve_file(url, reference_base_dir=self.kb_file.parent)

                if resolved is None:
                    # Try to locate by filename
                    cleaned_url = url.split("#")[0].replace("file:///", "").replace("\\", "/").strip()
                    # Strip trailing colon if any (like file.ts:L16)
                    if ":" in cleaned_url and not (len(cleaned_url) >= 2 and cleaned_url[1] == ":" and len(cleaned_url) == 2):
                        parts = cleaned_url.split(":")
                        if len(parts) > 1 and len(parts[0]) > 1:
                            cleaned_url = parts[0]
                    fname = Path(cleaned_url).name.lower()
                    if fname in self._file_cache and len(self._file_cache[fname]) == 1:
                        target = self._file_cache[fname][0]
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
                        repairs.append({"line": line_no, "old": old_link, "new": new_link, "target": str(target)})

            new_lines.append(line_str)

        if repairs:
            self.kb_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return repairs


def run_self_test() -> int:
    """Unit test for KnowledgeBaseAnchorChecker including auto-heal and semantic re-verification."""
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        src_dir = temp_root / "src"
        src_dir.mkdir()
        test_file = src_dir / "payment.service.ts"
        test_file.write_text("export const AUTH_MAX_CONCURRENT_SESSIONS_DEFAULT = 1;\nexport class PaymentService {\n  refund() {}\n}\n", encoding="utf-8")

        notes_dir = temp_root / "notes"
        notes_dir.mkdir()
        kb_file = notes_dir / "session-knowledge-base.md"
        kb_content = (
            "# Session KB\n\n"
            "- **[Payment/Refund] 微信支付退款幂等**: 必须加锁 [payment.service.ts:L1](file:///E:/broken/path/payment.service.ts#L1) (verified 2026-08-01).\n"
            "- **[Payment/Valid] 正常文件引用**: 正常引用 [payment.service.ts:L1](file:///"
            + test_file.as_posix()
            + "#L1) (verified 2026-08-01).\n"
            "- **[Auth/Conflict] 冲突常量规则**: 默认配置 AUTH_MAX_CONCURRENT_SESSIONS=3 [payment.service.ts:L1](file:///"
            + test_file.as_posix()
            + "#L1) (verified 2026-08-01).\n"
        )
        kb_file.write_text(kb_content, encoding="utf-8")

        checker = KnowledgeBaseAnchorChecker(codebase_root=temp_root, kb_file=kb_file)
        report_before = checker.check()
        assert report_before.stale_file_count == 1, f"Expected 1 stale file, got {report_before.stale_file_count}"

        # Test auto_heal
        repairs = checker.auto_heal()
        assert len(repairs) == 1, f"Expected 1 auto repair, got {len(repairs)}"

        report_after = checker.check()
        assert report_after.stale_file_count == 0, f"Expected 0 stale files after heal, got {report_after.stale_file_count}"
        assert report_after.valid_count == 3, f"Expected 3 valid anchors after heal, got {report_after.valid_count}"

        # Test semantic re-verification
        sem_report = checker.reverify_semantic()
        assert sem_report.total_rules == 3, f"Expected 3 rules, got {sem_report.total_rules}"
        assert sem_report.contradicted_count == 1, f"Expected 1 contradiction detected, got {sem_report.contradicted_count}"
        assert sem_report.answered_count == 2, f"Expected 2 answered, got {sem_report.answered_count}"

    print("kb-anchor-checker self-test: OK (All anchor resolution, stale checks, auto-heal, and semantic reverify passed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit, reverify, and auto-heal codebase anchors in session-knowledge-base.md")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "reverify", "self-test"], help="Action to run")
    parser.add_argument("--codebase", type=Path, default=None, help="Root path of target codebase")
    parser.add_argument("--kb-file", type=Path, default=None, help="Path to session-knowledge-base.md")
    parser.add_argument("--fix", action="store_true", help="Silently auto-heal broken links and file references in-place")
    parser.add_argument("--update-verified", action="store_true", help="Bump verified date to today for confirmed ANSWERED rules")
    parser.add_argument("--strict", action="store_true", help="Exit with non-zero code if any stale or contradicted rules exist")

    args = parser.parse_args(argv)

    if args.action == "self-test":
        return run_self_test()

    codebase_root = args.codebase or find_default_codebase()
    kb_file = args.kb_file or find_default_kb_file(codebase_root)

    if not kb_file or not kb_file.exists():
        print(f"Error: Could not locate session-knowledge-base.md in {codebase_root}")
        return 1

    checker = KnowledgeBaseAnchorChecker(codebase_root=codebase_root, kb_file=kb_file)

    if args.fix:
        repairs = checker.auto_heal()
        if repairs:
            print(f"Auto-healed {len(repairs)} broken link(s) in {kb_file}:")
            for rep in repairs:
                print(f"  [Line {rep['line']}] {rep['old']} -> {rep['new']}")
        else:
            print(f"All code anchors in {kb_file} are already fresh. No repairs needed.")
        print("-" * 70)

    if args.action == "reverify":
        print(f"Running Answer-Me Continuous Semantic Re-Verification on: {kb_file}")
        print(f"Target Codebase: {codebase_root}")
        print("-" * 70)

        sem_report = checker.reverify_semantic(auto_update_verified=args.update_verified)
        print(f"Total Rules Audited:           {sem_report.total_rules}")
        print(f"Untouched & Fresh (Git Delta): {sem_report.untouched_fresh_count}")
        print(f"Verified Active (ANSWERED):    {sem_report.answered_count}")
        print(f"Logic Conflicts (CONTRADICTED):{sem_report.contradicted_count}")
        print(f"Relocated Anchors (MOVED):     {sem_report.moved_count}")
        print(f"Deleted Code (STALE):          {sem_report.stale_count}")
        print("-" * 70)

        if sem_report.contradicted_count > 0 or sem_report.moved_count > 0 or sem_report.stale_count > 0:
            print("\nSemantic Findings Detail:")
            for v in sem_report.verdicts:
                if v.status in {"CONTRADICTED", "MOVED", "STALE"}:
                    print(f"  [{v.status}] [Rule #{v.rule_idx}] {v.rule_title}")
                    print(f"    - Target:    {v.target_file.name if v.target_file else 'Unknown'}")
                    print(f"    - Evidence:  {v.evidence}")
                    if v.suggested_fix:
                        print(f"    - Action:    {v.suggested_fix}")
                    print()

            if args.strict and sem_report.contradicted_count > 0:
                return 1

        print("Semantic reverification completed.")
        return 0

    print(f"Auditing Code Anchors in: {kb_file}")
    print(f"Target Codebase: {codebase_root}")
    print("-" * 70)

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
