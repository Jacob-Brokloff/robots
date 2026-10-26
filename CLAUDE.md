# CLAUDE.md - Jacere fork of strands-labs/robots

Personal fork for the wireless XLeRobot teleop POC. Upstream package code is untouched; the fork
adds `deploy/`, `scripts/teleop_xlerobot.py`, `scripts/agent.py`, the phase 2 scripts below, this file
and `plan.md` (the hand-off doc with checkpoint status). Upstream conventions live in `AGENTS.md`.

Git: `origin` = https://github.com/Jacob-Brokloff/robots, `upstream` = https://github.com/strands-labs/robots,
branch `main`.

## Hosts

| Host | Address | Role |
|---|---|---|
| Arch desktop | 192.168.1.162 | leader arms, `robot-client` container (`deploy/desktop/`) |
| XLeRobot Pi `Woodside` | 192.168.1.114 (WiFi), `ssh xlerobot` (user `woodside`, key in `~/.ssh/config`) | `xlerobot-host` systemd *user* unit (`deploy/pi/`); Debian 13, Python 3.13 |
| Proxmox host `pve` | https://192.168.1.78:8006 | VMs 100 claude-agent, 101 codex-agent, **102 strands-control** |
| VM `strands-control` (102) | 192.168.1.82 (DHCP), `ssh jbit@192.168.1.82` (desktop key) | Zenoh hub, dashboard, agent (`deploy/vm/`), clone at `~/robots`; Debian 13, 4 vCPU / 8 GB / 40 GB on truenas-nfs |
| RunPod network volume `strands-xlerobot` | id `tfjehy3k9s`, **US-MO-1**, 60 GB standard ($4.20/mo), mounts at `/workspace`; S3 `s3://tfjehy3k9s` via `https://s3api-us-mo-1.runpod.io` | Every pod is deployed **on this volume** (Secure Cloud, US-MO-1): 1x A40 ($0.59/hr) if free, else 1x L40S ($1.09/hr). No pod exists now. SSH: the pod takes the **desktop** key (`~/.ssh/id_ed25519`, RunPod account key), not the VM's; the address changes per pod |

## Tailnet (CP7, tailnet `jacob-brokloff.github`, MagicDNS `*.tail22e67e.ts.net`)

| Name | Tailnet IP | Host | Notes |
|---|---|---|---|
| `arch-desktop` | 100.92.165.27 | desktop | operator `jacob-jbit`, so `tailscale` needs no sudo |
| `strands-control` | 100.70.150.7 | VM | apt `tailscale`, `tailscaled` enabled |
| `woodside` | 100.89.113.110 | Pi | apt `tailscale`, `tailscaled` enabled |
| `strands-pod` | 100.85.254.112 | pod | userspace `tailscaled`, binaries and `tailscaled.state` on the volume in `/workspace/tailscale`; logged in once (2026-10-26), **key expiry disabled**. Any pod on the volume rejoins with this name/IP when `deploy/runpod/bootstrap.sh` starts the daemon; no new approval |

The Qwen/vLLM path is retired: `runpod-vllm-tunnel` on the VM is disabled (unit file kept) and the new pod
has no vLLM. Pod tailscale CLI: `/workspace/tailscale/tailscale --socket=/workspace/tailscale/tailscaled.sock`.
Only if the state is ever lost: run `up --ssh --hostname=strands-pod` in the background (`nohup ... &`); a
`timeout`-killed `up` cancels the login URL.
**Stop the pod in the RunPod console when not in use.**

## Ports

| Port | What | Where |
|---|---|---|
| 5555 | ZMQ PULL, commands to the robot | Pi (`xlerobot_host`) |
| 5556 | ZMQ PUSH, observations from the robot | Pi |
| 7447 | Zenoh mesh | VM listens (`ZENOH_LISTEN=tcp/0.0.0.0:7447`), desktop and Pi dial `tcp/100.70.150.7:7447` (tailnet) |
| 8090 | Strands dashboard (`strands-robots dashboard`, `DASHBOARD_AUTH_TOKEN` in VM `deploy/.env`) | VM (LAN) |
| 8090 | Strands dashboard, loopback only, passkey login: **http://localhost:8090** | desktop (`deploy/desktop` service `dashboard`) |
| 8000 | vLLM OpenAI API, via SSH tunnel (**retired** in CP7) | VM `127.0.0.1` only |
| 8765 | PolicyServer (WebSocket, no TLS; phase 2, not running yet) | VM (`serve_nudge.py`) / pod `127.0.0.1` behind userspace Tailscale (`serve_policy.sh`) |

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
- `ZENOH_CONNECT=tcp/100.70.150.7:7447` on the desktop (VM tailnet IP since CP7; empty = mesh stays local).
- `BYPASS_TOOL_CONSENT=true` skips every operator consent gate (logged as WARNING). POC only.
  Narrower: `STRANDS_MESH_HITL_ACTIONS=<actions that still ask>` for the mesh tool.
