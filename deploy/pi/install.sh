#!/usr/bin/env bash
# Install the XLeRobot 2-wheel host on the Pi as a systemd user unit (CP2). From the desktop:
#   scp -r deploy/pi xlerobot:~/strands-pi && ssh xlerobot 'bash ~/strands-pi/install.sh'
# Reuses ~/xlerobot-runtime when it already has lerobot + the 2-wheel plugin (it does on
# Woodside); otherwise builds a venv from XLeRobot at the pinned ref. Does not start anything.
set -euo pipefail

VENV="${VENV:-$HOME/xlerobot-runtime}"
ROBOT_ID="${ROBOT_ID:-woodside}"   # calibration: ~/.cache/huggingface/lerobot/calibration/robots/xlerobot_2wheels/<id>.json
PORT1="${PORT1:-/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B8E114351-if00}"   # left arm + head (ttyACM1)
PORT2="${PORT2:-/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B91027960-if00}"   # right arm + wheels (ttyACM0)
XLEROBOT_REF="${XLEROBOT_REF:-b017b5e6354bd9f61f4247a920c72622ca0aade0}"
XLEROBOT_DIR="${XLEROBOT_DIR:-$HOME/XLeRobot}"

if ! "$VENV/bin/python" -c "import lerobot_robot_xlerobot_2wheels, zmq" 2>/dev/null; then
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  [ -d "$XLEROBOT_DIR/.git" ] || git clone https://github.com/Vector-Wangel/XLeRobot.git "$XLEROBOT_DIR"
  git -C "$XLEROBOT_DIR" fetch --quiet origin && git -C "$XLEROBOT_DIR" checkout --quiet "$XLEROBOT_REF"
  [ -d "$VENV" ] || uv venv "$VENV"
  VIRTUAL_ENV="$VENV" uv pip install "lerobot[feetech]>=0.6.1,<0.7.0" pyzmq opencv-python-headless
  VIRTUAL_ENV="$VENV" uv pip install --no-deps \
    -e "$XLEROBOT_DIR/software/plugins/xlerobot_model" \
    -e "$XLEROBOT_DIR/software/plugins/lerobot_robot_xlerobot_2wheels"
fi

mkdir -p "$HOME/.config/systemd/user"
HERE="$(cd "$(dirname "$0")" && pwd)"
sed -e "s|@VENV@|$VENV|g" -e "s|@HERE@|$HERE|g" -e "s|@ROBOT_ID@|$ROBOT_ID|g" -e "s|@PORT1@|$PORT1|g" -e "s|@PORT2@|$PORT2|g" \
  "$(dirname "$0")/xlerobot-host.service" > "$HOME/.config/systemd/user/xlerobot-host.service"
systemctl --user daemon-reload
echo "Installed ~/.config/systemd/user/xlerobot-host.service (not started)."
echo "The host needs the motor buses: stop woodside-supervisor first, then"
echo "  systemctl --user start xlerobot-host && journalctl --user -u xlerobot-host -f"
