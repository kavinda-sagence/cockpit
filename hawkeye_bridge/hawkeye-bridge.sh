#!/bin/bash
set -e

SCRIPT_PATH=$(realpath "$(dirname "${BASH_SOURCE[0]}")")

source ~/anaconda3/etc/profile.d/conda.sh
conda activate `whoami`_ai_runtime_env

python3 "$SCRIPT_PATH/hawkeye-bridge.py"
