# Session Distill 上游迭代路线图

> **基线：** `session-distill-skills` @ `04f22e9`（2026-07-14）  
> **核对日期：** 2026-07-15（对照本机已安装七平台 adapter）  
> **目的：** 把 Deep Distill 从「裁剪摘要 packet」升级为可审计、可恢复、可增量重跑的 lossless pipeline。

---

## 现状摘要（与 04f22e9 对齐的已验证缺口）

| 主题 | 现状 |
|------|------|
| Packet 形态 | 单文件 Markdown 摘要；`clip_text` / `squeeze_text` 裁剪；`Coverage: partial` 仅告警 |
| TEXT_LIMIT | Claude **1200** 硬编码；Codex 默认 **1600**（`deep-distill-run` 可设 32000）；Cursor/Hermes/Antigravity 默认 **32000** |
| Revision 标识 | 依赖 `session_id` + `mtime`/`size`/`last_updated`；无内容哈希 |
| distilled 后增长 | `cmd_index` 保留 `status=distilled`；`cmd_bundle` 仅 `new`/`bundled`（Codex `bundled` 有 `needs_bundle_refresh`，**distilled 无**） |
| Chunk 恢复 | 无 chunk 级 checkpoint；中断需整包重生成 packet |
| Final review | 有 `validate_distilled`，但无强制「末轮状态 / 矛盾 / 未完成 / 证据」结构化块 |
| 候选 ID | memory draft / KB 行无稳定幂等键；重跑可能重复 |
| Raw 删除 | Codex `mark distilled` **默认删 raw**；需 `--keep-raw` 才保留 |
| Adapter contract | 七平台文档有表，但无统一 contract 测试（路径样本、增长、零丢失重建） |
| 测试 | Claude `tests/test_core.py` 写死 `C:\Users\EDY\...`；Codex/Grok 已用 `Path(__file__)` |
| 共享库 | `deep_distill_lib.py` 五份拷贝；SHA256 已漂移（见 §10） |

---

## 迭代顺序（建议严格执行）

### 1. Lossless revision + chunks（替代裁剪摘要 packet）

**问题：** `partial` 不能代替完整读取；高 `TEXT_LIMIT` 只是推迟裁剪，不是零丢失。

**目标：**

```
revisions/<session_id>/<revision_id>/
  manifest.json          # revision 元数据、source 指针、chunk 列表、pipeline_version
  raw/                   # 规范化后的完整 transcript（平台无关中间表示）
  chunks/
    0001.json            # {chunk_id, ordinal, byte_range|turn_range, sha256, status, ...}
    0001.summary.md      # 可选：供 LLM 消费的摘要视图（明确标注 non-authoritative）
  packet.md              # 索引 + audit + 指向 chunks 的目录（非唯一真源）
```

**规则：**

- Packet 降为 **索引 + audit**；晋升与 answer-me **必须能定位到 chunk/raw**。
- 所有有序 chunks 拼接（或按 turn_range 重组）可 **bit-exact 或 canonical-normalized** 重建完整 transcript。
- `Coverage: partial` 仅表示「摘要视图未覆盖全部 chunk」，**不表示** raw 缺失。

**验收：**

- 合成 fixture：10k+ 字符 user/assistant/tool 输出 → 重建 transcript 与 raw 一致。
- 现有 `build_packet` 测试改为断言 chunk 数量、重建哈希、packet 含 chunk 索引。

**触及：** 各平台 `*-session-distill.py` 的 `build_packet` → 拆为 `ingest_revision` + `emit_chunks`。

---

### 2. 内容哈希标识 revision

**问题：** 同 `session_id` 追加内容后，仅 mtime/size 变化；无法区分「同内容重扫」与「新 revision」。

**目标：**

```python
revision_id = sha256(canonical_json({
  "session_id": ...,
  "platform": "...",
  "normalized_transcript_sha256": "...",
  "source_fingerprint": {...},  # 平台相关：file path + inode/mtime 或 sqlite row version
}))[:16]
```

**规则：**

- `cmd_index`：若 `current_revision_id != manifest.last_revision_id` → 创建新 revision 记录；队列状态变为 `pending`（或 `new`）。
- 同 revision 重跑 bundle：**幂等**，不新建 revision。
- Manifest 会话条目保留 `revisions: [{revision_id, created_at, distilled_at?, status}]`。

**验收：**

- 追加一条 user message → 新 `revision_id`；内容不变仅 touch mtime → `revision_id` 不变。
- 跨平台 contract 测试各 1 例。

---

### 3. 修复 distilled 会话增长后不再入队

**问题（已复现）：**

- Cursor `cmd_index`：`queue_status = old.get("status")`，distilled 永不变。
- Cursor/Codex `cmd_bundle`：`status in {"new", "bundled"}`；distilled 排除。
- Codex `needs_bundle_refresh` 仅作用于 `bundled`，不作用于 `distilled`。

**目标：**

```python
def needs_redistill(session, current_revision_id) -> bool:
    if session.get("last_distilled_revision_id") != current_revision_id:
        return True
    return False
```

**规则：**

