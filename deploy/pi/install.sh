#!/usr/bin/env bash
# Install the XLeRobot host on the Raspberry Pi (CP2). Run on the Pi as the robot user:
#   scp -r deploy/pi <user>@<pi>:~/strands-pi && ssh <user>@<pi> 'bash ~/strands-pi/install.sh'
# Upstream XLeRobot code, not Strands. Idempotent.
set -euo pipefail

XLEROBOT_REF="${XLEROBOT_REF:-b017b5e6354bd9f61f4247a920c72622ca0aade0}"
XLEROBOT_DIR="${XLEROBOT_DIR:-$HOME/XLeRobot}"
VENV="${VENV:-$HOME/xlerobot-venv}"
LEROBOT_SPEC="${LEROBOT_SPEC:-lerobot[feetech]>=0.6.1,<0.7.0}"

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

if [ ! -d "$XLEROBOT_DIR/.git" ]; then
  git clone https://github.com/Vector-Wangel/XLeRobot.git "$XLEROBOT_DIR"
fi
git -C "$XLEROBOT_DIR" fetch --quiet origin
git -C "$XLEROBOT_DIR" checkout --quiet "$XLEROBOT_REF"

[ -d "$VENV" ] || uv venv --python 3.12 "$VENV"
VIRTUAL_ENV="$VENV" uv pip install "$LEROBOT_SPEC" pyzmq opencv-python-headless
VIRTUAL_ENV="$VENV" uv pip install --no-deps \
  -e "$XLEROBOT_DIR/software/plugins/xlerobot_model" \
  -e "$XLEROBOT_DIR/software/plugins/lerobot_robot_xlerobot"

# Serial access for the motor buses.
sudo usermod -aG dialout "$USER" || true

UNIT=/etc/systemd/system/xlerobot-host.service
sed -e "s|@USER@|$USER|g" -e "s|@VENV@|$VENV|g" -e "s|@HOME@|$HOME|g" \
  "$(dirname "$0")/xlerobot-host.service" | sudo tee "$UNIT" >/dev/null
sudo systemctl daemon-reload
echo "Installed. Calibrate the follower first if needed (see CLAUDE.md), then:"
echo "  sudo systemctl enable --now xlerobot-host && journalctl -u xlerobot-host -f"
