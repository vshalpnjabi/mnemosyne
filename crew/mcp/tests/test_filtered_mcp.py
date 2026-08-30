"""Isolation and default tests for filtered_mcp.py.

Drive stock mnemosyne.mcp_tools through the same monkeypatches the MCP
entrypoint applies. No network. LLM off. Does not edit the venv.
"""

from __future__ import annotations

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
import mnemosyne.mcp_tools as mcp_tools  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
