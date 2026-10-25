# CLAUDE.md - Jacere fork of strands-labs/robots

Personal fork for the wireless XLeRobot teleop POC. Upstream package code is untouched; the fork
adds `deploy/`, `scripts/teleop_xlerobot.py`, `scripts/agent.py`, this file and `plan.md` (the
hand-off doc with checkpoint status). Upstream conventions live in `AGENTS.md`.

Git: `upstream` = https://github.com/strands-labs/robots, branch `main`. `origin` (the fork
`Jacob-Brokloff/robots`) is not created yet; see `plan.md` CP0.

## Hosts

| Host | Address | Role |
|---|---|---|
| Arch desktop | 192.168.1.162 | leader arms, `robot-client` container (`deploy/desktop/`) |
| XLeRobot Pi | `PI_IP` (TBD, WiFi) | `xlerobot_host` systemd service (`deploy/pi/`) |
| Proxmox VM `strands-control` | TBD | Zenoh hub, dashboard, agent (`deploy/vm/`) |
| RunPod pod | TBD | vLLM, OpenAI-compatible `/v1` |

## Ports

| Port | What | Where |
|---|---|---|
| 5555 | ZMQ PULL, commands to the robot | Pi (`xlerobot_host`) |
| 5556 | ZMQ PUSH, observations from the robot | Pi |
| 7447 | Zenoh mesh | VM listens (`ZENOH_LISTEN=tcp/0.0.0.0:7447`), desktop dials it |
| 8090 | Strands dashboard (`strands-robots dashboard`) | VM |

## Serial devices (desktop)

| by-id path | tty | Board | Role |
|---|---|---|---|
| `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79017318-if00` | ttyACM0 | CH343 | leader arm, side TBD (CP1) |
| `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90040979-if00` | ttyACM1 | CH343 | leader arm, side TBD (CP1) |
| `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` | ttyUSB0 | CH340 | not used by the POC |

`deploy/.env.example` assumes 5B79017318 = left, 5B90040979 = right until CP1 confirms it.

## Calibration IDs

| ID | Device | File |
|---|---|---|
| `leader_left` | left SO-101 leader | `~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/leader_left.json` (host path, mounted at `/root/.cache/huggingface/lerobot`) |
| `leader_right` | right SO-101 leader | same dir, `leader_right.json` |

`bi_so_leader` with `id=leader` derives the arm ids `leader_left` / `leader_right` itself
(`SOLeaderConfig` has no `id`), so calibrate each arm as a plain `so101_leader` with those ids;
the two-device fallback reads the same files. An older calibration for board 5B79017318 exists
in that dir as `woodside-leader-5B79017318.json`; copy it to `leader_<side>.json` instead of
recalibrating if it is still valid for that arm.
| `my_xlerobot_pc` | XLeRobot follower (Pi) | on the Pi under `~/.cache/huggingface/lerobot/calibration/robots/xlerobot/`; the id is hardcoded in upstream `xlerobot_host.main()` |

## Env vars (`deploy/.env`, copied from `deploy/.env.example`, gitignored)

- `PI_IP`, `LEFT_LEADER_PORT`, `RIGHT_LEADER_PORT` - desktop teleop.
- `STRANDS_BASE_DIR=/strands` (set in compose; host dir `deploy/strands/`, holds `user_robots.json`
  which registers `xlerobot_client`).
- `STRANDS_MESH_LOCAL_DEV=true` - mesh auth `none`. Once any `ZENOH_CONNECT`/`ZENOH_LISTEN` is
  non-loopback Strands also requires `STRANDS_MESH_I_KNOW_THIS_IS_INSECURE=1`.
- `ZENOH_CONNECT=tcp/<vm-ip>:7447` on the desktop after CP4 (empty = mesh stays local).
- `BYPASS_TOOL_CONSENT=true` skips every operator consent gate (logged as WARNING). POC only.
  Narrower: `STRANDS_MESH_HITL_ACTIONS=<actions that still ask>` for the mesh tool.
- `DASHBOARD_AUTH_TOKEN` - required for the dashboard to bind a non-loopback address.
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL_ID` - RunPod vLLM for `scripts/agent.py`.

## Commands

Desktop (repo root):

```bash
docker compose -f deploy/desktop/docker-compose.yml build
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client strands-robots doctor
# CP1: identify + calibrate leaders, then read them
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client lerobot-find-port
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/ttyACM0 --teleop.id=leader_left
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/ttyACM1 --teleop.id=leader_right
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client python scripts/teleop_xlerobot.py --check-leaders
# CP3: plain lerobot, then Strands
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client lerobot-teleoperate --robot.type=xlerobot_client --robot.remote_ip=$PI_IP --teleop.type=bi_so_leader --teleop.left_arm_config.port=$LEFT_LEADER_PORT --teleop.right_arm_config.port=$RIGHT_LEADER_PORT --teleop.id=leader
docker compose -f deploy/desktop/docker-compose.yml run --rm robot-client python scripts/teleop_xlerobot.py
```

Pi:

```bash
scp -r deploy/pi <user>@<pi>:~/strands-pi && ssh <user>@<pi> 'bash ~/strands-pi/install.sh'
sudo systemctl enable --now xlerobot-host && journalctl -u xlerobot-host -f   # "Waiting for commands..."
nc -zv $PI_IP 5555 5556                                                      # from the desktop
```

VM:

```bash
docker compose -f deploy/vm/docker-compose.yml up -d --build dashboard   # zenoh hub + dashboard :8090
docker compose -f deploy/vm/docker-compose.yml run --rm agent            # interactive agent
docker compose -f deploy/vm/docker-compose.yml exec dashboard strands-robots doctor
```

## Gotchas

- `lerobot_robot_xlerobot` registers `XLerobotClientConfig` but does not export `XLerobotClient`,
  so lerobot cannot build `xlerobot_client` from it alone. `deploy/xlerobot_client/` is a tiny
  `lerobot_robot_xlerobot_client` plugin that exposes the class; the image installs it.
- Never `pip install strands` (unrelated package); it is `strands-robots`.
- The container runs as root, so `doctor`'s "not in dialout group" FAIL does not apply; its MuJoCo
  FAILs are the sim stack, which the POC does not install.
- Mesh is off unless `mesh=True`; `teleop_xlerobot.py` turns it on (`--no-mesh` to skip).
- The image installs CPU torch (`UV_TORCH_BACKEND=cpu`); the desktop GPU is AMD and no policy runs here.
