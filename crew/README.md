# Crew Mnemosyne filtered MCP

Thin in-process monkeypatch around stock `mnemosyne-memory` 3.15.1. Does **not** patch site-packages. Does **not** flip live wrappers until the Grok-vs-Hacka smoke test passes.

## Unflipped (today)

Live `/workspace/mcp/mnemosyne/<Bot>.sh` still:

```sh
export MNEMOSYNE_DATA_DIR=/home/box/agent-memory/<Bot>
export MNEMOSYNE_LLM_ENABLED=false
exec /home/box/.mnemosyne/venv/bin/mnemosyne mcp "$@"
```

Each bot has its own sqlite. Stock `_handle_recall` does not pass `author_id` / `channel_id` into `mem.recall()`, so isolation is “separate files,” not identity filters. After the shared `vishalpunjabi` bank is created, that stock leak would let every bot see every row (`session_id = mcp_<bank>`).

## Flipped (after smoke test)

Point every wrapper at the shared dir **and** this entrypoint. Pending copies live in `wrappers-pending/` (unused until flip). Template: `_wrapper.template.sh`.

```sh
export MNEMOSYNE_DATA_DIR=/home/box/agent-memory/vishalpunjabi
export MNEMOSYNE_AUTHOR_ID=<Bot>
export MNEMOSYNE_AUTHOR_TYPE=agent
export MNEMOSYNE_CHANNEL_ID=grokbot:<Bot>
export MNEMOSYNE_DEFAULT_SCOPE=global
export MNEMOSYNE_BUSY_TIMEOUT_MS=15000
export MNEMOSYNE_LLM_ENABLED=false
exec /home/box/.mnemosyne/venv/bin/python /workspace/mcp/mnemosyne/filtered_mcp.py "$@"
```

`filtered_mcp.py` applies process-local patches then runs `mnemosyne.mcp_server` stdio (same argv as `mnemosyne mcp`).

## Smoke test gate (do not flip until this passes)

1. Grok, through the **filtered** MCP against the shared bank, writes a unique `STATED` row (distinct phrase, `veracity=stated`, `source=user`).
2. Hacka `mnemosyne_recall` of that exact phrase must return **empty**.
3. Grok `mnemosyne_recall` of that phrase must **find** it.

If step 2 returns Grok’s row, stop. Live wrappers stay unflipped.

Unit tests (no network, LLM off, temp sqlite):

```sh
PYTHONPATH=/home/box/.mnemosyne/venv/lib/python3.13/site-packages \
  MNEMOSYNE_LLM_ENABLED=false \
  python3 /workspace/mcp/mnemosyne/tests/test_filtered_mcp.py
```

Prefer the venv interpreter when the environment allows:

```sh
/home/box/.mnemosyne/venv/bin/python /workspace/mcp/mnemosyne/tests/test_filtered_mcp.py
```

## What the patch does

| Tool | Behavior |
|---|---|
| `mnemosyne_recall` | Passes env `author_id` + `channel_id` into `mem.recall()`. Default isolate. Crew-wide standing rules stay in Grok Bot L0. Opt-in wide search: `crew_wide=true` or `MNEMOSYNE_RECALL_CREW_WIDE=1`. |
| `mnemosyne_remember` | Default `scope` from `MNEMOSYNE_DEFAULT_SCOPE` (global). Does **not** set `veracity=stated`. Identity from env via `_create_instance` when tool args omit it. |
| `mnemosyne_batch` | Same scope default (stock already uses `_resolve_default_scope`). |
| `mnemosyne_stats` | Beam working/episodic counts filtered to this author. Headline `total_memories` is scoped. |
| `mnemosyne_get` | Other authors’ rows → `not_found`. |
| `mnemosyne_validate` | `STATED` update/invalidate/delete refused unless same `author_id`, Vishal (`human` / known ids), or `MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1`. `attest` still allowed. |

## Remaining holes (documented, not wrapped)

`graph_query`, `hygiene_audit` / `hygiene_clean`, `export`, `triple_*`, `forget` / `update` / `invalidate` by id, canonical `(category, name)` bank-global clobber, Hermes `mnemosyne_shared_*`. See Dropbox `DESIGN.md`.

## Do not

- Patch `/home/box/.mnemosyne/venv` (read only).
- Flip live wrappers before the smoke test.
- Put live sqlite/WAL in Dropbox.
- Dual-write old per-bot DBs and the shared bank.