- `cmd_index` 检测到新 revision → `status = "pending_redistill"`（或回退 `new` 并保留 `previous_distilled_revision_id`）。
- `cmd_bundle` 接受 `pending_redistill` / `new` / 过期 `bundled`。
- `mark distilled` 写入 `last_distilled_revision_id`，而非仅 `status=distilled`。

**验收：**

- 测试：mark distilled → 追加 transcript → index → 会话重新出现在 pending 队列。
- Deep Distill queue 自动拾取新 revision。

---

### 4. Durable chunk checkpoint

**问题：** 中断后整包重生成 packet，浪费且可能漂移。

**目标：** `chunks/<revision_id>/checkpoints.json`：

```json
{
  "chunk_id": "0003",
  "state": "pending|running|done|failed",
  "attempt": 2,
  "lease_owner": "host:pid",
  "lease_expires_at": "ISO8601",
  "result_path": "chunks/0003.summary.md",
  "error": null
}
```

**规则：**

- `bundle` / `summarize-chunk` 按 ordinal 处理；仅 `pending|failed|lease_expired` 可领取。
- Lease 超时后可抢占；`done` 不可覆盖除非 `--force-chunk`。
- `deep-distill-run` 读取 checkpoint 续跑。

**验收：**

- 模拟中断（kill 于 chunk 2/5）→ 重跑仅处理 2–5，1 复用。
- 并发双进程：同一 chunk 仅一 worker 成功 claim。

---

### 5. 强制 final-session review

**问题：** 现有 `validate_distilled` 检查 note 存在与 partial 说明，不足以防止「末轮未完成却晋升」。

**目标：** `distilled/sessions/<session_id>.md` 必须含固定节：

```markdown
## Final Session Review
- **Final user request:** ...
- **Final outcome:** ...
- **Last turn state:** completed | abandoned | error | unknown
- **Contradictions:** none | ...
- **Open items:** none | ...
- **Evidence status:** all ANSWERED | partial (list Q ids) | not verified
- **Promotion allowed:** yes | no (reason)
```

**规则：**

- `validate_distilled` / `cmd_mark distilled` 缺任一字段 → 拒绝（非 `--force`）。
- `Promotion allowed: no` 时禁止写 KB（`promote` 子命令检查）。

**验收：**

- 缺 `Open items` → mark 失败。
- `Evidence status: partial` + `Promotion allowed: yes` → promote 失败。

---

### 6. 候选输出稳定幂等 ID

**问题：** 重跑 Deep Distill 可能重复 memory drafts / KB 候选行。

**目标：**

```python
candidate_id = sha256("|".join([
    source_revision_id,
    pipeline_version,      # e.g. "deep-distill-v2"
    candidate_kind,        # "memory_draft" | "kb_row" | "answer_packet_claim"
    normalized_claim,      # NFKC + lowercase + collapse_ws
]))[:20]
```

**规则：**

- `memory-drafts/<candidate_id>.md`；manifest `candidates[candidate_id]` 记录状态。
- 重跑：同 ID 存在且 `status=promoted` → skip；`status=draft` → 可选 `--refresh-candidate` 覆盖。
- KB 晋升行脚注：`[candidate:abc123 revision:def456]`。

**验收：**

- 同一 packet 连续跑两次 `deep-distill-run` → draft 文件数不增加。
- 改 `pipeline_version` → 新 ID，旧 ID 保留可追溯。

---

### 7. 原始会话默认永不删除

**问题：** Codex `cmd_mark(..., keep_raw=False)` 默认 `delete_raw_source`。

**目标：**

- `mark distilled`：**永不**删除 raw；仅更新 manifest。
- 删除 raw 仅通过显式子命令：`prune raw --session-id ... --reason ... --audit-log ...`。
- Cursor cleanup（`cleanup-cursor-distill.py`）保持 opt-in，与 mark 分离。

**验收：**

- 默认 mark distilled 后 raw 文件仍在。
- `prune raw` 写 audit JSONL；无 `--confirm` 则 dry-run。

**Breaking change：** 更新 SKILL / output-layout 文档；删除 `--keep-raw` 标志（改为默认行为）。

---

### 8. 统一七平台 adapter contract

**平台：** Grok、Cursor、Codex、Claude、Hermes、Antigravity、OpenCode。

**每平台必须声明：**

| 字段 | 说明 |
|------|------|
| `platform_id` | 稳定枚举 |
| `transcript_support` | `full` / `partial` / `none` |
| `hook_support` | 是否支持 IDE hook 注入（与 transcript 分开） |
| `source_roots` | 真实默认路径（可环境变量覆盖） |
| `project_match_rules` | 如何判定 `servers` 等仓库 |
| `sample_fixture` | 脱敏最小 JSONL/SQLite 片段 |
| `growth_test` | 追加内容 → 新 revision |
| `lossless_rebuild_test` | chunks → transcript 零丢失 |

**交付：** `contracts/<platform>.yaml` + `tests/contract/test_<platform>.py`（temp home，无硬编码用户路径）。

---

### 9. 修复测试可移植性

**问题：** Claude `tests/test_core.py`：

