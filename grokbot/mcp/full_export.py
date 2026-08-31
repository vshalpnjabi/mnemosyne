"""Full-column working/episodic dump for crew MCP export.

Stock mnemosyne-memory 3.15.1 ``beam.export_to_dict()`` SELECTs a short
allowlist and drops isolation fields (author_id, author_type, channel_id,
trust_tier) plus other schema columns. Grok's direct sqlite-to-Dropbox
path already dumps every column as v2 JSON. This helper rewrites the
stock MCP export file so ``working_memory`` and ``episodic_memory``
arrays are ``SELECT *`` snapshots that match sqlite.

Does not patch site-packages. Does not author-filter the bank.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Union

PathLike = Union[str, Path]

_MEMORY_TABLES = frozenset({"working_memory", "episodic_memory"})


def jsonable_cell(value: Any) -> Any:
    """Make one sqlite cell JSON-serializable without losing bytes."""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return list(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def table_column_names(conn: sqlite3.Connection, table: str) -> List[str]:
    """Return sqlite column names in schema order."""
    if table not in _MEMORY_TABLES:
        raise ValueError(f"refusing to inspect non-memory table: {table}")
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names: List[str] = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            names.append(str(row["name"]))
        else:
            names.append(str(row[1]))
    return names


def _row_as_dict(cursor: sqlite3.Cursor, row: Any) -> Dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        mapping: Mapping[str, Any] = dict(row)
    elif isinstance(row, Mapping):
        mapping = dict(row)
    else:
        names = [desc[0] for desc in (cursor.description or ())]
        mapping = dict(zip(names, row))
    return {key: jsonable_cell(val) for key, val in mapping.items()}


def dump_table_rows(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    """``SELECT *`` every current column. Order matches stock export when possible."""
    if table not in _MEMORY_TABLES:
        raise ValueError(f"refusing to dump non-memory table: {table}")
    columns = table_column_names(conn, table)
    order_sql = ""
    if "session_id" in columns and "timestamp" in columns:
        order_sql = " ORDER BY session_id, timestamp"
    cursor = conn.execute(f"SELECT * FROM {table}{order_sql}")
    return [_row_as_dict(cursor, row) for row in cursor.fetchall()]


def rewrite_export_memory_tables(db_path: PathLike, output_path: PathLike) -> None:
    """Replace working/episodic arrays in a stock export JSON with SELECT * rows."""
    export_path = Path(output_path)
    if not export_path.is_file():
        raise FileNotFoundError(f"export JSON missing: {export_path}")
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("export JSON must be an object")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        payload["working_memory"] = dump_table_rows(conn, "working_memory")
        payload["episodic_memory"] = dump_table_rows(conn, "episodic_memory")
    finally:
        conn.close()

    meta = payload.get("mnemosyne_export")
    if isinstance(meta, dict):
        meta["crew_full_columns"] = True

    export_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def sqlite_row_matches_export(
    sqlite_row: Mapping[str, Any],
    export_row: Mapping[str, Any],
    columns: Sequence[str],
) -> List[str]:
    """Return column names whose export value does not match sqlite."""
    mismatches: List[str] = []
    for column in columns:
        if column not in export_row:
            mismatches.append(column)
            continue
        if jsonable_cell(sqlite_row[column]) != export_row[column]:
            mismatches.append(column)
    return mismatches
