# Backup Mnemosyne to Dropbox

Live copy for Grok: skill Mnemosyne Dropbox backup.

Live sqlite stays on the computer at `/home/box/agent-memory/vishalpunjabi/`. Dropbox holds JSON only in this folder. Other Grok-like bots may also read and write the same current file. Goal: memories are never lost.

Until the shared bank is live, old per-bot folders `/Agents/<Bot>/memory/` are archive only. Do not keep dumping 17 currents. Do not migrate DBs in a docs pass.

Architecture: DESIGN.md. Bot behavior: BOT-GUIDE.md.

## Bites that affect backup

- **No live sqlite in Dropbox.** Never upload `.db`, `-wal`, `-shm`. WAL / multi-writer previously froze a 52MB WAL. JSON only.
- **No dual-write.** After flip, backup the shared bank only. Do not also dump per-bot DBs as “current.” Until flip, do not invent a dual-write to the not-yet-shared path.
- **Export is whole-bank and unwrapped.** `mnemosyne_export` is not author-filtered. `filtered_mcp.py` does **not** wrap export. That is intentional for this rotate (Grok/backup dumps the whole bank). Domain bots must not export.
- **Smoke test gate.** Do not switch the 11:31 job to the shared folder until Grok-vs-Hacka isolation smoke passes (Grok unique STATED; Hacka recall empty; Grok finds it). See DESIGN.md.
- **Busy timeout.** Export with `MNEMOSYNE_BUSY_TIMEOUT_MS=15000` and `MNEMOSYNE_LLM_ENABLED=false`. One writer.
- **LLM off.** Do not enable embeddings extras for export.
- **Canonical clobber** is a data issue, not a backup bug: merge by `memory_id` still keeps both working rows; canonical slots remain one-per-name in the sqlite.
- **Stats/recall leaks** do not change the rotate: export is the whole sqlite. Isolation is an MCP recall problem, not a JSON snapshot problem.
- **Session `mcp_<bank>`** does not belong in Dropbox. Do not export WAL or scratchpad as sqlite.
- **GitHub:** stay on https://github.com/vshalpnjabi/mnemosyne `crew-v3.15.1` / tag `v3.15.1`. Overlay directory: `grokbot/` (not `crew/`). Do not patch the venv to “fix” export.

## Paths (this folder)

- Current: `/Agents/memory/mnemosyne/mnemosyne-export.json`
- Next (staging): `/Agents/memory/mnemosyne/mnemosyne-export-next.json`
- Latest backup: `/Agents/memory/mnemosyne/mnemosyne-export-YYYY-MM-DD-HHmm.json` (PT)

Docs in this folder: `DESIGN.md`, `BOT-GUIDE.md`, `BACKUP.md`. They are not the export. Local mirrors: `/workspace/mcp/mnemosyne/docs/`.

Do not upload sqlite, WAL, or shm. JSON only. Dropbox `create_file` is UTF-8 text (5 MB). If a full export is too large, write slim `working_memory` plus `canonical_facts`. `create_file` fails if the path exists: write **next**, confirm, then rename. Never overwrite current in place.

## Rotate (this order)

1. Read the latest current file if it exists. Treat it as possibly written by another Grok-like bot. If missing, start from empty.
2. Export the shared bank sqlite (`MNEMOSYNE_DATA_DIR=/home/box/agent-memory/vishalpunjabi`, LLM extras off). Until cutover this path may not exist — do not invent a dual-write to per-bot DBs.
3. Merge by `memory_id`: keep Dropbox-only, add local-only, same id keeps the newer timestamp. Never drop a current-file memory just because it is missing locally.
4. Write staging `mnemosyne-export-next.json`. If leftover next exists, delete it first, then create. Never write the merged payload onto the current filename in this step.
5. Confirm next exists and size > 0. If not, stop. Leave current and backups untouched.
6. If current exists, rename it to `mnemosyne-export-YYYY-MM-DD-HHmm.json`. Never delete current.
7. Rename next to `mnemosyne-export.json`.
8. Prune dated backups older than 3 calendar days. Keep current. Never prune current. Keep backups from today and the previous 2 days.

## Seeding when next is missing

If current exists and there is no next file, copy current to the dated backup name and leave current in place. Do not move current away unless next is confirmed.

## Rules

- Never overwrite current in place.
- Never delete current. Retire it only by renaming it to the latest dated backup, then renaming next to current.
- Never delete a backup until it is older than 3 days.
- Never skip the read/merge.
- Look up Dropbox and Mnemosyne tools each run. Do not assume old argument names.
- Stay quiet on success. If the rotate fails, say which step and leave files recoverable.

## New bot

Do not create `/Agents/<Name>/memory/` for live dumps. This shared snapshot folder is enough. Isolation is `author_id` / `channel_id` inside the bank. See DESIGN.md.

