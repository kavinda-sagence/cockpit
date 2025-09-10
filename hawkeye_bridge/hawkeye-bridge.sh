#!/bin/bash
set -e

SCRIPT_PATH=$(realpath "$(dirname "${BASH_SOURCE[0]}")")

source "$SCRIPT_PATH/init_env.sh"

python3 "$SCRIPT_PATH/hawkeye-bridge.py"
