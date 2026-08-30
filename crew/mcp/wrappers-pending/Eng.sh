#!/bin/sh
export MNEMOSYNE_DATA_DIR=/home/box/agent-memory/vishalpunjabi
export MNEMOSYNE_AUTHOR_ID=Eng
export MNEMOSYNE_AUTHOR_TYPE=agent
export MNEMOSYNE_CHANNEL_ID=grokbot:Eng
export MNEMOSYNE_DEFAULT_SCOPE=global
export MNEMOSYNE_BUSY_TIMEOUT_MS=15000
export MNEMOSYNE_LLM_ENABLED=false
exec /home/box/.mnemosyne/venv/bin/python /workspace/mcp/mnemosyne/filtered_mcp.py "$@"