- `DASHBOARD_AUTH_TOKEN` - required for the dashboard to bind a non-loopback address.
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL_ID` - RunPod vLLM for `scripts/agent.py` (retired; no vLLM on the pod).

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
docker compose -f deploy/desktop/docker-compose.yml run --rm -e BYPASS_TOOL_CONSENT=true robot-client python scripts/teleop_xlerobot.py --duration 120
# glides 3 s from the robot's pose to the leaders', then follows live; --glide 0 to skip
```

Sim (CP8-CP10; `sim` service = same image, `/dev/dri` + `MUJOCO_GL=egl`, no serial devices):

```bash
docker compose -f deploy/desktop/docker-compose.yml run --rm sim strands-robots doctor
docker compose -f deploy/desktop/docker-compose.yml run --rm sim python examples/01_sim_hello_world.py
docker compose -f deploy/desktop/docker-compose.yml run --rm sim python scripts/xlerobot_2wheels_sim.py   # drive check
docker compose -f deploy/desktop/docker-compose.yml run --rm sim python scripts/xlerobot_embodiment.py    # sim/real keys
python scripts/make_xlerobot_2wheels_mjcf.py <XLeRobot>/simulation/mujoco deploy/sim/xlerobot_2wheels    # regenerate MJCF
```

Sim robots in `user_robots.json`: `xlerobot` (upstream 3-omniwheel MJCF, from GitHub) and `xlerobot_2wheels`
(fork MJCF from `deploy/sim/xlerobot_2wheels` on GitHub; reads `xlerobot`'s meshes, so `xlerobot` must be
downloaded first). Assets cache in `deploy/strands/assets/` (root-owned). Both spawn from the dashboard.

Phase 2 Pi loop (CP11, run): venv `~/strands-control`, clone `~/robots` on the Pi, `xlerobot-control.service`
user unit (never enabled), `~/strands-control.env`. With `xlerobot-host` running:

```bash
ssh xlerobot 'set -a; . ~/strands-control.env; set +a; ~/strands-control/bin/python ~/robots/scripts/pi_control.py --dry-run'
ssh jbit@192.168.1.82 'cd ~/robots && docker compose -f deploy/vm/docker-compose.yml run -d --rm --name nudge-server --no-deps dashboard python scripts/serve_nudge.py --host 100.70.150.7'
ssh xlerobot 'set -a; . ~/strands-control.env; set +a; ~/strands-control/bin/python ~/robots/scripts/pi_control.py --duration 10'   # moves the left gripper
ssh jbit@192.168.1.82 'docker stop nudge-server'
```

Phase 2 files written, not yet run: pod `deploy/runpod/{bootstrap,train,serve_policy}.sh`
+ `scripts/train_pi05.py` / `scripts/serve_policy.py`; shared embodiment `scripts/xlerobot_embodiment.py`.

Desktop dashboard (always on; passkey store persisted in `deploy/strands/dashboard-auth/`):

```bash
docker compose -f deploy/desktop/docker-compose.yml up -d dashboard   # open http://localhost:8090 (not 127.0.0.1)
```

A new passkey needs the one-time bootstrap file; with no passkey enrolled the server mints it at
`/root/.strands_dashboard/enroll_token` inside the container. Copy it without printing:
`docker compose -f deploy/desktop/docker-compose.yml exec -T dashboard cat /root/.strands_dashboard/enroll_token | tr -d '\n' | wl-copy`.

Agent motion check (needs mesh mTLS before the robot will accept it): `scripts/robot_peer.py` on the desktop
with `STRANDS_ROBOT_COMMAND_ALLOW=execute STRANDS_MESH_POLICY_TYPE_ALLOW=nudge`, then `~/cp5_nudge.sh` on the VM
(also needs `STRANDS_MESH_POLICY_TYPE_ALLOW=nudge`). `scripts/agent.py` prompts `Approve? [y/N]` for gated actions.

