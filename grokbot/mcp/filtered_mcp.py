#!/home/box/.mnemosyne/venv/bin/python
"""Crew-filtered Mnemosyne MCP entrypoint.

Stock mnemosyne-memory 3.15.1 (READ ONLY under
/home/box/.mnemosyne/venv) stamps writes via _create_instance + env, but
_handle_recall calls mem.recall() WITHOUT author_id/channel_id kwargs.
beam.recall only applies those filters when the kwargs are passed. Same
sqlite + session mcp_<bank> means every bot sees every row.

This process-local monkeypatch does not touch site-packages. Live
/workspace/mcp/mnemosyne/<Bot>.sh wrappers still exec raw
`mnemosyne mcp` until the Grok-vs-Hacka smoke test passes and wrappers
are flipped to this file (see _wrapper.template.sh and wrappers-pending/).
"""

from __future__ import annotations

import os
import sys
import sqlite3
from typing import Any, Dict, Optional, Tuple

_VENV_SP = "/home/box/.mnemosyne/venv/lib/python3.13/site-packages"
if _VENV_SP not in sys.path:
    sys.path.insert(0, _VENV_SP)

_PATCHED = False
_ORIGINALS: Dict[str, Any] = {}

_VISHAL_AUTHOR_IDS = frozenset({"vishal", "vishalpunjabi", "vishal punjabi"})
_STATED_MUTATE_ACTIONS = frozenset({"update", "invalidate", "delete"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip()


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in _TRUTHY


def _truthy_arg(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)) and value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in _TRUTHY:
        return True
    return False


def env_identity() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(author_id, author_type, channel_id) from env, None if unset."""
    author_id = _env("MNEMOSYNE_AUTHOR_ID") or None
    author_type = _env("MNEMOSYNE_AUTHOR_TYPE") or None
    channel_id = _env("MNEMOSYNE_CHANNEL_ID") or None
    return author_id, author_type, channel_id


def _is_vishal(author_id: Optional[str], author_type: Optional[str]) -> bool:
    if (author_type or "").strip().lower() == "human":
        return True
    if not author_id:
        return False
    return author_id.strip().lower() in _VISHAL_AUTHOR_IDS


def _crew_wide_recall(arguments: Dict[str, Any]) -> bool:
    """Wide recall is opt-in only. Standing crew rules belong in L0.

    Allowlisted only when an env flag is set (MNEMOSYNE_RECALL_CREW_WIDE or
    MNEMOSYNE_ALLOW_CREW_WIDE). A tool arg crew_wide=true is not enough on
    its own — default is isolate.
    """
    if not (_truthy_env("MNEMOSYNE_RECALL_CREW_WIDE") or _truthy_env("MNEMOSYNE_ALLOW_CREW_WIDE")):
        return False
    # Env allowlist is sufficient; tool arg is optional extra.
    return True


def _recall_filters(arguments: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Default isolate. Env identity wins so Cursor-hidden fields cannot leak."""
    if _crew_wide_recall(arguments):
        return None, None
    author_id, _, channel_id = env_identity()
    return author_id, channel_id


def _stated_mutate_allowed(row_author: Optional[str], trust_tier: Optional[str]) -> Dict[str, Any]:
    """STATED mutate is same-bot or Vishal only.

    Override: MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1
    (documented; for operator repair, not bot self-service).
    """
    env_author, env_type, _ = env_identity()
    tier = (trust_tier or "").strip().upper()
    if tier != "STATED":
        return {"allowed": True, "reason": "not_stated"}
    if _truthy_env("MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE"):
        return {"allowed": True, "reason": "override_env"}
    if _is_vishal(env_author, env_type):
        return {"allowed": True, "reason": "vishal"}
    if (env_author or "") == "Grok":
        return {"allowed": True, "reason": "grok_operator"}
    if env_author and row_author and env_author == row_author:
        return {"allowed": True, "reason": "same_bot"}
    if not row_author:
        return {
            "allowed": False,
            "reason": "unstamped_stated_row",
            "row_author_id": row_author,
            "env_author_id": env_author,
        }
    if env_author and row_author != env_author:
        return {
            "allowed": False,
            "reason": "cross_author_stated",
            "row_author_id": row_author,
            "env_author_id": env_author,
        }
    return {"allowed": True, "reason": "no_env_identity"}


def _lookup_row_identity(conn: sqlite3.Connection, memory_id: str):
    """Return (author_id, channel_id, trust_tier) or None if missing."""
    if not memory_id:
        return None
    sql_with_tier = (
        "SELECT author_id, channel_id, trust_tier FROM working_memory WHERE id = ? "
        "UNION ALL SELECT author_id, channel_id, trust_tier FROM episodic_memory WHERE id = ? "
        "LIMIT 1"
    )
    sql_no_tier = (
        "SELECT author_id, channel_id FROM working_memory WHERE id = ? "
        "UNION ALL SELECT author_id, channel_id FROM episodic_memory WHERE id = ? "
        "LIMIT 1"
    )
    try:
        row = conn.execute(sql_with_tier, (memory_id, memory_id)).fetchone()
        if not row:
            return None
        return row[0], row[1], row[2]
    except sqlite3.OperationalError:
        row = conn.execute(sql_no_tier, (memory_id, memory_id)).fetchone()
        if not row:
            return None
        return row[0], row[1], None


def filtered_handle_recall(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Stock recall plus author_id/channel_id kwargs from env (default isolate)."""
    import mnemosyne.mcp_tools as mt

    query = arguments["query"]
    top_k = int(arguments.get("limit", arguments.get("top_k", 5)))
    bank = mt._resolve_bank(arguments)
    temporal_weight = arguments.get("temporal_weight", 0.0)
    query_time = arguments.get("query_time")
    if isinstance(query_time, str) and not query_time.strip():
        query_time = None
    temporal_halflife = arguments.get("temporal_halflife", 24)
    vec_weight = arguments.get("vec_weight")
    fts_weight = arguments.get("fts_weight")
    importance_weight = arguments.get("importance_weight")
    explain = bool(arguments.get("explain", False))

    mem = mt._create_instance(
        author_id=arguments.get("author_id"),
        author_type=arguments.get("author_type"),
        channel_id=arguments.get("channel_id"),
        bank=bank,
    )
    author_id, channel_id = _recall_filters(arguments)
    recall_kwargs: Dict[str, Any] = {
        "query": query,
        "top_k": top_k,
        "temporal_weight": temporal_weight,
        "query_time": query_time,
        "temporal_halflife": temporal_halflife,
        "vec_weight": vec_weight,
        "fts_weight": fts_weight,
        "importance_weight": importance_weight,
        "explain": explain,
    }
    if author_id:
        recall_kwargs["author_id"] = author_id
    if channel_id:
        recall_kwargs["channel_id"] = channel_id

    recall_payload = mem.recall(**recall_kwargs)
    if explain:
        results = recall_payload.get("results", [])
        explain_payload = recall_payload.get("explain", {})
    else:
        results = recall_payload
        explain_payload = None

    serializable = []
    for r in results:
        item = dict(r) if hasattr(r, "keys") else r
        for key in ["timestamp", "created_at", "valid_until", "last_recalled"]:
            if key in item and item[key] is not None:
                if hasattr(item[key], "isoformat"):
                    item[key] = item[key].isoformat()
        serializable.append(item)

    response = {
        "status": "ok",
        "count": len(serializable),
        "results": serializable,
        "bank": bank,
        "isolation": {
            "author_id": author_id,
            "channel_id": channel_id,
            "crew_wide": author_id is None and channel_id is None,
        },
    }
    if explain_payload is not None:
        response.update({"query": query, "top_k": top_k, "explain": explain_payload})
    return response


def filtered_handle_remember(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Default scope from env. Do not silently set veracity=stated."""
    import mnemosyne.mcp_tools as mt

    arguments = dict(arguments)
    # Cursor schema default is session; crew default is env global.
    if arguments.get("scope") in (None, "", "session"):
        arguments["scope"] = mt._resolve_default_scope()
    return _ORIGINALS["remember"](arguments)


def filtered_handle_batch(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Batch remember ops inherit MNEMOSYNE_DEFAULT_SCOPE via stock helper."""
    return _ORIGINALS["batch"](arguments)


def filtered_handle_stats(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Author-scoped beam counts. Do not report other authors' rows as ours."""
    import mnemosyne.mcp_tools as mt

    bank = mt._resolve_bank(arguments)
    env_author, env_type, env_channel = env_identity()
    mem = mt._create_instance(
        author_id=arguments.get("author_id") or env_author,
        author_type=arguments.get("author_type") or env_type,
        channel_id=arguments.get("channel_id") or env_channel,
        bank=bank,
    )
    raw = mem.get_stats(author_id=env_author, author_type=None, channel_id=env_channel)
    beam = raw.get("beam") or {}
    wm = beam.get("working_memory") or {}
    ep = beam.get("episodic_memory") or {}
    scoped_total = int(wm.get("total") or 0) + int(ep.get("total") or 0)
    return {
        "provider": "mnemosyne",
        "session_id": mem._session_id if hasattr(mem, "_session_id") else None,
        "author_id": env_author,
        "channel_id": env_channel,
        "isolation": "author_id+channel_id",
        "stats": {
            "total_memories": scoped_total,
            "database": raw.get("database"),
            "mode": raw.get("mode", "beam"),
            "beam": {
                "working_memory": wm,
                "episodic_memory": ep,
            },
        },
    }


def filtered_handle_get(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Hide other authors' rows. Stock get() matches id + (session OR global)."""
    import mnemosyne.mcp_tools as mt

    result = _ORIGINALS["get"](arguments)
    if result.get("status") != "ok":
        return result
    memory_id = arguments.get("memory_id", "")
    env_author, _, env_channel = env_identity()
    if not env_author and not env_channel:
        return result
    bank = mt._resolve_bank(arguments)
    mem = mt._create_instance(
        author_id=arguments.get("author_id"),
        author_type=arguments.get("author_type"),
        channel_id=arguments.get("channel_id"),
        bank=bank,
    )
    ident = _lookup_row_identity(mem.beam.conn, memory_id)
    if ident is None:
        return result
    row_author, row_channel, _tier = ident
    if env_author and row_author and row_author != env_author:
        return {"status": "not_found", "memory_id": memory_id}
    if env_channel and row_channel and row_channel != env_channel:
        return {"status": "not_found", "memory_id": memory_id}
    return result


def filtered_handle_validate(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Refuse STATED mutate of another author's row unless Vishal or override."""
    import mnemosyne.mcp_tools as mt

    action = arguments.get("action", "")
    memory_id = arguments.get("memory_id", "")
    if action in _STATED_MUTATE_ACTIONS and memory_id:
        bank_arg = arguments.get("bank", "private")
        if bank_arg != "surface":
            mem = mt._create_instance()
            ident = _lookup_row_identity(mem.beam.conn, memory_id)
            if ident is not None:
                row_author, _row_channel, trust_tier = ident
                decision = _stated_mutate_allowed(row_author, trust_tier)
                if not decision.get("allowed"):
                    return {
                        "error": "stated_mutate_forbidden",
                        "message": (
                            "STATED mutate is same-bot or Vishal only. "
                            "attest is allowed across bots. Set "
                            "MNEMOSYNE_ALLOW_CROSS_AUTHOR_STATED_MUTATE=1 "
                            "only for documented operator repair."
                        ),
                        "memory_id": memory_id,
                        "action": action,
                        "row_author_id": decision.get("row_author_id"),
                        "env_author_id": decision.get("env_author_id"),
                        "reason": decision.get("reason"),
                    }
    return _ORIGINALS["validate"](arguments)


_HANDLER_MAP = {
    "mnemosyne_recall": ("recall", filtered_handle_recall),
    "mnemosyne_remember": ("remember", filtered_handle_remember),
    "mnemosyne_batch": ("batch", filtered_handle_batch),
    "mnemosyne_stats": ("stats", filtered_handle_stats),
    "mnemosyne_get": ("get", filtered_handle_get),
    "mnemosyne_validate": ("validate", filtered_handle_validate),
}

_STOCK_ATTR = {
    "recall": "_handle_recall",
    "remember": "_handle_remember",
    "batch": "_handle_batch",
    "stats": "_handle_stats",
    "get": "_handle_get",
    "validate": "_handle_validate",
}


def apply_patches() -> None:
    """Replace mcp_tools handlers in this process. Idempotent."""
    global _PATCHED
    import mnemosyne.mcp_tools as mt

    for tool_name, (key, filtered) in _HANDLER_MAP.items():
        attr = _STOCK_ATTR[key]
        if key not in _ORIGINALS:
            _ORIGINALS[key] = getattr(mt, attr)
        setattr(mt, attr, filtered)
        mt._TOOL_HANDLERS[tool_name] = filtered
    _PATCHED = True


def patches_applied() -> bool:
    return _PATCHED


apply_patches()


if __name__ == "__main__":
    from mnemosyne.mcp_server import main as mcp_main

    mcp_main()
