# Mnemosyne shared bank — design

Live copy for bots: skill Mnemosyne shared bank. This Dropbox file is the readable architecture doc. Do not treat this folder as live sqlite.

Companion: BOT-GUIDE.md (how every bot writes and recalls), BACKUP.md (the rotate). Local mirrors: `/workspace/mcp/mnemosyne/docs/`.

## Goal

One sqlite bank for the whole crew. Isolate with `author_id`, `author_type`, and `channel_id`. Write widely, trust narrowly, so 17+ bots do not poison each other or ingest web/email text as standing fact. Never lose memories: merge-and-rotate Dropbox JSON, 3-day dated backups, old per-bot DBs stay as archive.

Native Grok Bot memory stays L0 (prompt). Mnemosyne is L1 (query). Apps are L2 (live systems of record). Do not two-way sync them.

## Non-goals

- Live sqlite in Dropbox (WAL / multi-writer / 52MB frozen WAL).
- One sqlite file per bot (after cutover).
- The empty Hermes shared-surface DB (`mnemosyne_shared_*`).
- Embeddings / LLM extras (`MNEMOSYNE_LLM_ENABLED=false`).
- Deleting old per-bot DBs or old `/Agents/<Bot>/memory/` folders.
- Adding mem0 (or any other memory product) as a second L1. If a project needs it, it is L2: query it, do not dual-write.
- Flipping live wrappers before filtered MCP + Grok-vs-Hacka smoke test.
- Patching `/home/box/.mnemosyne/venv` (read only). Do not develop on upstream `v4.0.0b1`.

## GitHub source of truth

Crew package is **mnemosyne-memory 3.15.1**.

- Repo: https://github.com/vshalpnjabi/mnemosyne
- Branch to stay on: `crew-v3.15.1`
- Tag: `v3.15.1`
- Overlay directory: `grokbot/` (not `crew/`). Customizations only there. Path rename: https://github.com/vshalpnjabi/mnemosyne/commit/100178838cca0aad8e3e03425a0905acd8cae73b
- Do **not** develop on `v4.0.0b1`.
- Do **not** clone that git into this box as part of bot work.
- Do **not** patch site-packages. Isolation is process-local monkeypatch in `/workspace/mcp/mnemosyne/filtered_mcp.py`.

## Memory layers (this is how dual memory works)

Three stores, one job each. A fact has one writer of truth. Others may point, never copy as STATED.

| Layer | Store | When it is used | Who writes |
|---|---|---|---|
| **L0 Prompt** | Native Grok Bot memory (`update_state`: agent profile, shared user memory) | Already in the prompt every turn. No tool call. | Grok via persist-bot-instructions. Crew-wide standing rules live here so every bot sees them without a leaky Mnemosyne recall. |
| **L1 Query** | Shared Mnemosyne bank `vishalpunjabi` | Bot must `recall`. Domain history, preferences, episode context. Isolated by `author_id` + `channel_id`. | That bot, stamped. |
| **L2 Live** | Integrations: Todoist, Notion, Gmail, Dropbox/Obsidian, and any future memory product that is an app | Bot must call that connector. Live list/state. | The app. Mnemosyne may store a **pointer** (`EXTERNAL_WRITE` or a STATED “judging lives in Notion”), never a copy of the rows. |

### Recall waterfall (every bot, every question)

1. **Already in the prompt (L0)?** Use it. Highest trust for role and standing rules.
2. **Need live objects (tasks, pages, mail, vault notes)?** Query L2. L2 wins over any L1 copy of the same objects. If Mnemosyne says 3 open tasks and Todoist says 5, Todoist wins.
3. **Need domain history not in L0?** `mnemosyne_recall` (L1), filtered to that bot. Prefer `STATED` over `DERIVED`. Ignore `EXTERNAL_WRITE` unless the question is about that source.
4. **A new memory integration** (mem0, etc.) is L2 unless we explicitly promote it. Do not make it a parallel L1. No two-way sync with Mnemosyne.

Conflict order: L2 live > L0 for objects that app owns; L0 > L1 for standing how-to-behave rules; L1 `STATED` > L1 `DERIVED` > L1 `EXTERNAL_WRITE`. Untrusted tool text never becomes L0 or L1 `STATED`.

## Layout

