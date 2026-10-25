# CLAUDE.md - Jacere fork of strands-labs/robots

Personal fork for the wireless XLeRobot teleop POC. Upstream package code is untouched; the fork
adds `deploy/`, `scripts/teleop_xlerobot.py`, `scripts/agent.py`, this file and `plan.md` (the
hand-off doc with checkpoint status). Upstream conventions live in `AGENTS.md`.

Git: `origin` = https://github.com/Jacob-Brokloff/robots, `upstream` = https://github.com/strands-labs/robots,
branch `main`.

## Hosts

| Host | Address | Role |
|---|---|---|
| Arch desktop | 192.168.1.162 | leader arms, `robot-client` container (`deploy/desktop/`) |
| XLeRobot Pi `Woodside` | 192.168.1.114 (WiFi), `ssh xlerobot` (user `woodside`, key in `~/.ssh/config`) | `xlerobot-host` systemd *user* unit (`deploy/pi/`); Debian 13, Python 3.13 |
| Proxmox host `pve` | https://192.168.1.78:8006 | VMs 100 claude-agent, 101 codex-agent, **102 strands-control** |
| VM `strands-control` (102) | 192.168.1.82 (DHCP), `ssh jbit@192.168.1.82` (desktop key) | Zenoh hub, dashboard, agent (`deploy/vm/`), clone at `~/robots`; Debian 13, 4 vCPU / 8 GB / 40 GB on truenas-nfs |
| RunPod pod `strands-vllm` | id `vo7awa4r5uk3x1`, SSH `root@69.30.85.107 -p 22159` (VM key only) | 1x A40, $0.60/hr; vLLM 0.11.0 serving `Qwen/Qwen3-32B-AWQ` on pod `127.0.0.1:8000` |

The pod's vLLM is not exposed publicly. The VM reaches it through the `runpod-vllm-tunnel`
systemd service (`ssh -L 127.0.0.1:8000:127.0.0.1:8000`); after a pod restart, update
`POD_HOST`/`POD_PORT` in `/etc/default/runpod-vllm-tunnel` on the VM. On the pod:
`/workspace/serve.sh` (log `/workspace/vllm.log`; transformers pinned to 4.57.1 for vLLM 0.11).
**Stop the pod in the RunPod console when not in use.**

## Ports

| Port | What | Where |
|---|---|---|
| 5555 | ZMQ PULL, commands to the robot | Pi (`xlerobot_host`) |
| 5556 | ZMQ PUSH, observations from the robot | Pi |
| 7447 | Zenoh mesh | VM listens (`ZENOH_LISTEN=tcp/0.0.0.0:7447`), desktop dials it |
| 8090 | Strands dashboard (`strands-robots dashboard`, `DASHBOARD_AUTH_TOKEN` in VM `deploy/.env`) | VM |
| 8000 | vLLM OpenAI API, via SSH tunnel | VM `127.0.0.1` only |

## Serial devices (desktop)

| by-id path | tty | Board | Role |
|---|---|---|---|
| `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79017318-if00` | ttyACM0 | CH343 | leader arm, side TBD (CP1) |
| `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90040979-if00` | ttyACM1 | CH343 | leader arm, side TBD (CP1) |
| `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` | ttyUSB0 | CH340 | not used by the POC |

Confirmed: 5B79017318 = **left**, 5B90040979 = **right** (motor homing offsets match the
calibration files, and the Woodside profile agrees).

## Serial devices (Pi follower buses)

| by-id path | tty | Bus |
|---|---|---|
| `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B8E114351-if00` | ttyACM1 | `port1`: left arm + head |
| `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B91027960-if00` | ttyACM0 | `port2`: right arm + 2 wheels |

Do not rely on the upstream default `port1=/dev/ttyACM0`; on this Pi it would swap the arms.

## Calibration IDs

| ID | Device | File |
|---|---|---|
| `leader_left` | left SO-101 leader | `~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/leader_left.json` (host path, mounted at `/root/.cache/huggingface/lerobot`) |
| `leader_right` | right SO-101 leader | same dir, `leader_right.json` |

`bi_so_leader` with `id=leader` derives the arm ids `leader_left` / `leader_right` itself
(`SOLeaderConfig` has no `id`), so calibrate each arm as a plain `so101_leader` with those ids;
the two-device fallback reads the same files. `leader_left.json` / `leader_right.json` are
copies of the existing `woodside-leader-5B79017318.json` / `JBit Arm.json` (originals kept).
| `woodside` | XLeRobot 2-wheel follower (Pi) | Pi `~/.cache/huggingface/lerobot/calibration/robots/xlerobot_2wheels/woodside.json` (all 16 motors) |

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

Pi (the host needs both motor buses, which `woodside-supervisor` holds while it runs):

```bash
scp -r deploy/pi xlerobot:strands-pi && ssh xlerobot 'bash ~/strands-pi/install.sh'   # installed already
ssh xlerobot 'systemctl --user stop woodside-supervisor && systemctl --user start xlerobot-host'
ssh xlerobot 'journalctl --user -u xlerobot-host -f'
ssh xlerobot 'systemctl --user stop xlerobot-host && systemctl --user start woodside-supervisor'   # hand back
```

VM:

```bash
docker compose -f deploy/vm/docker-compose.yml up -d --build dashboard   # zenoh hub + dashboard :8090
docker compose -f deploy/vm/docker-compose.yml run --rm agent            # interactive agent
docker compose -f deploy/vm/docker-compose.yml exec dashboard strands-robots doctor
```

## Gotchas

- The robot is the **2-wheel** build (`xlerobot_2wheels`, keys `x.vel`/`theta.vel`, no `y.vel`).
  Use `XLEROBOT_TYPE=xlerobot_2wheels_client`; `xlerobot_client` is the 3-omniwheel build.
- The Pi also runs **Woodside LeLab** (`woodside-supervisor` user unit, `~/.local/share/woodside-lelab`),
  a separate rate-limited teleop/safety stack using the same leaders, follower ports and
  calibrations. It and `xlerobot-host` cannot run at the same time.
- The 2-wheel host's `connect()` prompts on stdin to restore calibration (writes it to the motors);
  the unit answers Enter.
- `lerobot_robot_xlerobot` registers `XLerobotClientConfig` but does not export `XLerobotClient`,
  so lerobot cannot build `xlerobot_client` from it alone. `deploy/xlerobot_client/` is a tiny
  `lerobot_robot_xlerobot_client` plugin that exposes the class; the image installs it.
- Never `pip install strands` (unrelated package); it is `strands-robots`.
- The container runs as root, so `doctor`'s "not in dialout group" FAIL does not apply; its MuJoCo
  FAILs are the sim stack, which the POC does not install.
- Mesh is off unless `mesh=True`; `teleop_xlerobot.py` turns it on (`--no-mesh` to skip).
- The image installs CPU torch (`UV_TORCH_BACKEND=cpu`); the desktop GPU is AMD and no policy runs here.