Pi: `xlerobot-host` is the robot's only stack (enabled at boot, runs forever; Woodside retired 2026-10-26).
The unit runs `~/robots/deploy/pi/xlerobot_host.py` with the cameras in `~/robots/deploy/pi/cameras.json`.
Its (re)start reconfigures the motors with torque briefly off: support the arms first.

```bash
ssh xlerobot 'bash ~/robots/deploy/pi/install.sh'   # installed already; rerun after editing the unit or cameras
ssh xlerobot 'systemctl --user restart xlerobot-host'
ssh xlerobot 'systemctl --user status xlerobot-host -n 50'   # user journal is not persisted; status shows the log
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
- **Woodside LeLab is retired** (2026-10-26): `woodside-supervisor` is stopped and disabled, files left in
  `~/.local/share/woodside-lelab`. Do not start it; it would fight `xlerobot-host` for both motor buses.
- The plugin host exits after `connection_time_s` (default 3600 s), and that clean exit disables torque on
  both arms; the unit passes 10 years so this never fires.
- The 2-wheel host's `connect()` prompts on stdin to restore calibration (writes it to the motors);
  the unit answers Enter.
- `lerobot_robot_xlerobot` registers `XLerobotClientConfig` but does not export `XLerobotClient`,
  so lerobot cannot build `xlerobot_client` from it alone. `deploy/xlerobot_client/` is a tiny
  `lerobot_robot_xlerobot_client` plugin that exposes the class; the image installs it.
- Never `pip install strands` (unrelated package); it is `strands-robots`.
- The container runs as root, so `doctor`'s "not in dialout group" FAIL does not apply; its MuJoCo
  FAILs are the sim stack, which the POC does not install.
- Mesh is off unless `mesh=True`; `teleop_xlerobot.py` turns it on (`--no-mesh` to skip).
- If a follower bus goes silent (no motors answer, USB adapter still present), the C300's USB-C port
  dropped 12 V. Toggle the station's USB outputs (this reboots the Pi too); the host starts at boot
  (support the arms).
- Both leaders run from 5 V / 3 A supplies (since 2026-10-26). Before that the right leader's
  gripper (id 6) flagged "Input voltage error" on connect; `teleop_xlerobot.py` still retries the
  leader connect as a safety net.
- Agent-driven motion on real hardware goes through mesh `execute`/`start`. The robot refuses it unless
  the sender is attributable ("no publisher session id" under auth `none`), so it needs mesh mTLS, plus a
  policy (`scripts/nudge_policy.py` is a bounded one). `set_joints` is sim-only. `stop` works today.
- `systemctl --user stop xlerobot-host` (SIGTERM) leaves the follower torque ON.
- The image installs CPU torch (`UV_TORCH_BACKEND=cpu`); the desktop GPU is AMD and no policy runs here.
  The GPU is used only for MuJoCo's EGL rendering (mesa, `/dev/dri`).
- At the pinned XLeRobot ref the 2-wheel plugin configures **no cameras** (`cameras={}`), and the client drops
  frames whose names are not in its own `config.cameras`; host and client both need the camera config.
  `deploy/pi/cameras.json` is that config (`head` = D415 colour `/dev/video4`, `left_wrist`/`right_wrist` =
  USB ports 1.1/1.2, sides unverified), read by `deploy/pi/xlerobot_host.py` and `pi_control.py --cameras`.
- Raw camera frames on the PolicyServer wire cost ~1 s per call over the Pi's WiFi (3 x 640x480 ~ 3.7 MB);
  `pi_control.py` drops them for image-free policies. Pi aarch64 torch: CPU index, `torch==2.11.0` (see install.sh).
- The VM dashboard drops woodside's mesh replies under auth `none` (`no_answer`), but `stop` still halts the robot.
- The dashboard at :8090 is passkey-only. To script `/api/sim`, run a second one in the `sim` service with
  `-e DASHBOARD_AUTH_TOKEN=<random> ... strands-robots dashboard --host 127.0.0.1 --port 8091` and send
  `Authorization: Bearer <token>`; remove it afterwards.