| What | Where |
|---|---|
| Bank name | `vishalpunjabi` |
| Live sqlite | `/home/box/agent-memory/vishalpunjabi/mnemosyne.db` |
| WAL | same dir — never copy to Dropbox |
| Filtered MCP | `/workspace/mcp/mnemosyne/filtered_mcp.py` (unflipped: live wrappers do not exec it yet) |
| Intended wrapper | `/workspace/mcp/mnemosyne/_wrapper.template.sh` and `wrappers-pending/<Bot>.sh` |
| Live wrappers today | `/workspace/mcp/mnemosyne/<Bot>.sh` — per-bot `DATA_DIR`, stock `mnemosyne mcp` |
| Dropbox snapshots + docs | `/Agents/memory/mnemosyne/` |
| Current snapshot | `mnemosyne-export.json` |
| Staging | `mnemosyne-export-next.json` |
| Dated backup | `mnemosyne-export-YYYY-MM-DD-HHmm.json` (PT) |
| Old per-bot DBs (archive) | `/home/box/agent-memory/<Bot>/mnemosyne.db` |
| Old per-bot snapshots (archive) | `/Agents/<Bot>/memory/` |
| Unit tests | `/workspace/mcp/mnemosyne/tests/test_filtered_mcp.py` |

## Vocabulary

- **Bank** — one named sqlite. Ours is `vishalpunjabi`.
- **author_id** — who wrote the row. Bot display name: `Grok`, `Hacka`, `Nutri`, …
- **author_type** — `human` \| `agent` \| `system`. Bots stamp `agent`. Vishal’s notes are `human`. Cron, backups, sleep stamp `system`.
- **channel_id** — `grokbot:<bot name>` (`grokbot:Grok`).
- **scope** — always `global`. Never `session` (session id is shared; see bites).
- **trust_tier** — injection defense: `STATED` \| `DERIVED` \| `EXTERNAL_WRITE` \| `IMPORTED`.
- **veracity** — claim confidence: `stated` \| `inferred` \| `tool` \| `imported`. Never `unknown`.
- **source** — `user`, `conversation`, `mcp`, `import`, `sleep_consolidation`. Maps to trust_tier if trust_tier is omitted. Set it honestly.
- **canonical** — one current value per `(category, name)` **per sqlite profile, not per author_id**.
- **working memory** — raw rows. Grows until sleep.
- **episodic** — sleep summaries. `DERIVED` + `system`.
- **valid_until** — `YYYY-MM-DD`. Recall drops expired rows.
- **superseded_by** — soft-replace via `invalidate` + `replacement_id`.
- **batch** — one lock for a turn’s writes.
- **sleep** — `mnemosyne_sleep` `all_sessions=true`. Nightly 3:00am PT, all 7 days. Do not `force`.
- **WAL** — one writer. `MNEMOSYNE_BUSY_TIMEOUT_MS=15000`. Alert if `-wal` > 8MB.
- **IMPORTED** — migrated old per-bot rows. Lose to new `STATED`.
- **session id** — stock MCP uses `mcp_<bank>` (usually `mcp_default`). Shared across bots on one sqlite. Isolation is recall kwargs, not session.

## Bites / limitations / considerations

These are why we wrap MCP instead of trusting stock 3.15.1 on a shared bank. Align this list with `filtered_mcp.py`. Do not invent extra wrappers.

### 1. Recall leak (must wrap MCP; do not patch site-packages)

Stock `_handle_recall` creates an instance with env `author_id` but calls `mem.recall()` **without** `author_id` / `channel_id` kwargs. `beam.recall` only applies those filters when the kwargs are passed. Same bank + same MCP session id (`mcp_<bank>`) = every bot sees every row.

**Wrapped** in `filtered_handle_recall`: always pass env `MNEMOSYNE_AUTHOR_ID` + `MNEMOSYNE_CHANNEL_ID` into `mem.recall(...)` unless crew-wide is opted in. Default isolate. Response includes `isolation: {author_id, channel_id, crew_wide}`.

Do not tell bots to pass those fields as the isolation mechanism — Cursor’s schema often hides them. Env identity wins so Cursor-hidden fields cannot leak on recall.

Crew-wide standing rules do **not** use leaky recall. They live in L0 shared user memory.

Crew-wide recall is **opt-in only** (code, not docs folklore):

- env `MNEMOSYNE_RECALL_CREW_WIDE=1` **or**
- tool arg `crew_wide=true`

