#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${CONTITEXT_INSTALL_PYTHON:-python3}" "$SCRIPT_DIR/install_agent_adapters.py" "$@"
