"""Automatic Claim Verification Engine (Auto-Answer-Me).

Verifies discoverable claims (FILE_EXISTS, SYMBOL_GREP, CONFIG_VALUE, ROUTE_ENDPOINT, MIGRATION)
against target codebase HEAD without requiring manual interactive queries.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".cache",
    ".turbo",
    ".next",
    "coverage",
    ".gradle",
    ".idea",
    ".vscode",
    "tempmediaStorage",
}

CODE_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".conf",
    ".env",
    ".yml",
    ".yaml",
    ".ps1",
    ".sh",
)


@dataclass
class VerificationResult:
    status: str  # "ANSWERED" | "CONTRADICTED" | "PENDING"
    lens: str  # "repo" | "auth" | "payment" | "deploy" | "activity"
    rule_type: str  # "FILE_EXISTS" | "SYMBOL_GREP" | "CONFIG_VALUE" | "ROUTE_ENDPOINT" | "MIGRATION" | "UNVERIFIED"
    answer: str
    evidence: str
    confidence: float  # 0.0 to 1.0


class CodebaseIndex:
    """Fast cache for repository files and symbol discovery."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self._files: list[str] = []
        self._rel_map: dict[str, list[str]] = {}  # basename.lower() -> [full_paths]
        self._scanned = False

    def scan(self) -> None:
        if self._scanned:
            return
        files_list: list[str] = []
        rel_map: dict[str, list[str]] = {}

        if self.root.exists() and self.root.is_dir():
            for dirpath, dirnames, filenames in os.walk(self.root):
                # Prune excluded or dot directories in-place before descending
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]
                for fname in filenames:
                    if fname.endswith(CODE_EXTENSIONS):
                        full_path = os.path.join(dirpath, fname)
                        files_list.append(full_path)
                        rel_map.setdefault(fname.lower(), []).append(full_path)

        self._files = files_list
        self._rel_map = rel_map
        self._scanned = True

    @property
    def files(self) -> list[str]:
        self.scan()
        return self._files

    def find_by_basename(self, basename: str) -> list[str]:
        self.scan()
        return self._rel_map.get(basename.lower(), [])

    def to_rel(self, path: str | Path) -> str:
        try:
            return os.path.relpath(path, self.root).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")