Either one is enough. There is no `MNEMOSYNE_ALLOW_CREW_WIDE`. Standing crew rules belong in L0, not a wide search.

### 2. Canonical is bank-global

`mnemosyne_remember_canonical` is one `(category, name)` slot per sqlite profile, **not** per `author_id`. Two bots writing `preference` / `store` will clobber.

**Not wrapped.** Policy: canonical is **Vishal’s identity card only** (name, how to address him, stable personal prefs). Crew standing rules stay in **L0 user memory**. Per-bot domain facts stay in **working_memory** with `author_id`. Bots do not write canonical unless recording Vishal’s identity.

### 3. Validate mutate-any (now guarded for STATED)

Stock `mnemosyne_validate` looks up any `working_memory` id and can `attest` / `update` / `invalidate` / `delete` it. `previous_content` is returned. That is a cross-author mutate + content leak.

**Wrapped** in `filtered_handle_validate` for **STATED** `update` / `invalidate` / `delete` only:

- same-bot (`env author_id == row author_id`) allowed
- Vishal allowed: `MNEMOSYNE_AUTHOR_TYPE=human` **or** author_id in `{vishal, vishalpunjabi, vishal punjabi}`
- operator override: `MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1` (documented repair, not bot self-service)
- `attest` remains allowed across bots
- non-STATED rows are not gated by this wrapper
- `bank=surface` (Hermes) is not gated here

There is no `MNEMOSYNE_ALLOW_VALIDATE_ANY`. Grok is not a special mutate override; Grok is an agent like the others unless Vishal’s identity env is set.

Direct tools `mnemosyne_update` / `mnemosyne_forget` / `mnemosyne_invalidate` are **unwrapped** and still mutate by id (see remaining holes).

### 4. Stats leak (wrapped)

Stock `_handle_stats` calls `mem.get_stats()` with no author/channel. Beam stats *can* filter, but the stock handler does not pass identity, so totals include every author on the sqlite.

**Wrapped** in `filtered_handle_stats`: `get_stats(author_id=env, channel_id=env)`. Headline `total_memories` is scoped working+episodic. Response includes `author_id`, `channel_id`, `isolation: author_id+channel_id`.

### 5. Session `mcp_<bank>`

`_create_instance` sets `session_id = session_id or f"mcp_{bank}"`. All MCP connections on a bank share that session. Scope `session` would mix bots.

Wrappers set `MNEMOSYNE_DEFAULT_SCOPE=global`. `filtered_handle_remember` fills `scope` from that env **only when the tool omits scope or sends empty**. If Cursor sends `scope=session`, that still writes session. Bots must pass `scope=global`. Scratchpad is session-scoped and **not wrapped**.

### 6. Cursor hiding identity fields

Remember/recall schemas often omit `author_id` / `author_type` / `channel_id` / `trust_tier`. Writes already stamp via stock `_create_instance` when those args are omitted (`author_id or env`). The leak is recall kwargs, not write stamps.

Stock prefers **tool args over env**. The wrapper does **not** strip a spoofed `author_id` if Cursor ever exposes those fields. Bots must never pass another bot’s `author_id`. Env identity is what filtered recall uses even if the tool call includes something else.

### 7. Busy timeout

`MNEMOSYNE_BUSY_TIMEOUT_MS=15000`. One writer. More than one row in a turn → `mnemosyne_batch`. Alert if `-wal` > 8MB.

### 8. LLM off

`MNEMOSYNE_LLM_ENABLED=false`. No embeddings extras, no extract-via-LLM. Do not turn it on for crew MCP.

### 9. No live sqlite in Dropbox

JSON only under `/Agents/memory/mnemosyne/`. Never upload `.db`, `-wal`, `-shm`.

### 10. No dual-write

Do not write to old per-bot DBs and the shared bank at the same time. Flip all wrappers in one pass after import + smoke.

### 11. Smoke test gate

Do not flip live wrappers until the Grok-vs-Hacka unique-phrase test passes (below). Unit tests: `/workspace/mcp/mnemosyne/tests/test_filtered_mcp.py`.

## Wrapper env (intended after flip)

```
MNEMOSYNE_DATA_DIR=/home/box/agent-memory/vishalpunjabi
MNEMOSYNE_AUTHOR_ID=<Bot>
MNEMOSYNE_AUTHOR_TYPE=agent
MNEMOSYNE_CHANNEL_ID=grokbot:<Bot>
MNEMOSYNE_DEFAULT_SCOPE=global
MNEMOSYNE_BUSY_TIMEOUT_MS=15000
MNEMOSYNE_LLM_ENABLED=false
```

