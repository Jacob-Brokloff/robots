#!/usr/bin/env bash
# Train pi0.5 LoRA on the pod (CP13), in the background, logging to /workspace/train.log.
#   DATASET_REPO_ID=Jacob-Brokloff/xlerobot_<task> HUB_MODEL_ID=Jacob-Brokloff/pi05_xlerobot_<task> \
#     bash /workspace/robots/deploy/runpod/train.sh [--check | --fix-quantiles]
# POLICY_TYPE=smolvla for the fallback; STEPS / BATCH_SIZE / LORA_R as in scripts/train_pi05.py.
# Bills $0.60/hr while the pod runs: stop it in the RunPod console when the run ends.
set -euo pipefail
WS="${WS:-/workspace}"
source "$WS/strands.env"
[ -f "$WS/secrets.env" ] && source "$WS/secrets.env"
: "${DATASET_REPO_ID:?set DATASET_REPO_ID}"
cd "$WS/robots/scripts"
if [ "${1:-}" = "--check" ]; then exec python train_pi05.py --check; fi
nohup python train_pi05.py "$@" >"$WS/train.log" 2>&1 &
echo "training (pid $!): tail -f $WS/train.log"