class AutoVerifier:
    """Automated claim verifier against repository HEAD."""

    # Regex patterns for extracting candidate verifiable entities
    FILE_PATH_RE = re.compile(
        r"(?:[\s`\"'(/]|^)([a-zA-Z0-9_\-\./\\]+\.(?:ts|tsx|js|json|sql|md|conf|env|ps1|sh))\b"
    )
    PASCAL_SYMBOL_RE = re.compile(
        r"\b([A-Z][a-zA-Z0-9]{2,}(?:Service|Controller|Module|Guard|Interceptor|Entity|Factory|Provider|Facade|Dto|Strategy)?)\b"
    )
    MEMBER_ACCESS_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]+)[.#]([a-zA-Z0-9_]+)\b")
    UPPER_CONST_RE = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\b")
    ROUTE_RE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH)\s+([/a-zA-Z0-9_\-:]+)\b")
    MIGRATION_RE = re.compile(r"\b(\d{10,14}[-_][a-zA-Z0-9_\-]+(?:\.ts)?)\b")
    CONFIG_ASSIGN_RE = re.compile(
        r"\b([A-Z0-9_]{3,})\s*(?:[:=]|默认为|默认值|设置(?:为)?)\s*['\"]?([a-zA-Z0-9_\-\./:]+)['\"]?"
    )

    def __init__(self, codebase_root: Path | str):
        self.index = CodebaseIndex(codebase_root)

    def verify_claim(self, claim: str) -> VerificationResult:
        """Analyze a single claim and attempt to verify it against codebase."""
        self.index.scan()
        claim_clean = claim.strip()

        # 0. Noise / Non-claim filtering
        if not claim_clean or claim_clean.startswith("Session topic:") or len(claim_clean) < 8:
            return VerificationResult(
                status="PENDING",
                lens="repo",
                rule_type="UNVERIFIED",
                answer="Non-actionable topic or greeting header",
                evidence="",
                confidence=0.0,
            )

        # 1. Try Migration match
        mig_res = self._verify_migration(claim_clean)
        if mig_res:
            return mig_res

        # 2. Try Route Endpoint match
        route_res = self._verify_route(claim_clean)
        if route_res:
            return route_res

        # 3. Try Config Value match
        cfg_res = self._verify_config_value(claim_clean)
        if cfg_res:
            return cfg_res

        # 4. Try Class/Member access match (e.g. Service.method)
        member_res = self._verify_member_access(claim_clean)
        if member_res:
            return member_res

        # 5. Try Direct File Exists match
        file_res = self._verify_file_path(claim_clean)
        if file_res:
            return file_res

        # 6. Try Symbol Grep match (PascalCase class or UPPER_CONST)
        sym_res = self._verify_symbol(claim_clean)
        if sym_res:
            return sym_res

        return VerificationResult(
            status="PENDING",
            lens=self._infer_lens(claim_clean),
            rule_type="UNVERIFIED",
            answer="",
            evidence="",
            confidence=0.0,
        )

    def _verify_migration(self, text: str) -> VerificationResult | None:
        matches = self.MIGRATION_RE.findall(text)
        for mig in matches:
            clean_mig = mig if mig.endswith(".ts") else f"{mig}.ts"
            basename = os.path.basename(clean_mig)
            found = self.index.find_by_basename(basename)
            if not found:
                # Try finding by timestamp prefix
                ts_prefix = basename.split("-")[0].split("_")[0]
                if len(ts_prefix) >= 10:
                    for f in self.index.files:
                        if ts_prefix in os.path.basename(f) and f.endswith(".ts"):
                            found.append(f)
                            break
            if found:
                target = found[0]
                rel = self.index.to_rel(target)
                return VerificationResult(
                    status="ANSWERED",
                    lens="repo",
                    rule_type="MIGRATION",
                    answer=f"Verified migration {basename}",
                    evidence=f"{rel}:L1",
                    confidence=1.0,
                )
        return None

    def _verify_route(self, text: str) -> VerificationResult | None:
        matches = self.ROUTE_RE.findall(text)
        for method, path in matches:
            method_norm = method.capitalize()  # Post, Get, Put, Delete, Patch
            segments = [seg for seg in path.split("/") if seg and not seg.startswith(":")]
            last_segment = segments[-1] if segments else ""
            if not last_segment:
                continue

            dec_pat = re.compile(rf"@{method_norm}\s*\(\s*['\"]{re.escape(last_segment)}['\"]")
            for f in self.index.files:
                if "controller" in f.lower() and f.endswith((".ts", ".js")):
                    try:
                        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                            for idx, line in enumerate(fp, start=1):
                                if dec_pat.search(line) or (f"@{method_norm}" in line and last_segment in line):
                                    rel = self.index.to_rel(f)
                                    end_line = idx + 15
                                    return VerificationResult(
                                        status="ANSWERED",
                                        lens=self._infer_lens(text),
                                        rule_type="ROUTE_ENDPOINT",
                                        answer=f"Verified {method} {path} endpoint in {os.path.basename(f)}",
                                        evidence=f"{rel}:L{idx}-L{end_line}",
                                        confidence=0.95,
                                    )
                    except Exception:
                        pass
        return None

    def _verify_config_value(self, text: str) -> VerificationResult | None:
        matches = self.CONFIG_ASSIGN_RE.findall(text)
        for key, expected_val in matches:
            if len(key) < 3 or key in {"SELECT", "FROM", "WHERE", "ORDER", "DELETE", "HTTP", "POST", "GET"}:
                continue
            pat = re.compile(rf"\b{re.escape(key)}\b\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\./:]+)['\"]?")
            for f in self.index.files:
                if any(ind in f.lower() for ind in ("config", "constant", "env", "service", "validator")):
                    try:
                        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                            for idx, line in enumerate(fp, start=1):
                                m = pat.search(line)
                                if m:
                                    found_val = m.group(1)
                                    if expected_val.lower() in found_val.lower() or found_val.lower() in expected_val.lower():
                                        rel = self.index.to_rel(f)
                                        return VerificationResult(
                                            status="ANSWERED",
                                            lens=self._infer_lens(text),
                                            rule_type="CONFIG_VALUE",
                                            answer=f"Verified {key}={found_val} in {os.path.basename(f)}",
                                            evidence=f"{rel}:L{idx}",
                                            confidence=0.95,
                                        )
                    except Exception:
                        pass
        return None

    def _verify_member_access(self, text: str) -> VerificationResult | None:
        matches = self.MEMBER_ACCESS_RE.findall(text)
        for cls_name, member_name in matches:
            if len(member_name) < 3 or member_name.lower() in {"then", "catch", "map", "length"}:
                continue
            # Search for files matching class or service
            cls_lower = cls_name.lower()
            candidate_files: list[str] = []
            for f in self.index.files:
                base = os.path.basename(f).lower()
                if cls_lower in base or base.startswith(cls_lower[:8]):
                    candidate_files.append(f)

            mem_pat = re.compile(rf"(?:async\s+)?\b{re.escape(member_name)}\b\s*\(")
            for f in (candidate_files or self.index.files):
                if f.endswith((".ts", ".tsx", ".js", ".py")):
                    try:
                        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                            content = fp.read()
                            if cls_name in content and member_name in content:
                                for idx, line in enumerate(content.splitlines(), start=1):
                                    if mem_pat.search(line) or member_name in line:
                                        rel = self.index.to_rel(f)
                                        end_line = idx + 15
                                        return VerificationResult(
                                            status="ANSWERED",
                                            lens=self._infer_lens(text),
                                            rule_type="SYMBOL_GREP",
                                            answer=f"Verified {cls_name}.{member_name} in {os.path.basename(f)}",
                                            evidence=f"{rel}:L{idx}-L{end_line}",
                                            confidence=0.95,
                                        )
                    except Exception:
                        pass
        return None

    def _verify_file_path(self, text: str) -> VerificationResult | None:
        matches = self.FILE_PATH_RE.findall(text)
        for raw_path in matches:
            clean_path = raw_path.strip("`'\"()[]").replace("\\", "/")
            if "/" in clean_path:
                candidate = self.index.root / clean_path
                if candidate.exists() and candidate.is_file():
                    rel = self.index.to_rel(candidate)
                    return VerificationResult(
                        status="ANSWERED",
                        lens=self._infer_lens(text),
                        rule_type="FILE_EXISTS",
                        answer=f"Verified file exists: {clean_path}",
                        evidence=f"{rel}:L1",
                        confidence=0.9,
                    )
            basename = os.path.basename(clean_path)
            found = self.index.find_by_basename(basename)
            if found:
                target = found[0]
                rel = self.index.to_rel(target)
                return VerificationResult(
                    status="ANSWERED",
                    lens=self._infer_lens(text),
                    rule_type="FILE_EXISTS",
                    answer=f"Verified file exists: {basename}",
                    evidence=f"{rel}:L1",
                    confidence=0.9,
                )
        return None

    def _verify_symbol(self, text: str) -> VerificationResult | None:
        # Extract candidate symbols: PascalCase, UPPER_SNAKE, or specific method names enclosed in backticks
        backtick_terms = re.findall(r"`([A-Za-z0-9_\-\.]{4,})`", text)
        pascal_terms = self.PASCAL_SYMBOL_RE.findall(text)
        upper_terms = self.UPPER_CONST_RE.findall(text)

        candidates = set(backtick_terms + pascal_terms + upper_terms)
        noise = {
            "TypeScript", "JavaScript", "PostgreSQL", "React", "NestJS", "Node", "Docker",
            "Redis", "Linux", "Windows", "Shanghai", "JSON", "HTTP", "HTTPS", "SELECT", "DELETE",
            "UPDATE", "ORDER", "LIMIT", "WHERE", "TRUE", "FALSE", "NULL", "SKIP", "LOCKED",
            "ANSI", "UTF8", "EXPIRED", "PENDING", "PAID", "FAILED", "CREATED"
        }
        candidates = [c for c in candidates if c not in noise and len(c) >= 4]

        for sym in candidates:
            def_pat = re.compile(
                rf"(?:class|interface|enum|function|const|let|type|export\s+(?:class|interface|enum|function|const|type))\s+\b{re.escape(sym)}\b"
            )
            for f in self.index.files:
                if f.endswith((".ts", ".tsx", ".js", ".sql", ".py")):
                    try:
                        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                            for idx, line in enumerate(fp, start=1):
                                if def_pat.search(line):
                                    rel = self.index.to_rel(f)
                                    end_line = idx + 15
                                    return VerificationResult(
                                        status="ANSWERED",
                                        lens=self._infer_lens(text),
                                        rule_type="SYMBOL_GREP",
                                        answer=f"Verified symbol {sym} defined in {os.path.basename(f)}",
                                        evidence=f"{rel}:L{idx}-L{end_line}",
                                        confidence=0.95,
                                    )
                    except Exception:
                        pass
        return None

    def _infer_lens(self, text: str) -> str:
        lower = text.lower()
        if any(k in lower for k in ("deploy", "nginx", "docker", "hsts", "ops", "ssl", "disk")):
            return "deploy"
        if any(k in lower for k in ("pay", "order", "refund", "alipay", "wechat", "price", "merchant")):
            return "payment"
        if any(k in lower for k in ("auth", "jwt", "login", "user", "sms", "phone", "uos", "token")):
            return "auth"
        if any(k in lower for k in ("activity", "活动", "game", "gift", "save", "tombstone", "rank")):
            return "activity"
        return "repo"

    def verify_answer_packet(self, packet_path: Path | str, apply: bool = False) -> dict[str, Any]:
        """Verify all Q rows in an answer packet markdown file."""
        path = Path(packet_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Answer packet not found: {path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()

        claims_map: dict[str, str] = {}
        in_claims = False
        for line in lines:
            line_str = line.strip()
            if line_str == "## Claims extracted (hypotheses)":
                in_claims = True
                continue
            if line_str.startswith("## Results") or line_str.startswith("## "):
                if in_claims and line_str != "## Claims extracted (hypotheses)":
                    in_claims = False
            if in_claims:
                m = re.match(r"^(\d+)\.\s*(.+)$", line_str)
                if m:
                    idx = int(m.group(1))
                    claims_map[f"Q{idx}"] = m.group(2).strip()

        verified_count = 0
        table_start = -1
        table_end = -1
        updated_rows: list[str] = []

        for idx, line in enumerate(lines):
            if line.strip().startswith("| ID | Lens | Status | Answer | Evidence |"):
                table_start = idx + 2
                break

        if table_start != -1:
            for idx in range(table_start, len(lines)):
                line = lines[idx]
                if not line.strip().startswith("|"):
                    table_end = idx
                    break
                row_parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(row_parts) >= 5:
                    qid, lens, status, answer, evidence = row_parts[:5]
                    claim_text = claims_map.get(qid, "")
                    if status == "PENDING" and claim_text:
                        res = self.verify_claim(claim_text)
                        if res.status == "ANSWERED":
                            status = "ANSWERED"
                            lens = res.lens
                            answer = res.answer
                            evidence = res.evidence
                            verified_count += 1
                    updated_rows.append(f"| {qid} | {lens} | {status} | {answer} | {evidence} |")

        if apply and verified_count > 0 and table_start != -1:
            if table_end == -1:
                table_end = len(lines)
            new_lines = lines[:table_start] + updated_rows + lines[table_end:]
            path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return {
            "packet": str(path),
            "total_questions": len(claims_map),
            "auto_verified": verified_count,
            "applied": apply,
        }

    @classmethod
    def self_test(cls) -> bool:
        """Run self-test against temporary mock directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            src_dir = tmppath / "src"
            mig_dir = tmppath / "migrations"
            src_dir.mkdir(parents=True)
            mig_dir.mkdir(parents=True)

            # Mock files
            (src_dir / "user.service.ts").write_text(
                "export class UserService {\n  async findUser(id: string) { return null; }\n}\n",
                encoding="utf-8",
            )
            (src_dir / "auth.controller.ts").write_text(
                "@Controller('auth')\nexport class AuthController {\n  @Post('login')\n  async login() {}\n}\n",
                encoding="utf-8",
            )
            (src_dir / "app.config.ts").write_text(
                "export const MAX_RETRY_COUNT = 5;\nexport const AUTH_TIMEOUT = '30s';\n",
                encoding="utf-8",
            )
            (mig_dir / "1789000000000-CreateUserTable.ts").write_text(
                "export class CreateUserTable1789000000000 {}\n",
                encoding="utf-8",
            )

            verifier = cls(tmppath)

            # 1. Test FILE_EXISTS
            r1 = verifier.verify_claim("user.service.ts 文件存在")
            assert r1.status == "ANSWERED" and r1.rule_type == "FILE_EXISTS", f"FILE_EXISTS failed: {r1}"

            # 2. Test SYMBOL_GREP
            r2 = verifier.verify_claim("UserService 负责用户查询逻辑")
            assert r2.status == "ANSWERED" and r2.rule_type == "SYMBOL_GREP", f"SYMBOL_GREP failed: {r2}"

            # 3. Test Member access
            r3 = verifier.verify_claim("UserService.findUser 方法实现")
            assert r3.status == "ANSWERED" and "UserService.findUser" in r3.answer, f"Member access failed: {r3}"

            # 4. Test ROUTE_ENDPOINT
            r4 = verifier.verify_claim("POST /auth/login 接口定义在控制器中")
            assert r4.status == "ANSWERED" and r4.rule_type == "ROUTE_ENDPOINT", f"ROUTE_ENDPOINT failed: {r4}"

            # 5. Test CONFIG_VALUE
            r5 = verifier.verify_claim("配置常量 MAX_RETRY_COUNT=5")
            assert r5.status == "ANSWERED" and r5.rule_type == "CONFIG_VALUE", f"CONFIG_VALUE failed: {r5}"

            # 6. Test MIGRATION
            r6 = verifier.verify_claim("数据库迁移 1789000000000-CreateUserTable.ts 已落地")
            assert r6.status == "ANSWERED" and r6.rule_type == "MIGRATION", f"MIGRATION failed: {r6}"

            # 7. Test Answer Packet table rewriting
            packet_file = tmppath / "test-packet.md"
            packet_file.write_text(
                "# Answer Packet: test\n\n"
                "## Claims extracted (hypotheses)\n\n"
                "1. user.service.ts 文件存在\n"
                "2. 非法声明无法匹配 nonexistent\n\n"
                "## Results\n\n"
                "| ID | Lens | Status | Answer | Evidence |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| Q1 | repo | PENDING | | |\n"
                "| Q2 | repo | PENDING | | |\n\n"
                "## Promotion gate\n",
                encoding="utf-8",
            )
            res = verifier.verify_answer_packet(packet_file, apply=True)
            assert res["total_questions"] == 2, f"Total questions mismatch: {res}"
            assert res["auto_verified"] == 1, f"Auto verified count mismatch: {res}"

            updated_content = packet_file.read_text(encoding="utf-8")
            assert "| Q1 | auth | ANSWERED | Verified file exists: user.service.ts | src/user.service.ts:L1 |" in updated_content
            assert "| Q2 | repo | PENDING |" in updated_content

        return True