Optional (off unless an operator sets them):

```
MNEMOSYNE_RECALL_CREW_WIDE=1          # opt-in wide recall; standing rules belong in L0
MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1   # operator repair of STATED rows only
```

Cursor remember/recall often omit identity and `trust_tier`. Env stamps writes. Filtered recall injects author+channel kwargs.

## Wrapper and MCP changes (intended code)

Package is `mnemosyne-memory 3.15.1` at `/home/box/.mnemosyne/venv` (**do not patch site-packages**).

`filtered_mcp.py` is the process-local entrypoint: `apply_patches()` replaces `mnemosyne.mcp_tools` handlers in **this process only**, then `mnemosyne.mcp_server.main()` (same argv as `mnemosyne mcp`).

Shebang: `/home/box/.mnemosyne/venv/bin/python`.

### What is actually patched

| Tool | Behavior in `filtered_mcp.py` |
|---|---|
| `mnemosyne_recall` | Passes env `author_id` + `channel_id` into `mem.recall()`. Default isolate. Opt-in wide: `crew_wide=true` **or** `MNEMOSYNE_RECALL_CREW_WIDE=1`. |
| `mnemosyne_remember` | If `scope` is omitted/empty, set from `MNEMOSYNE_DEFAULT_SCOPE` (global). Does **not** set `veracity=stated`. Identity from env via stock `_create_instance` when tool args omit it. |
| `mnemosyne_batch` | Passthrough. Stock already uses `_resolve_default_scope()`. |
| `mnemosyne_stats` | `get_stats(author_id=env, channel_id=env)`. Headline `total_memories` is scoped. |
| `mnemosyne_get` | Other authors’ / other channels’ rows → `not_found`. |
| `mnemosyne_validate` | STATED `update`/`invalidate`/`delete` refused unless same-bot, Vishal, or `MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1`. `attest` still allowed. |

Intended recall filter (actual code):

```python
def _crew_wide_recall(arguments):
    if _truthy_env("MNEMOSYNE_RECALL_CREW_WIDE"):
        return True
    if _truthy_arg(arguments.get("crew_wide")):
        return True
    return False

def _recall_filters(arguments):
    if _crew_wide_recall(arguments):
        return None, None
    author_id, _, channel_id = env_identity()
    return author_id, channel_id
```

Intended STATED mutate gate (actual code):

```python
# STATED mutate is same-bot or Vishal only.
# Override: MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1
# Vishal: author_type == "human" or author_id in {vishal, vishalpunjabi, "vishal punjabi"}
```

### Live wrappers today (UNFLIPPED)

Do **not** copy pending wrappers over these. Isolation today is **per-file sqlite**, not author kwargs.

```
export MNEMOSYNE_DATA_DIR=/home/box/agent-memory/<Bot>
export MNEMOSYNE_LLM_ENABLED=false
exec /home/box/.mnemosyne/venv/bin/mnemosyne mcp "$@"
```

Do not point `DATA_DIR` at the shared bank until flip. After the shared bank exists, this stock leak would let every bot see every row.

### Intended wrapper (NOT live)

Template `_wrapper.template.sh`; unused copies in `wrappers-pending/<Bot>.sh`:

```
export MNEMOSYNE_DATA_DIR=/home/box/agent-memory/vishalpunjabi
export MNEMOSYNE_AUTHOR_ID=<Bot>
export MNEMOSYNE_AUTHOR_TYPE=agent
export MNEMOSYNE_CHANNEL_ID=grokbot:<Bot>
export MNEMOSYNE_DEFAULT_SCOPE=global
export MNEMOSYNE_BUSY_TIMEOUT_MS=15000
export MNEMOSYNE_LLM_ENABLED=false
exec /home/box/.mnemosyne/venv/bin/python /workspace/mcp/mnemosyne/filtered_mcp.py "$@"
```

Copy over live `*.sh` only after import + smoke. Do not flip one bot early.

### Smoke test (do not flip until this passes)

1. Grok, through the **filtered** MCP against the shared bank, writes a unique `STATED` row (distinct phrase, `veracity=stated`, `source=user`).
2. Hacka `mnemosyne_recall` of that exact phrase must return **empty**.
3. Grok `mnemosyne_recall` of that phrase must **find** it.