```python
SCRIPT_PATH = Path(r"C:\Users\EDY\.claude\skills\manhua\session-distill\bin\session-distill.py")
```

**目标：**

```python
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "session-distill.py"
```

- 所有平台测试：`tempfile.TemporaryDirectory()` 注入 `HOME` / `*_HOME` / `DISTILL_DIR`。
- CI matrix：Windows + Linux（路径分隔符与 `expanduser`）。

**验收：** 在无任何 `EDY` 路径的机器上 `python -m unittest discover` 全绿。

---

### 10. 减少共享逻辑复制

**问题：** 当前 `deep_distill_lib.py` 多份拷贝，哈希已漂移：

| SHA256 (prefix) | 路径 |
|-----------------|------|
| `72E5251A857D` | cursor, hermes, antigravity |
| `71778ABDA2AD` | codex |
| `B47B74350920` | claude/codex-session-distill |

**目标（二选一，推荐 A）：**

**A. 单一共享包**

```
session-distill-skills/
  packages/distill-core/
    distill_core/
      revision.py
      chunks.py
      checkpoint.py
      candidate_id.py
      final_review.py
  platforms/{cursor,codex,...}/bin/*-session-distill.py  # 薄 adapter
```

安装时：`pip install -e packages/distill-core` 或 vendoring 脚本从单一源复制并校验哈希。

**B. 短期：哈希一致性测试**

- `tests/test_lib_parity.py`：所有已安装 `deep_distill_lib.py` 与 `packages/distill-core` 同步。
- 发布 checklist：bump `LIB_VERSION` → 复制到七平台 → 跑 parity。

**验收：** 改 `extract_claims` 一处 → 七平台测试全过；parity 测试防止静默漂移。

---

## 建议里程碑

| 里程碑 | 包含项 | 说明 |
|--------|--------|------|
| **M1 数据真源** | §1, §2, §7 | revision/chunk/raw 落地；默认不删 raw |
| **M2 队列正确性** | §3, §6 | 增长再入队 + 幂等 candidate |
| **M3 可恢复执行** | §4, §5 | chunk checkpoint + final review 门禁 |
| **M4 工程化** | §8, §9, §10 | contract 测试、可移植测试、共享 core |

---

## 与当前 Deep Distill 工作流的关系

- Phase 1 Ingest 改为：`index` → `ingest_revision` → `bundle_chunks`（非单次 `build_packet` 裁剪）。
- Phase 2 Extract 从 **chunk summaries + raw 指针** 提取 claims，而非仅 `packet.md` 正文。
- Phase 3–7 不变，但晋升必须满足 §5 Final Review 且 claim 带 `candidate_id` / `revision_id`。
- Cursor post-distill cleanup（`cleanup-cursor-distill.py`）仍为 **独立 opt-in**，不属于 `mark distilled`。

---

## 不在本路线图内

- 自动删除 Cursor SQLite / JSONL（已由 cleanup 子命令显式处理）
- 用 `partial` 摘要直接晋升 KB（继续禁止）
- 在 `servers` 仓库内放置 distill 工具脚本（工具归 skill 包 / session-distill-skills）

---

## 参考：当前需改的关键符号

| 位置 | 符号 |
|------|------|
| Cursor | `build_packet`, `clip_text`, `cmd_index`, `cmd_bundle`, `cmd_mark` |
| Codex | 同上 + `delete_raw_source`, `needs_bundle_refresh`, `--keep-raw` |
| Claude | `squeeze_text`, `TEXT_LIMIT=1200`, `needs_bundle_refresh` |
| 共享 | `deep_distill_lib.extract_claims`, `deep-distill-run.cmd_bundle` |

---

*本文档为上游需求真源；实现落在 `session-distill-skills` 仓库，发布后同步到各 `~/.{cursor,codex,...}/skills/session-distill/`。*

---

## 实现进度（2026-07-15）

| 项 | 状态 | 备注 |
|----|------|------|
| §1 lossless revision + chunks | **M1 已落地** | `distill_core/ingest.py`；Cursor + Codex `cmd_bundle` |
| §2 内容哈希 revision | **已落地** | `compute_revision_id` / `source_fingerprint` |
| §3 distilled 增长再入队 | **已落地** | `pending_redistill`；Codex 测试 `test_growth_reopens_distilled_session` |
| §4 chunk checkpoint | **已落地** | `extract-checkpoints.json` + `deep-distill-run --force-extract`；chunk 续跑测试通过 |
| §5 final-session review | **已落地** | `validate_final_review`；`mark distilled` 门禁 |
| §6 幂等 candidate ID | **已落地** | `make_candidate_id`；`deep_distill_lib.candidate_draft_path` |
| §7 raw 默认不删 | **已落地（Codex）** | `prune-raw --confirm`；`mark` 不再默认删 |
| §8 七平台 contract | 待做 | Cursor/Codex/Grok 已有 portable tests |
| §9 测试可移植 | **部分** | Codex/Grok/distill_core 已 portable；Claude `SCRIPT_PATH` 已修 |
| §10 共享 core | **M1 已落地** | `bin/distill_core/` 为真源；Codex 已同步拷贝 |
