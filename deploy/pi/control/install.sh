#!/usr/bin/env bash
# Install the Pi control loop (CP11): a venv with the fork + the XLeRobot plugins, and the
# xlerobot-control systemd user unit (the woodside peer; enabled, not started). From the desktop:
#   ssh xlerobot 'git clone https://github.com/Jacob-Brokloff/robots ~/robots || git -C ~/robots pull --ff-only'
#   ssh xlerobot 'bash ~/robots/deploy/pi/control/install.sh'
# Runs next to xlerobot-host (deploy/pi/), which keeps its own ~/xlerobot-runtime venv.
set -euo pipefail

VENV="${VENV:-$HOME/strands-control}"
REPO="${REPO:-$HOME/robots}"
XLEROBOT_SRC="${XLEROBOT_SRC:-$HOME/xlerobot-source}"
HERE="$(cd "$(dirname "$0")" && pwd)"

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

[ -d "$VENV" ] || uv venv --python 3.13 "$VENV"
# CPU torch: the policy runs on RunPod; lerobot still imports torch for the client's types. PyPI's aarch64
# torch is a CUDA build (GBs of nvidia-*), and UV_TORCH_BACKEND=cpu fails on aarch64 because the PyTorch CPU
# index has no aarch64 torchcodec. So: torch/torchvision from the CPU index first, the rest from PyPI. 2.11 is
# the torch lerobot 0.6.1 pairs with torchcodec 0.11 (and what ~/xlerobot-runtime runs); a newer one gets replaced.
VIRTUAL_ENV="$VENV" uv pip install --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 torchvision==0.26.0
VIRTUAL_ENV="$VENV" uv pip install -e "$REPO[lerobot,mesh,inference]" pyzmq
VIRTUAL_ENV="$VENV" uv pip install --no-deps \
  "$XLEROBOT_SRC/software/plugins/xlerobot_model" \
  "$XLEROBOT_SRC/software/plugins/lerobot_robot_xlerobot" \
  "$XLEROBOT_SRC/software/plugins/lerobot_robot_xlerobot_2wheels" \
  -e "$REPO/deploy/xlerobot_client"

# Registry overlay with xlerobot_2wheels_client, shared with the desktop.
mkdir -p "$HOME/.strands_robots"
cp "$REPO/deploy/strands/user_robots.json" "$HOME/.strands_robots/user_robots.json"

[ -f "$HOME/strands-control.env" ] || cp "$HERE/strands-control.env.example" "$HOME/strands-control.env"
mkdir -p "$HOME/.config/systemd/user"
sed -e "s|@VENV@|$VENV|g" -e "s|@REPO@|$REPO|g" "$HERE/xlerobot-control.service" \
  > "$HOME/.config/systemd/user/xlerobot-control.service"
systemctl --user daemon-reload
systemctl --user enable xlerobot-control
echo "Installed $VENV and ~/.config/systemd/user/xlerobot-control.service (enabled; restart it to pick up changes)."
echo "With xlerobot-host running: systemctl --user restart xlerobot-control, then"
echo "  $VENV/bin/python $REPO/scripts/pi_control.py observe"
