#!/usr/bin/env python3
"""
Packet Memory Exporter - Convert session packets into draft memory entries.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

DISTILL_DIR = Path.home() / ".claude" / "session-distill"
PACKETS_DIR = DISTILL_DIR / "packets"
MEMORY_DRAFTS_DIR = DISTILL_DIR / "memory-drafts"
SYNC_LISTS_DIR = DISTILL_DIR / "sync-lists"
ALLOWED_LABELS = {"new", "refine", "confirm", "conflict", "ephemeral"}
REVIEW_STATUSES = {"pending", "approved", "rejected", "deferred"}
REVIEW_STATUS_PRIORITY = {
    "pending": 0,
    "approved": 1,
    "deferred": 2,
    "rejected": 3,
}
READINESS_PRIORITY = {
    "ready-candidate": 0,
    "needs-raw-review": 1,
    "needs-conflict-review": 2,
    "local-only": 3,
}
NORMATIVE_MARKERS = (
    "must",
    "should",
    "always",
    "default",
    "never",
    "必须",
    "应该",
    "默认",
    "总是",
    "不要",
    "不能",
)
MODULE_FACT_MARKERS = (
    "dto",
    "service",
    "controller",
    "validation",
    "transform",
    "signature",
    "api",
    "字段",
    "接口",
    "链路",
    "签名",
    "校验",
    "模块",
)
NEGATION_MARKERS = (
    " not ",
    " never ",
    " cannot ",
    " can't ",
    " without ",
    " 不要 ",
    " 不能 ",
    " 不是 ",
    " 无需 ",
)
EPHEMERAL_MARKERS = (
    "one-off",
    "temporary",
    "temp ",
    "for this task",
    "for this session",
    "current run",
    "session id",
    "request id",
    "timestamp",
    "临时",
    "一次性",
    "当前任务",
    "本次",
    "这次",
)
PROJECT_RULE_MARKERS = (
    "default workflow",
    "before promoting",
    "review",
    "ai should",
    "future ai",
    "默认 workflow",
    "默认工作流",
    "以后",
    "评审",
    "提炼前",
    "promotion",
)
WORKFLOW_MARKERS = (
    " run ",
    " use ",
    " check ",
    " inspect ",
    " verify ",
    " read ",
    " query ",
    " rg ",
    " grep ",
    "执行",
    "检查",
    "查看",
    "先",
    "再",
)
SOURCE_PRIORITY = {
    "final_answers": 3,
    "assistant_updates": 2,
    "user_requests": 1,
}
TEXT_SECTIONS = {
    "User Requests": "user_requests",
    "Assistant Updates": "assistant_updates",
    "Final Answers": "final_answers",
}
BULLET_SECTIONS = {
    "Commands": "commands",
    "Referenced Files": "referenced_files",
    "System Events": "system_events",
}


def now_iso():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_dirs():
    MEMORY_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_LISTS_DIR.mkdir(parents=True, exist_ok=True)


def normalize_text(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_statement(text):
    cleaned = normalize_text(text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip("`'\" ")
    return cleaned


def append_review_note(existing_note, new_note):
    existing = normalize_text(existing_note)
    incoming = normalize_text(new_note)
    if not incoming:
        return existing
    if not existing:
        return incoming
    return f"{existing}\n{incoming}"


def sync_list_path(session_id):
    return SYNC_LISTS_DIR / f"{session_id}.json"


def contains_any(text, markers):
    return any(marker in text for marker in markers)


def first_sentence(text, limit=240):
    cleaned = normalize_statement(text)
    if not cleaned:
        return ""
    first_line = cleaned.splitlines()[0].strip()
    if first_line and len(first_line) <= limit:
        cleaned = first_line
    match = re.search(r"^(.{1,%d}?[。！？.!?])" % limit, cleaned)
    if match:
        return match.group(1).strip()
    return cleaned[:limit].rstrip()


def parse_audit_value(line, label):
    prefix = f"- {label}: "
    if not line.startswith(prefix):
        return ""
    value = line[len(prefix):].strip()
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def parse_packet(packet_path):
    packet = {
        "session_id": packet_path.stem,
        "source_packet": str(packet_path),
        "audit": {
            "coverage": "unknown",
            "warnings": [],
            "lossy_transforms": [],
            "turns_rendered": 0,
            "invalid_json_lines": 0,
            "orphan_tool_results": 0,
            "unfinished_turns": 0,
            "compaction_events": 0,
        },
        "turns": [],
    }
    lines = packet_path.read_text(encoding="utf-8").splitlines()
    current_turn = None
    current_top = ""
    current_sub = ""
    idx = 0

    while idx < len(lines):
        line = lines[idx]

        if line.startswith("# Session Packet:"):
            packet["session_id"] = line.split(":", 1)[1].strip()
            idx += 1
            continue

        if line.startswith("## "):
            current_top = line[3:].strip()
            current_sub = ""
            if current_top.startswith("Turn "):
                number = int(current_top.split()[1])
                current_turn = {
                    "number": number,
                    "turn_id": "",
                    "user_requests": [],
                    "assistant_updates": [],
                    "final_answers": [],
                    "commands": [],
                    "referenced_files": [],
                    "system_events": [],
                }
                packet["turns"].append(current_turn)
            else:
                current_turn = None
            idx += 1
            continue

        if line.startswith("### "):
            current_sub = line[4:].strip()
            idx += 1
            continue

        if current_top == "Packet Audit":
            if line.startswith("- Coverage: "):
                packet["audit"]["coverage"] = parse_audit_value(line, "Coverage")
            elif line.startswith("- Turns rendered: "):
                packet["audit"]["turns_rendered"] = int(parse_audit_value(line, "Turns rendered") or 0)
            elif line.startswith("- Invalid JSON lines skipped: "):
                packet["audit"]["invalid_json_lines"] = int(parse_audit_value(line, "Invalid JSON lines skipped") or 0)
            elif line.startswith("- Orphan tool results: "):
                packet["audit"]["orphan_tool_results"] = int(parse_audit_value(line, "Orphan tool results") or 0)
            elif line.startswith("- Unfinished turns: "):
                packet["audit"]["unfinished_turns"] = int(parse_audit_value(line, "Unfinished turns") or 0)
            elif line.startswith("- Compaction events: "):
                packet["audit"]["compaction_events"] = int(parse_audit_value(line, "Compaction events") or 0)
            elif current_sub == "Audit Warnings" and line.startswith("- "):
                packet["audit"]["warnings"].append(line[2:].strip())
            elif current_sub == "Lossy Transforms" and line.startswith("- "):
                packet["audit"]["lossy_transforms"].append(line[2:].strip())
            idx += 1
            continue

        if current_turn:
            if line.startswith("- Turn id: "):
                current_turn["turn_id"] = parse_audit_value(line, "Turn id")
                idx += 1
                continue
            if current_sub in TEXT_SECTIONS and line == "```text":
                block_lines = []
                idx += 1
                while idx < len(lines) and lines[idx] != "```":
                    block_lines.append(lines[idx])
                    idx += 1
                current_turn[TEXT_SECTIONS[current_sub]].append("\n".join(block_lines).strip())
                idx += 1
                continue
            if current_sub in BULLET_SECTIONS and line.startswith("- "):
                current_turn[BULLET_SECTIONS[current_sub]].append(line[2:].strip())
                idx += 1
                continue

        idx += 1

    return packet


def load_memory_statements(memory_path):
    if not memory_path:
        return []
    raw = json.loads(Path(memory_path).read_text(encoding="utf-8"))
    items = []

    def visit(value):
        if isinstance(value, str):
            statement = normalize_statement(value)
            if statement:
                items.append(statement)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key in ("statement", "title", "subtitle", "content", "narrative"):
                if key in value and value[key]:
                    visit(value[key])
            for nested_key in ("items", "observations", "entries", "results"):
                if nested_key in value:
                    visit(value[nested_key])

    visit(raw)
    deduped = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def best_memory_match(statement, memory_statements):
    normalized = normalize_statement(statement).lower()
    best_ratio = 0.0
    best_match = ""
    for existing in memory_statements:
        ratio = SequenceMatcher(None, normalized, normalize_statement(existing).lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = existing
    return best_match, best_ratio


def negation_conflict(statement, existing):
    left = f" {normalize_statement(statement).lower()} "
    right = f" {normalize_statement(existing).lower()} "
    left_has_negation = any(marker in left for marker in NEGATION_MARKERS)
    right_has_negation = any(marker in right for marker in NEGATION_MARKERS)
    return left_has_negation != right_has_negation


def looks_ephemeral(statement):
    lowered = f" {normalize_statement(statement).lower()} "
    if contains_any(lowered, EPHEMERAL_MARKERS):
        return True
    if re.search(r"\b(?:request|session|ticket|issue)\s*#?\d{3,}\b", lowered):
        return True
    return False


def looks_workflow(statement, turn):
    lowered = f" {normalize_statement(statement).lower()} "
    return bool(turn["commands"]) or contains_any(lowered, WORKFLOW_MARKERS)


def looks_project_rule(statement, turn):
    lowered = f" {normalize_statement(statement).lower()} "
    if contains_any(lowered, PROJECT_RULE_MARKERS):
        return True
    return contains_any(lowered, NORMATIVE_MARKERS) and looks_workflow(statement, turn)


def choose_destination(statement, turn):
    lowered = f" {normalize_statement(statement).lower()} "
    if looks_ephemeral(statement):
        return "keep-local"
    if looks_project_rule(statement, turn):
        return "project-rules"
    if any(marker in lowered for marker in MODULE_FACT_MARKERS) and turn["referenced_files"] and not looks_workflow(statement, turn):
        return "module-docs"
    if looks_workflow(statement, turn):
        return "knowledge-base"
    if any(marker in lowered for marker in MODULE_FACT_MARKERS) or turn["referenced_files"]:
        return "module-docs"
    return "keep-local"


def choose_label(statement, destination, memory_statements):
    if destination == "keep-local":
        return "ephemeral", "Statement looks task-specific or too local for stable memory."
    if not memory_statements:
        return "new", "No existing memory input was provided, so keep this as a new draft candidate."

    best_match, best_ratio = best_memory_match(statement, memory_statements)
    if best_ratio >= 0.72 and negation_conflict(statement, best_match):
        return "conflict", f"Closest existing memory conflicts with this statement: {best_match}"
    if best_ratio >= 0.92:
        return "confirm", f"Very close match to existing memory: {best_match}"
    if best_ratio >= 0.72:
        return "refine", f"Related existing memory found and may need refinement: {best_match}"
    return "new", "No close existing memory match was found."


def build_entry(statement, source_kind, turn, session_id, memory_statements, requires_raw_review, index):
    destination = choose_destination(statement, turn)
    label, rationale = choose_label(statement, destination, memory_statements)
    if label == "ephemeral":
        sync_readiness = "local-only"
    elif label == "conflict":
        sync_readiness = "needs-conflict-review"
    elif requires_raw_review:
        sync_readiness = "needs-raw-review"
    else:
        sync_readiness = "ready-candidate"
    evidence_refs = {
        "turn_number": turn["number"],
        "turn_id": turn["turn_id"],
        "source_kind": source_kind,
        "commands": turn["commands"][:5],
        "files": turn["referenced_files"][:5],
    }
    if requires_raw_review and label in {"new", "refine", "confirm"}:
        rationale = f"{rationale} Packet Audit is partial, so raw transcript review is required before sync."
    return {
        "id": f"{session_id}-{index}",
        "statement": statement,
        "label": label,
        "sync_readiness": sync_readiness,
        "review_status": "pending",
        "review_note": "",
        "reviewed_at": "",
        "review_log": [],
        "rationale": rationale,
        "destination": destination,
        "source_session_id": session_id,
        "evidence_refs": evidence_refs,
    }


def candidate_seed_score(seed):
    score = SOURCE_PRIORITY.get(seed["source_kind"], 0) * 100
    score += len(seed["turn"]["commands"]) * 5
    score += len(seed["turn"]["referenced_files"]) * 3
    score += len(seed["turn"]["system_events"])
    return score


def similar_statement(left, right, threshold=0.95):
    return (
        SequenceMatcher(
            None,
            normalize_statement(left).lower(),
            normalize_statement(right).lower(),
        ).ratio()
        >= threshold
    )


def dedupe_candidate_seeds(seeds):
    deduped = []
    for seed in seeds:
        statement = normalize_statement(seed["statement"])
        if not statement:
            continue
        duplicate_index = None
        for index, existing in enumerate(deduped):
            if similar_statement(statement, existing["statement"]):
                duplicate_index = index
                break
        if duplicate_index is None:
            deduped.append(seed)
            continue
        if candidate_seed_score(seed) > candidate_seed_score(deduped[duplicate_index]):
            deduped[duplicate_index] = seed
    return deduped


def collect_candidates(packet, memory_statements):
    seeds = []
    requires_raw_review = packet["audit"]["coverage"] == "partial"

    for turn in packet["turns"]:
        text_blocks = turn["final_answers"] or turn["assistant_updates"]
        for block in text_blocks:
            statement = first_sentence(block)
            if not statement:
                continue
            seeds.append(
                {
                    "statement": statement,
                    "source_kind": "final_answers" if turn["final_answers"] else "assistant_updates",
                    "turn": turn,
                }
            )

    if not seeds:
        for turn in packet["turns"]:
            if not turn["user_requests"]:
                continue
            statement = first_sentence(turn["user_requests"][0])
            if not statement:
                continue
            seeds.append(
                {
                    "statement": statement,
                    "source_kind": "user_requests",
                    "turn": turn,
                }
            )

    deduped_seeds = dedupe_candidate_seeds(seeds)
    entries = []
    for index, seed in enumerate(deduped_seeds, start=1):
        entries.append(
            build_entry(
                statement=seed["statement"],
                source_kind=seed["source_kind"],
                turn=seed["turn"],
                session_id=packet["session_id"],
                memory_statements=memory_statements,
                requires_raw_review=requires_raw_review,
                index=index,
            )
        )

    return entries, requires_raw_review


def packet_to_draft(packet_path, memory_path=None):
    packet = parse_packet(packet_path)
    memory_statements = load_memory_statements(memory_path)
    entries, requires_raw_review = collect_candidates(packet, memory_statements)

    sync_candidates = []
    blocked_sync_candidates = []
    conflict_ids = []
    local_only_ids = []
    label_counts = Counter()
    readiness_counts = Counter()
    review_counts = Counter()

    for entry in entries:
        label_counts[entry["label"]] += 1
        readiness_counts[entry["sync_readiness"]] += 1
        review_counts[entry["review_status"]] += 1
        if entry["label"] == "ephemeral":
            local_only_ids.append(entry["id"])
            continue
        if entry["label"] == "conflict":
            conflict_ids.append(entry["id"])
            continue
        if requires_raw_review:
            blocked_sync_candidates.append(entry["id"])
        else:
            sync_candidates.append(entry["id"])

    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "source_packet": str(packet_path),
        "session_id": packet["session_id"],
        "memory_input": str(memory_path) if memory_path else None,
        "packet_audit": packet["audit"],
        "requires_raw_review": requires_raw_review,
        "draft_entries": entries,
        "label_counts": dict(sorted(label_counts.items())),
        "readiness_counts": dict(sorted(readiness_counts.items())),
        "review_counts": dict(sorted(review_counts.items())),
        "sync_candidates": sync_candidates,
        "blocked_sync_candidates": blocked_sync_candidates,
        "conflict_ids": conflict_ids,
        "local_only_ids": local_only_ids,
    }


def infer_sync_readiness(entry, requires_raw_review):
    label = entry.get("label")
    if label == "ephemeral":
        return "local-only"
    if label == "conflict":
        return "needs-conflict-review"
    if requires_raw_review and label in {"new", "refine", "confirm"}:
        return "needs-raw-review"
    return "ready-candidate"


def hydrate_draft(draft):
    draft = dict(draft)
    requires_raw_review = bool(draft.get("requires_raw_review"))
    entries = []
    label_counts = Counter()
    readiness_counts = Counter()
    review_counts = Counter()
    sync_candidates = []
    blocked_sync_candidates = []
    conflict_ids = []
    local_only_ids = []

    for entry in draft.get("draft_entries") or []:
        hydrated_entry = dict(entry)
        hydrated_entry["sync_readiness"] = hydrated_entry.get("sync_readiness") or infer_sync_readiness(
            hydrated_entry,
            requires_raw_review,
        )
        review_status = hydrated_entry.get("review_status") or "pending"
        if review_status not in REVIEW_STATUSES:
            review_status = "pending"
        hydrated_entry["review_status"] = review_status
        hydrated_entry["review_note"] = normalize_text(hydrated_entry.get("review_note"))
        hydrated_entry["reviewed_at"] = normalize_text(hydrated_entry.get("reviewed_at"))
        hydrated_entry["review_log"] = list(hydrated_entry.get("review_log") or [])
        entries.append(hydrated_entry)
        label = hydrated_entry.get("label")
        readiness = hydrated_entry.get("sync_readiness")
        if label:
            label_counts[label] += 1
        if readiness:
            readiness_counts[readiness] += 1
        review_counts[hydrated_entry["review_status"]] += 1
        if label == "ephemeral":
            local_only_ids.append(hydrated_entry["id"])
        elif label == "conflict":
            conflict_ids.append(hydrated_entry["id"])
        elif readiness == "needs-raw-review":
            blocked_sync_candidates.append(hydrated_entry["id"])
        elif readiness == "ready-candidate":
            sync_candidates.append(hydrated_entry["id"])

    draft["draft_entries"] = entries
    draft["label_counts"] = dict(sorted(label_counts.items()))
    draft["readiness_counts"] = dict(sorted(readiness_counts.items()))
    draft["review_counts"] = dict(sorted(review_counts.items()))
    draft["sync_candidates"] = sync_candidates
    draft["blocked_sync_candidates"] = blocked_sync_candidates
    draft["conflict_ids"] = conflict_ids
    draft["local_only_ids"] = local_only_ids
    return draft


def load_draft(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return hydrate_draft(raw)


def save_draft(path, draft):
    hydrated = hydrate_draft(draft)
    Path(path).write_text(json.dumps(hydrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return hydrated


def build_sync_list(draft, draft_path):
    approved_entries = []
    for entry in draft.get("draft_entries") or []:
        if entry.get("review_status") != "approved":
            continue
        if entry.get("sync_readiness") != "ready-candidate":
            continue
        if entry.get("label") not in {"new", "refine", "confirm"}:
            continue
        approved_entries.append(
            {
                "id": entry.get("id"),
                "statement": entry.get("statement"),
                "label": entry.get("label"),
                "destination": entry.get("destination"),
                "source_session_id": entry.get("source_session_id"),
                "review_note": entry.get("review_note"),
                "reviewed_at": entry.get("reviewed_at"),
                "evidence_refs": entry.get("evidence_refs") or {},
            }
        )
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "source_draft": str(draft_path),
        "session_id": draft.get("session_id"),
        "approved_ready_count": len(approved_entries),
        "entries": approved_entries,
    }


def refresh_sync_list(draft, draft_path):
    path = sync_list_path(draft.get("session_id") or Path(draft_path).stem)
    payload = build_sync_list(draft, draft_path)
    if payload["approved_ready_count"] == 0:
        if path.exists():
            path.unlink()
        return None, payload
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, payload


def latest_matching_file(directory, pattern):
    items = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return items[0] if items else None


def resolve_draft_path(session_id=None, draft_path=None, latest=False):
    if draft_path:
        candidate = Path(draft_path)
    elif session_id:
        candidate = MEMORY_DRAFTS_DIR / f"{session_id}.json"
    elif latest:
        candidate = latest_matching_file(MEMORY_DRAFTS_DIR, "*.json")
    else:
        candidate = None
    if not candidate or not candidate.exists():
        raise FileNotFoundError(f"Draft not found: {candidate or '<latest>'}")
    return candidate


def resolve_packet_path(session_id=None, packet_path=None, latest=False):
    if packet_path:
        candidate = Path(packet_path)
    elif session_id:
        candidate = PACKETS_DIR / f"{session_id}.md"
    elif latest:
        candidate = latest_matching_file(PACKETS_DIR, "*.md")
    else:
        candidate = None
    if not candidate or not candidate.exists():
        raise FileNotFoundError(f"Packet not found: {candidate or '<latest>'}")
    return candidate


def cmd_status():
    ensure_dirs()
    packet_count = len(list(PACKETS_DIR.glob("*.md"))) if PACKETS_DIR.exists() else 0
    draft_paths = list(MEMORY_DRAFTS_DIR.glob("*.json")) if MEMORY_DRAFTS_DIR.exists() else []
    draft_count = len(draft_paths)
    sync_list_paths = list(SYNC_LISTS_DIR.glob("*.json")) if SYNC_LISTS_DIR.exists() else []
    sync_list_count = len(sync_list_paths)
    aggregate_sync_ready = 0
    aggregate_labels = Counter()
    aggregate_readiness = Counter()
    aggregate_review = Counter()
    for draft_path in draft_paths:
        draft = load_draft(draft_path)
        aggregate_labels.update(draft.get("label_counts") or {})
        aggregate_readiness.update(draft.get("readiness_counts") or {})
        aggregate_review.update(draft.get("review_counts") or {})
    for sync_path in sync_list_paths:
        raw = json.loads(sync_path.read_text(encoding="utf-8"))
        aggregate_sync_ready += int(raw.get("approved_ready_count") or 0)
    print("==> Packet Memory Exporter Status")
    print("")
    print(f"Packets: {packet_count}")
    print(f"Memory drafts: {draft_count}")
    print(f"Sync lists: {sync_list_count}")
    print(f"Approved ready entries: {aggregate_sync_ready}")
    print(f"Output dir: {MEMORY_DRAFTS_DIR}")
    if aggregate_labels:
        print("")
        print("Label counts:")
        for label in sorted(aggregate_labels):
            print(f"  - {label}: {aggregate_labels[label]}")
    if aggregate_readiness:
        print("")
        print("Readiness counts:")
        for readiness in sorted(aggregate_readiness):
            print(f"  - {readiness}: {aggregate_readiness[readiness]}")
    if aggregate_review:
        print("")
        print("Review counts:")
        for review_status in sorted(aggregate_review):
            print(f"  - {review_status}: {aggregate_review[review_status]}")


def cmd_list():
    ensure_dirs()
    print("==> Packets Available For Export")
    print("")
    packets = sorted(PACKETS_DIR.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not packets:
        print("No packets found")
        return 0
    for packet in packets:
        draft_path = MEMORY_DRAFTS_DIR / f"{packet.stem}.json"
        status = "drafted" if draft_path.exists() else "pending"
        if draft_path.exists():
            draft = load_draft(draft_path)
            readiness = draft.get("readiness_counts") or {}
            review_counts = draft.get("review_counts") or {}
            coverage = ((draft.get("packet_audit") or {}).get("coverage") or "unknown")
            summary = ", ".join(f"{key}={value}" for key, value in sorted(readiness.items()))
            review_summary = ", ".join(f"{key}={value}" for key, value in sorted(review_counts.items()))
            suffix = f" coverage={coverage}"
            if summary:
                suffix += f" | {summary}"
            if review_summary:
                suffix += f" | review[{review_summary}]"
            print(f"- {packet.stem} [{status}] {suffix}")
        else:
            print(f"- {packet.stem} [{status}]")
    return 0


def cmd_export(session_id=None, packet_path=None, memory_path=None, force=False, latest=False):
    ensure_dirs()
    resolved_packet = resolve_packet_path(
        session_id=session_id,
        packet_path=packet_path,
        latest=latest or (not session_id and not packet_path),
    )
    output_path = MEMORY_DRAFTS_DIR / f"{resolved_packet.stem}.json"
    if output_path.exists() and not force:
        print(f"Draft already exists: {output_path}")
        print("Use --force to regenerate.")
        return 0

    draft = packet_to_draft(resolved_packet, memory_path=memory_path)
    output_path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sync_path, sync_payload = refresh_sync_list(draft, output_path)

    print(f"==> Memory draft exported: {output_path}")
    print(f"Entries: {len(draft['draft_entries'])}")
    print(f"Requires raw review: {draft['requires_raw_review']}")
    print(f"Sync candidates: {len(draft['sync_candidates'])}")
    print(f"Blocked sync candidates: {len(draft['blocked_sync_candidates'])}")
    print(f"Conflicts: {len(draft['conflict_ids'])}")
    print(f"Local only: {len(draft['local_only_ids'])}")
    print("Label counts:")
    for label, count in sorted((draft.get("label_counts") or {}).items()):
        print(f"  - {label}: {count}")
    print("Readiness counts:")
    for readiness, count in sorted((draft.get("readiness_counts") or {}).items()):
        print(f"  - {readiness}: {count}")
    print("Review counts:")
    for review_status, count in sorted((draft.get("review_counts") or {}).items()):
        print(f"  - {review_status}: {count}")
    if sync_path:
        print(f"Sync list: {sync_path} ({sync_payload['approved_ready_count']} approved ready entrie(s))")
    return 0


def cmd_review(session_id=None, draft_path=None, readiness=None, label=None, review_status=None, limit=20, latest=False):
    ensure_dirs()
    resolved_draft = resolve_draft_path(
        session_id=session_id,
        draft_path=draft_path,
        latest=latest or (not session_id and not draft_path),
    )
    draft = load_draft(resolved_draft)
    entries = draft.get("draft_entries") or []
    if readiness:
        entries = [entry for entry in entries if entry.get("sync_readiness") == readiness]
    if label:
        entries = [entry for entry in entries if entry.get("label") == label]
    if review_status:
        entries = [entry for entry in entries if entry.get("review_status") == review_status]
    entries = sorted(
        entries,
        key=lambda entry: (
            REVIEW_STATUS_PRIORITY.get(entry.get("review_status"), 99),
            READINESS_PRIORITY.get(entry.get("sync_readiness"), 99),
            (entry.get("evidence_refs") or {}).get("turn_number") or 0,
            entry.get("id") or "",
        ),
    )

    print(f"==> Review: {draft.get('session_id')}")
    print(f"Draft: {resolved_draft}")
    print(f"Source packet: {draft.get('source_packet')}")
    print(f"Coverage: {(draft.get('packet_audit') or {}).get('coverage', 'unknown')}")
    print(f"Requires raw review: {draft.get('requires_raw_review')}")
    generated_sync_list = sync_list_path(draft.get("session_id"))
    if generated_sync_list.exists():
        raw_sync = json.loads(generated_sync_list.read_text(encoding="utf-8"))
        print(f"Sync list: {generated_sync_list} ({raw_sync.get('approved_ready_count', 0)} approved ready)")
    print("")
    print("Label counts:")
    for item_label, count in sorted((draft.get("label_counts") or {}).items()):
        print(f"  - {item_label}: {count}")
    print("Readiness counts:")
    for item_readiness, count in sorted((draft.get("readiness_counts") or {}).items()):
        print(f"  - {item_readiness}: {count}")
    print("Review counts:")
    for item_review_status, count in sorted((draft.get("review_counts") or {}).items()):
        print(f"  - {item_review_status}: {count}")

    if not entries:
        print("")
        print("No entries matched the current filters.")
        return 0

    print("")
    print(f"Showing up to {limit} entries")
    print("")
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry.get("sync_readiness") or "unknown", []).append(entry)

    shown = 0
    for group_name in sorted(grouped):
        print(f"## {group_name}")
        print("")
        for entry in grouped[group_name]:
            if shown >= limit:
                break
            shown += 1
            evidence = entry.get("evidence_refs") or {}
            commands = evidence.get("commands") or []
            files = evidence.get("files") or []
            print(
                f"- [{entry['id']}] `{entry['label']}` -> `{entry['destination']}` | review=`{entry.get('review_status')}`"
            )
            print(f"  statement: {entry['statement']}")
            print(f"  rationale: {entry['rationale']}")
            if entry.get("review_note"):
                print(f"  review_note: {entry['review_note']}")
            print(
                f"  evidence: turn={evidence.get('turn_number')} source={evidence.get('source_kind')} commands={len(commands)} files={len(files)}"
            )
        print("")
        if shown >= limit:
            break
    if len(entries) > shown:
        print(f"... {len(entries) - shown} more entrie(s) not shown")
    print("")
    print("Review actions:")
    print(f"  - approve: packet-memory-export approve --session {draft.get('session_id')} --entry <entry-id>")
    print(f"  - approve-batch: packet-memory-export approve-batch --session {draft.get('session_id')} --review-status pending --readiness ready-candidate")
    print(f"  - reject: packet-memory-export reject --session {draft.get('session_id')} --entry <entry-id> --note \"why\"")
    print(f"  - reject-batch: packet-memory-export reject-batch --session {draft.get('session_id')} --entries <id1,id2>")
    print(f"  - defer: packet-memory-export defer --session {draft.get('session_id')} --entry <entry-id> --note \"follow-up\"")
    print(f"  - note: packet-memory-export note --session {draft.get('session_id')} --entry <entry-id> --note \"comment\"")
    print(f"  - sync-list: packet-memory-export sync-list --session {draft.get('session_id')}")
    return 0


def find_entry(draft, entry_id):
    for entry in draft.get("draft_entries") or []:
        if entry.get("id") == entry_id:
            return entry
    raise KeyError(f"Entry not found: {entry_id}")


def parse_entry_ids(entries):
    if not entries:
        return []
    if isinstance(entries, (list, tuple)):
        tokens = entries
    else:
        tokens = str(entries).split(",")
    cleaned = []
    seen = set()
    for token in tokens:
        value = normalize_text(token)
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def select_entries(draft, entry_ids=None, readiness=None, label=None, review_status=None):
    entries = draft.get("draft_entries") or []
    if entry_ids:
        wanted = set(parse_entry_ids(entry_ids))
        entries = [entry for entry in entries if entry.get("id") in wanted]
    if readiness:
        entries = [entry for entry in entries if entry.get("sync_readiness") == readiness]
    if label:
        entries = [entry for entry in entries if entry.get("label") == label]
    if review_status:
        entries = [entry for entry in entries if entry.get("review_status") == review_status]
    return entries


def apply_review_action(entry, action, note):
    previous_status = entry.get("review_status") or "pending"
    timestamp = now_iso()
    normalized_note = normalize_text(note)

    if action == "approve":
        entry["review_status"] = "approved"
    elif action == "reject":
        entry["review_status"] = "rejected"
    elif action == "defer":
        entry["review_status"] = "deferred"
    elif action == "note":
        entry["review_status"] = previous_status
        if not normalized_note:
            raise ValueError("Provide --note when using note")
    else:
        raise ValueError(f"Unsupported review action: {action}")

    if normalized_note:
        entry["review_note"] = append_review_note(entry.get("review_note"), normalized_note)
    entry["reviewed_at"] = timestamp
    entry.setdefault("review_log", [])
    entry["review_log"].append(
        {
            "at": timestamp,
            "action": action,
            "previous_status": previous_status,
            "new_status": entry["review_status"],
            "note": normalized_note,
        }
    )
    return previous_status, entry["review_status"]


def cmd_update_review(action, entry_id, session_id=None, draft_path=None, note="", latest=False):
    ensure_dirs()
    if not entry_id:
        raise ValueError("Provide --entry")
    resolved_draft = resolve_draft_path(
        session_id=session_id,
        draft_path=draft_path,
        latest=latest or (not session_id and not draft_path),
    )
    draft = load_draft(resolved_draft)
    entry = find_entry(draft, entry_id)
    previous_status, _ = apply_review_action(entry, action, note)

    draft = save_draft(resolved_draft, draft)
    sync_path, sync_payload = refresh_sync_list(draft, resolved_draft)
    refreshed = find_entry(draft, entry_id)
    print(f"==> Review updated: {entry_id}")
    print(f"Draft: {resolved_draft}")
    print(f"Status: {previous_status} -> {refreshed['review_status']}")
    if refreshed.get("review_note"):
        print(f"Note: {refreshed['review_note']}")
    if sync_path:
        print(f"Sync list: {sync_path} ({sync_payload['approved_ready_count']} approved ready entrie(s))")
    else:
        print("Sync list: none (no approved ready entries)")
    print("Review counts:")
    for review_status, count in sorted((draft.get("review_counts") or {}).items()):
        print(f"  - {review_status}: {count}")
    return 0


def cmd_batch_update_review(action, session_id=None, draft_path=None, entry_ids=None, readiness=None, label=None, review_status=None, note="", latest=False):
    ensure_dirs()
    resolved_draft = resolve_draft_path(
        session_id=session_id,
        draft_path=draft_path,
        latest=latest or (not session_id and not draft_path),
    )
    if not entry_ids and not any([readiness, label, review_status]):
        raise ValueError("Provide --entries or at least one filter for batch review")
    draft = load_draft(resolved_draft)
    targets = select_entries(
        draft,
        entry_ids=entry_ids,
        readiness=readiness,
        label=label,
        review_status=review_status,
    )
    if not targets:
        print("No entries matched the batch selection.")
        return 0

    changes = []
    for entry in targets:
        previous_status, new_status = apply_review_action(entry, action, note)
        changes.append((entry.get("id"), previous_status, new_status))

    draft = save_draft(resolved_draft, draft)
    sync_path, sync_payload = refresh_sync_list(draft, resolved_draft)

    print(f"==> Batch review updated: {len(changes)} entrie(s)")
    print(f"Draft: {resolved_draft}")
    for entry_id, previous_status, new_status in changes[:10]:
        print(f"  - {entry_id}: {previous_status} -> {new_status}")
    if len(changes) > 10:
        print(f"  ... {len(changes) - 10} more entrie(s)")
    if sync_path:
        print(f"Sync list: {sync_path} ({sync_payload['approved_ready_count']} approved ready entrie(s))")
    else:
        print("Sync list: none (no approved ready entries)")
    print("Review counts:")
    for item_review_status, count in sorted((draft.get("review_counts") or {}).items()):
        print(f"  - {item_review_status}: {count}")
    return 0


def cmd_sync_list(session_id=None, draft_path=None, latest=False):
    ensure_dirs()
    resolved_draft = resolve_draft_path(
        session_id=session_id,
        draft_path=draft_path,
        latest=latest or (not session_id and not draft_path),
    )
    draft = load_draft(resolved_draft)
    sync_path, payload = refresh_sync_list(draft, resolved_draft)
    if not sync_path:
        print("==> Sync list not generated")
        print(f"Draft: {resolved_draft}")
        print("Reason: no approved ready entries yet")
        return 0
    print(f"==> Sync list: {sync_path}")
    print(f"Entries: {payload['approved_ready_count']}")
    for entry in payload["entries"][:10]:
        print(f"- [{entry['id']}] `{entry['label']}` -> `{entry['destination']}`")
        print(f"  statement: {entry['statement']}")
    if len(payload["entries"]) > 10:
        print(f"... {len(payload['entries']) - 10} more entrie(s)")
    return 0


def cmd_self_test():
    import unittest

    print("==> Packet Memory Exporter Self-Test")
    test_dir = Path(__file__).resolve().parents[1] / "tests"
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main():
    commands = {"export", "review", "approve", "reject", "defer", "note", "approve-batch", "reject-batch", "sync-list", "status", "list", "self-test", "help"}
    argv = list(sys.argv[1:])
    command = "help"
    for index, token in enumerate(argv):
        if token in commands:
            command = token
            del argv[index]
            break

    parser = argparse.ArgumentParser(description="Packet Memory Exporter")
    parser.add_argument("--session", help="Session id that maps to packets/<session-id>.md")
    parser.add_argument("--packet", help="Explicit packet path")
    parser.add_argument("--draft", help="Explicit draft JSON path")
    parser.add_argument("--latest", action="store_true", help="Use the latest packet/draft when no explicit session is given")
    parser.add_argument("--memory", help="Optional JSON file containing existing memory statements")
    parser.add_argument("--entry", help="Entry id inside the draft JSON")
    parser.add_argument("--entries", help="Comma-separated entry ids for batch review actions")
    parser.add_argument("--note", help="Optional review note to persist with the action")
    parser.add_argument("--readiness", help="Filter review output by sync_readiness")
    parser.add_argument("--label", help="Filter review output by label")
    parser.add_argument("--review-status", help="Filter review output by review_status")
    parser.add_argument("--limit", type=int, default=20, help="Maximum entries to show in review output")
    parser.add_argument("--force", action="store_true", help="Regenerate even if the output JSON already exists")
    args = parser.parse_args(argv)

    if command == "help":
        parser.print_help()
        return 0
    if command == "status":
        cmd_status()
        return 0
    if command == "list":
        return cmd_list()
    if command == "review":
        return cmd_review(
            session_id=args.session,
            draft_path=args.draft,
            readiness=args.readiness,
            label=args.label,
            review_status=args.review_status,
            limit=args.limit,
            latest=args.latest,
        )
    if command == "sync-list":
        return cmd_sync_list(
            session_id=args.session,
            draft_path=args.draft,
            latest=args.latest,
        )
    if command in {"approve", "reject", "defer", "note"}:
        return cmd_update_review(
            action=command,
            entry_id=args.entry,
            session_id=args.session,
            draft_path=args.draft,
            note=args.note or "",
            latest=args.latest,
        )
    if command in {"approve-batch", "reject-batch"}:
        return cmd_batch_update_review(
            action=command.replace("-batch", ""),
            session_id=args.session,
            draft_path=args.draft,
            entry_ids=args.entries,
            readiness=args.readiness,
            label=args.label,
            review_status=args.review_status,
            note=args.note or "",
            latest=args.latest,
        )
    if command == "self-test":
        return cmd_self_test()
    return cmd_export(
        session_id=args.session,
        packet_path=args.packet,
        memory_path=args.memory,
        force=args.force,
        latest=args.latest,
    )


if __name__ == "__main__":
    sys.exit(main())