If step 2 returns Grok’s row, stop. Live wrappers stay unflipped.

Unit stand-in (no network, LLM off, temp sqlite; does not flip anything):

```
/home/box/.mnemosyne/venv/bin/python /workspace/mcp/mnemosyne/tests/test_filtered_mcp.py
```

## Remaining leak holes (documented, not wrapped)

`filtered_mcp.py` does **not** patch these. Treat them as cross-author until a later wrap. Domain bots should not call them.

- **canonical** `remember_canonical` / `recall_canonical`: bank-global `(category, name)` clobber. Policy: Vishal identity card only.
- **graph_query / graph_link**: graph is not author-scoped. Related ids/content can leak.
- **triple_add / triple_query**: triples are not author-scoped.
- **hygiene_audit / hygiene_clean**: whole-DB noise scan / clean. Content of other authors can appear.
- **export**: whole bank. Needed for backup rotate; do not run from domain bots.
- **forget / update / invalidate** (direct tools by id): bypass the STATED validate guard. Can mutate another author’s row if you have the id.
- **scratchpad** read/write/clear: session `mcp_<bank>`, no author column.
- **sleep / sleep_all_sessions**: consolidates the whole bank. Cron/Grok job, not a bot recall path.
- **import / diagnose**: whole-DB. Do not use from domain bots.
- **mnemosyne_shared_***: Hermes shared-surface, **not** the crew bank. Do not use unless Vishal explicitly asks.

## Trust mapping

| Situation | layer | author_type | trust_tier | veracity | source |
|---|---|---|---|---|---|
| Standing how-to-behave rule | L0 user memory | n/a | n/a | n/a | n/a |
| Vishal said a domain fact | L1 | human, or agent recording him | STATED | stated | user or conversation |
| Bot inferred | L1 | agent | DERIVED | inferred | not mcp |
| Tool, email, web, scrape | L1 pointer only, or skip | agent | EXTERNAL_WRITE | tool | mcp |
| Todoist/Notion/Gmail object | L2 live query | n/a | n/a | n/a | n/a |
| Old DB migration | L1 | system | IMPORTED | imported | import |
| Nightly sleep | L1 | system | DERIVED | inferred | sleep_consolidation |

MCP remember defaults to veracity `unknown` if unset. Always set veracity. Batch has no `trust_tier`; set `source` honestly. The wrapper does **not** silently set `veracity=stated`.

## Anti-poisoning, hygiene, WAL, sleep, backups

Write widely / trust narrowly; `valid_until`; invalidate+replace; batch; 15s busy timeout; 8MB WAL alert; sleep 3:00am PT `all_sessions`; Dropbox rotate in `/Agents/memory/mnemosyne/` with 3-day dated backups. See BACKUP.md.

## Cutover

1. Create empty `/home/box/agent-memory/vishalpunjabi/` and confirm Dropbox `/Agents/memory/mnemosyne/` (docs already there).
2. Install the filtered MCP entrypoint (**done**, unflipped). Point wrappers at the shared dir **but do not flip until import+smoke pass**.
3. Import each old `/home/box/agent-memory/<Bot>/mnemosyne.db` as `IMPORTED` / `imported` with that bot’s `author_id` and `channel_id`. On `memory_id` collision, keep both by assigning a new id to the incoming row (do not drop).
4. Smoke test isolation (Grok unique STATED; Hacka empty; Grok finds it).
5. Flip all wrappers in one pass (copy `wrappers-pending/<Bot>.sh` over live `<Bot>.sh`). Brief every bot with BOT-GUIDE.md / skill Mnemosyne bot memory.
6. Switch 11:31 backup to this folder. Add 3:00am sleep. Seed one dated backup.
7. Old DBs and `/Agents/<Bot>/memory/` stay archive. No dual-write window.

## New bot

No new sqlite. Same data dir, identity env, filtered MCP, brief BOT-GUIDE. Standing rules still go to L0 via persist-bot-instructions. Do not create `/Agents/<Name>/memory/` live dump.

## Status

Filtered MCP + unit tests exist. Live wrappers still per-bot stock `mnemosyne mcp`. Shared bank is **not** created, wrappers are **not** rewired, old DBs still live, until Vishal signs off and smoke passes. Do not migrate DBs in this docs pass.

