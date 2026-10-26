#!/usr/bin/env bash
# RunPod pod setup for phase 2 (CP13/CP14): everything lives on the network volume at /workspace, so a
# stopped pod keeps its install. Run on the pod (as root):
#   curl -LsSf https://raw.githubusercontent.com/Jacob-Brokloff/robots/main/deploy/runpod/bootstrap.sh | bash
#   # or: git clone https://github.com/Jacob-Brokloff/robots /workspace/robots && bash /workspace/robots/deploy/runpod/bootstrap.sh
# Idempotent. Starts tailscaled (userspace networking: no TUN in a pod) but does not log in; it prints the
# `tailscale up` command, whose login URL Jacob approves (CP7). Then: deploy/runpod/train.sh, serve_policy.sh.
set -euo pipefail

WS="${WS:-/workspace}"
REPO_URL="${REPO_URL:-https://github.com/Jacob-Brokloff/robots.git}"
REPO="$WS/robots"
VENV="$WS/strands-venv"
TS_DIR="$WS/tailscale"
TS_VERSION="${TS_VERSION:-1.104.2}"
export HF_HOME="$WS/hf"

command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
export PATH="$HOME/.local/bin:$PATH"

[ -d "$REPO/.git" ] || git clone "$REPO_URL" "$REPO"
git -C "$REPO" pull --ff-only

# CUDA torch (A40). strands-robots needs Python >= 3.12; lerobot[pi] = pi0.5, [smolvla] = the fallback.
[ -d "$VENV" ] || uv venv --python 3.12 "$VENV"
VIRTUAL_ENV="$VENV" UV_TORCH_BACKEND=auto uv pip install -e "$REPO[lerobot,inference]" \
  "lerobot[pi,smolvla,peft,training]>=0.6.1,<0.7.0"

# Tailscale, userspace networking. Inbound tailnet connections are handed to local listeners, so the
# policy server binds 127.0.0.1 here (no tailnet interface exists in this mode).
if [ ! -x "$TS_DIR/tailscaled" ]; then
  mkdir -p "$TS_DIR"
  curl -fsSL "https://pkgs.tailscale.com/stable/tailscale_${TS_VERSION}_amd64.tgz" | tar -xz -C "$TS_DIR" --strip-components=1
fi
TS="$TS_DIR/tailscale --socket=$TS_DIR/tailscaled.sock"
if ! $TS status >/dev/null 2>&1 && ! pgrep -f "$TS_DIR/tailscaled" >/dev/null; then
  nohup "$TS_DIR/tailscaled" --tun=userspace-networking --state="$TS_DIR/tailscaled.state" \
    --socket="$TS_DIR/tailscaled.sock" >"$TS_DIR/tailscaled.log" 2>&1 &
  sleep 2
fi

cat > "$WS/strands.env" <<ENV
export PATH="$VENV/bin:\$PATH"
export HF_HOME="$HF_HOME"
export TS="$TS"
ENV
cat <<MSG
Installed: venv $VENV, repo $REPO, HF cache $HF_HOME. Source $WS/strands.env in new shells.
Tailscale: $( $TS status >/dev/null 2>&1 && echo "logged in ($($TS ip -4 2>/dev/null))" || echo "not logged in; run and approve the URL:
  $TS up --ssh --hostname=strands-pod" )
HF: put HF_TOKEN in $WS/secrets.env (sourced by train.sh / serve_policy.sh), never in the repo.
MSG
