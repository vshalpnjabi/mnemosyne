"""Isolation and default tests for filtered_mcp.py.

Drive stock mnemosyne.mcp_tools through the same monkeypatches the MCP
entrypoint applies. No network. LLM off. Does not edit the venv.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# LLM extras off before any mnemosyne import.
os.environ["MNEMOSYNE_LLM_ENABLED"] = "false"
os.environ.setdefault("MNEMOSYNE_BUSY_TIMEOUT_MS", "15000")
os.environ.setdefault("MNEMOSYNE_DEFAULT_SCOPE", "global")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import filtered_mcp  # noqa: E402  (patches mcp_tools on import)
import full_export  # noqa: E402
import mnemosyne.mcp_tools as mcp_tools  # noqa: E402

_ISOLATION_COLS = ("author_id", "author_type", "channel_id", "trust_tier")


PHRASE_A = "zx9q7f3a purple durian espresso is Grok isolation canary beverage"
PHRASE_B = "qm4w2c8n indigo jackfruit cortado is Hacka isolation canary beverage"


def _set_author(name: str) -> None:
    os.environ["MNEMOSYNE_AUTHOR_ID"] = name
    os.environ["MNEMOSYNE_AUTHOR_TYPE"] = "agent"
    os.environ["MNEMOSYNE_CHANNEL_ID"] = f"grokbot:{name}"
    os.environ["MNEMOSYNE_DEFAULT_SCOPE"] = "global"
    os.environ["MNEMOSYNE_LLM_ENABLED"] = "false"
    os.environ.pop("MNEMOSYNE_RECALL_CREW_WIDE", None)
    os.environ.pop("MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE", None)


def _db_path() -> Path:
    data_dir = Path(os.environ["MNEMOSYNE_DATA_DIR"])
    return data_dir / "mnemosyne.db"


def _fetch_row(memory_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, content, scope, veracity, author_id, channel_id, trust_tier "
            "FROM working_memory WHERE id = ?",
            (memory_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_episodic(
    memory_id: str,
    *,
    author_id: str,
    channel_id: str,
    trust_tier: str = "DERIVED",
    blob: bytes = b"\x00\x01\xff",
) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO episodic_memory ("
            "id, content, source, timestamp, session_id, importance, "
            "scope, author_id, author_type, channel_id, trust_tier, "
            "veracity, binary_vector"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                "episodic isolation canary for full-column export",
                "sleep_consolidation",
                "2026-08-31T00:00:00",
                "mcp_default",
                0.6,
                "global",
                author_id,
                "agent",
                channel_id,
                trust_tier,
                "inferred",
                blob,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class FilteredMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="mnemo-filtered-")
        os.environ["MNEMOSYNE_DATA_DIR"] = self._tmpdir.name
        os.environ["MNEMOSYNE_LLM_ENABLED"] = "false"
        os.environ["MNEMOSYNE_DEFAULT_SCOPE"] = "global"
        os.environ["MNEMOSYNE_BUSY_TIMEOUT_MS"] = "15000"
        filtered_mcp.apply_patches()
        self.assertTrue(filtered_mcp.patches_applied())
        self.assertIs(
            mcp_tools._TOOL_HANDLERS["mnemosyne_recall"],
            filtered_mcp.filtered_handle_recall,
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_isolation_two_authors_one_sqlite(self) -> None:
        _set_author("Grok")
        stored = mcp_tools._handle_remember(
            {
                "content": PHRASE_A,
                "source": "user",
                "veracity": "stated",
                "importance": 0.9,
            }
        )
        self.assertEqual(stored.get("status"), "stored", stored)
        self.assertTrue(stored.get("memory_id"), stored)

        _set_author("Hacka")
        hacka = mcp_tools._handle_recall({"query": PHRASE_A, "limit": 10})
        self.assertEqual(hacka.get("status"), "ok", hacka)
        blob = " ".join(
            str(r.get("content", "")) for r in hacka.get("results") or []
        )
        self.assertNotIn(
            "zx9q7f3a",
            blob.lower(),
            f"Hacka must not see Grok's phrase: {hacka}",
        )
        self.assertEqual(
            hacka.get("count"),
            0,
            f"Hacka recall of Grok phrase should be empty: {hacka}",
        )

        _set_author("Grok")
        grok = mcp_tools._handle_recall({"query": PHRASE_A, "limit": 10})
        self.assertEqual(grok.get("status"), "ok", grok)
        grok_blob = " ".join(
            str(r.get("content", "")) for r in grok.get("results") or []
        )
        self.assertIn("zx9q7f3a", grok_blob.lower(), f"Grok must find own phrase: {grok}")
        self.assertGreaterEqual(grok.get("count"), 1, grok)

    def test_remember_defaults_scope_global_not_stated_veracity(self) -> None:
        _set_author("Grok")
        stored = mcp_tools._handle_remember(
            {
                "content": (
                    "Standing note about the isolation test workspace "
                    "qm8p3 isolation-default-scope-check"
                ),
                "source": "conversation",
            }
        )
        self.assertEqual(stored.get("status"), "stored", stored)
        row = _fetch_row(stored["memory_id"])
        self.assertIsNotNone(row, "remembered row missing from sqlite")
        self.assertEqual(row["scope"], "global")
        self.assertNotEqual(
            (row["veracity"] or "").lower(),
            "stated",
            f"must not silently set veracity=stated; got {row['veracity']!r}",
        )
        self.assertEqual(row["author_id"], "Grok")
        self.assertEqual(row["channel_id"], "grokbot:Grok")

    def test_stats_does_not_count_other_author_as_this_author(self) -> None:
        _set_author("Grok")
        a = mcp_tools._handle_remember(
            {
                "content": PHRASE_A,
                "source": "user",
                "veracity": "stated",
            }
        )
        self.assertEqual(a.get("status"), "stored", a)

        _set_author("Hacka")
        b = mcp_tools._handle_remember(
            {
                "content": PHRASE_B,
                "source": "user",
                "veracity": "stated",
            }
        )
        self.assertEqual(b.get("status"), "stored", b)

        _set_author("Grok")
        grok_stats = mcp_tools._handle_stats({})
        wm = (
            (grok_stats.get("stats") or {})
            .get("beam", {})
            .get("working_memory", {})
        )
        grok_total = int(wm.get("total") or grok_stats.get("stats", {}).get("total_memories") or -1)
        self.assertEqual(
            grok_stats.get("author_id"),
            "Grok",
            grok_stats,
        )
        self.assertEqual(
            grok_total,
            1,
            f"Grok stats must not include Hacka's row: {grok_stats}",
        )

        _set_author("Hacka")
        hacka_stats = mcp_tools._handle_stats({})
        hacka_wm = (
            (hacka_stats.get("stats") or {})
            .get("beam", {})
            .get("working_memory", {})
        )
        hacka_total = int(
            hacka_wm.get("total")
            or hacka_stats.get("stats", {}).get("total_memories")
            or -1
        )
        self.assertEqual(hacka_total, 1, f"Hacka stats leaked Grok: {hacka_stats}")

    def test_export_json_rows_match_all_sqlite_columns(self) -> None:
        """mnemosyne_export working/episodic rows include every sqlite column."""
        _set_author("Grok")
        stored = mcp_tools._handle_remember(
            {
                "content": PHRASE_A,
                "source": "user",
                "veracity": "stated",
                "importance": 0.9,
            }
        )
        self.assertEqual(stored.get("status"), "stored", stored)
        working_id = stored["memory_id"]
        episodic_id = "ep-full-column-export-canary"
        _insert_episodic(
            episodic_id,
            author_id="Grok",
            channel_id="grokbot:Grok",
            trust_tier="DERIVED",
        )

        self.assertIs(
            mcp_tools._TOOL_HANDLERS["mnemosyne_export"],
            filtered_mcp.filtered_handle_export,
        )

        export_path = Path(self._tmpdir.name) / "full-export.json"
        result = mcp_tools._handle_export({"output_path": str(export_path)})
        self.assertNotIn("error", result, result)
        self.assertEqual(result.get("status"), "exported", result)
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        self.assertTrue(
            (payload.get("mnemosyne_export") or {}).get("crew_full_columns"),
            payload.get("mnemosyne_export"),
        )

        conn = _connect()
        try:
            for table, expected_id in (
                ("working_memory", working_id),
                ("episodic_memory", episodic_id),
            ):
                columns = full_export.table_column_names(conn, table)
                for required in _ISOLATION_COLS:
                    self.assertIn(required, columns, f"{table} schema missing {required}")
                sqlite_row = conn.execute(
                    f"SELECT * FROM {table} WHERE id = ?",
                    (expected_id,),
                ).fetchone()
                self.assertIsNotNone(sqlite_row, f"{table} missing {expected_id}")
                export_rows = {
                    row.get("id"): row for row in payload.get(table) or []
                }
                self.assertIn(expected_id, export_rows, f"{table} absent from export")
                export_row = export_rows[expected_id]
                for column in columns:
                    self.assertIn(
                        column,
                        export_row,
                        f"{table} export dropped {column}: {sorted(export_row)}",
                    )
                mismatches = full_export.sqlite_row_matches_export(
                    sqlite_row, export_row, columns
                )
                self.assertEqual(
                    mismatches,
                    [],
                    f"{table} sqlite/export mismatch on {mismatches}: "
                    f"sqlite={[ (c, sqlite_row[c]) for c in mismatches ]} "
                    f"export={[ (c, export_row.get(c)) for c in mismatches ]}",
                )
                self.assertEqual(export_row["author_id"], "Grok")
                self.assertEqual(export_row["author_type"], "agent")
                self.assertEqual(export_row["channel_id"], "grokbot:Grok")
        finally:
            conn.close()

        working_row = next(
            row for row in payload["working_memory"] if row["id"] == working_id
        )
        self.assertTrue(working_row.get("trust_tier"), working_row)
        episodic_row = next(
            row for row in payload["episodic_memory"] if row["id"] == episodic_id
        )
        self.assertEqual(episodic_row["trust_tier"], "DERIVED")
        self.assertEqual(episodic_row["binary_vector"], [0, 1, 255])

    def test_stock_export_omits_isolation_columns(self) -> None:
        """Document the 3.15.1 allowlist hole the wrap exists to close."""
        _set_author("Grok")
        stored = mcp_tools._handle_remember(
            {
                "content": PHRASE_A,
                "source": "user",
                "veracity": "stated",
            }
        )
        self.assertEqual(stored.get("status"), "stored", stored)
        stock_path = Path(self._tmpdir.name) / "stock-export.json"
        stock = filtered_mcp._ORIGINALS["export"]({"output_path": str(stock_path)})
        self.assertNotIn("error", stock, stock)
        payload = json.loads(stock_path.read_text(encoding="utf-8"))
        stock_row = next(
            row
            for row in payload.get("working_memory") or []
            if row.get("id") == stored["memory_id"]
        )
        omitted = [col for col in _ISOLATION_COLS if col not in stock_row]
        self.assertEqual(
            omitted,
            list(_ISOLATION_COLS),
            f"stock 3.15.1 export was expected to omit isolation cols; "
            f"got keys {sorted(stock_row)}",
        )


if __name__ == "__main__":
    unittest.main()
