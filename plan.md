# Strands Fork: wireless XLeRobot teleop POC

## Context

Jacob wants a personal fork of `strands-labs/robots` (Strands Robots, AWS's Python library that lets a
Strands Agent drive real robots via LeRobot drivers) and a fast proof of concept: two SO-101 leader
arms on this Arch desktop teleoperating an XLeRobot that is fully wireless (Raspberry Pi onboard runs
the follower arms, head motors and wheel servos, connected over WiFi). Strands itself runs in
containers, the control plane lives in a VM on the local Proxmox server, and the agent's LLM is served
from RunPod. Minimal tests, minimal gates; get it moving, then iterate.

Research findings that shape the plan (verified against the upstream repos on 2026-10-25):

- Strands has **no Dockerfile**; we add our own. Install is `pip install "strands-robots[lerobot]"`,
  Python 3.12+, `uv` recommended. CLI entrypoint is `strands-robots` (has `doctor` and `dashboard`).
- Strands `Robot(name, mode="real")` resolves `hardware.lerobot_type` to a lerobot config dataclass and
  **already loads third-party `lerobot_robot_*` plugins** (`strands_robots/hardware_robot.py` ~L1344).
  A **user registry overlay** (`$STRANDS_BASE_DIR/user_robots.json`, merged over `robots.json`) lets us
  register new robots without touching package code. The shipped `lekiwi_client` entry is the template:
  `{"description": ..., "category": "mobile_manip", "hardware": {"lerobot_type": "lekiwi_client"}}`.
- XLeRobot ships lerobot plugins in `software/plugins/` (`lerobot_robot_xlerobot`, type `xlerobot`),
  with `xlerobot_host.py` (ZMQ PULL cmd on **5555**, PUSH observations on **5556**, 500 ms watchdog)
  and `xlerobot_client` config (`remote_ip`, `port_zmq_cmd`, `port_zmq_observations`). This is exactly
  the LeKiwi host/client pattern, so it is the wireless path.
- Leader side: lerobot has `bi_so_leader` (`left_arm_config`/`right_arm_config`, each an
  `SOLeaderConfig` with `port`, `id`). It emits `left_shoulder_pan.pos`, `right_gripper.pos`, etc.
  `xlerobot_client` expects `left_arm_shoulder_pan.pos`, `right_arm_gripper.pos`, `head_motor_1.pos`,
  `head_motor_2.pos`, `x.vel`, `y.vel`, `theta.vel`. Strands `attach_teleop(device, map_fn=)` handles
  the rename: `left_X -> left_arm_X`, `right_X -> right_arm_X`. Head and base get zeros for the POC.
- Strands teleop API: `follower.attach_teleop(Teleoperator("bi_so_leader", ...), map_fn=...)`, then
  `follower.teleoperate(hz=50, block=True)`.
- Agent model: Strands Agents `OpenAIModel(client_args={"base_url": ..., "api_key": ...}, model_id=...)`
  with `pip install "strands-agents[openai]"` talks to any OpenAI-compatible server (vLLM on RunPod).
- Mesh: Zenoh on **7447**. For the POC use `STRANDS_MESH_LOCAL_DEV=true` (auth `none`) and
  `ZENOH_CONNECT=tcp/<vm>:7447` on peers. mTLS is a later hardening step.
- Remote policy inference (`PolicyServer`, ws on 8765) exists but is **out of scope** (RunPod = LLM only).

Local facts: this desktop is Arch, 20 cores, 32 GB, Radeon RX 6600 (no CUDA), has `docker 29`, `uv`,
`gh` (logged in as `Jacob-Brokloff`), `tailscale` (installed, currently logged out), user is in
`docker` group. Serial devices present now: `/dev/ttyACM0` (CH343 serial 5B79017318), `/dev/ttyACM1`
(CH343 serial 5B90040979), `/dev/ttyUSB0` (CH340). The two ACM boards are almost certainly the two
leader arms; stable paths live under `/dev/serial/by-id/`. LAN is `192.168.1.0/24`.

## Target architecture

```
[Arch desktop 192.168.1.162]            [XLeRobot Pi, WiFi, 192.168.1.?]
  leader arms /dev/ttyACM0,1              lerobot + lerobot_robot_xlerobot
  container: robot-client   --ZMQ 5555/5556 over LAN-->  xlerobot_host (follower arms, head, wheels)
  (strands + xlerobot plugin,
   bi_so_leader -> xlerobot_client,
   mesh peer)
        |  zenoh 7447 (LAN or Tailscale)
[Proxmox VM "strands-control"]           [RunPod pod]
  container: agent + dashboard  --https (Tailscale or RunPod proxy)-->  vLLM, OpenAI-compatible API
  (Strands Agent w/ OpenAIModel,
   mesh listener, strands-robots dashboard)
```

Hard rule: nothing about the robot is wired to the desktop. All robot I/O goes through the Pi over WiFi.

## Repo layout (the fork)

Fork `strands-labs/robots` to `Jacob-Brokloff/robots` with `gh repo fork`, clone into
`/home/jacob-jbit/Documents/jacere-robotics/Strands_Fork` (the existing empty dir), keep `upstream`
remote. Add, without modifying upstream package code:

```
plan.md                          # this plan, with checkpoint status; the hand-off doc for other sessions
CLAUDE.md                        # mappings: hosts, ports, serial IDs, arm IDs, env vars, commands
deploy/
  Dockerfile                     # python:3.12-slim + uv; strands-robots[lerobot] + strands-agents[openai] + xlerobot plugin
  desktop/docker-compose.yml     # robot-client: host network, /dev/serial/by-id/* devices, STRANDS_BASE_DIR mount
  vm/docker-compose.yml          # agent + dashboard: ports 7447, 8000 (dashboard); env from .env
  pi/                            # xlerobot_host install script + systemd unit (or compose if Pi has docker)
  strands/user_robots.json       # registers "xlerobot_client" (lerobot_type xlerobot_client)
  .env.example                   # PI_IP, LEFT_LEADER_PORT, RIGHT_LEADER_PORT, OPENAI_BASE_URL, OPENAI_API_KEY, MODEL_ID
scripts/
  teleop_xlerobot.py             # Robot("xlerobot_client", remote_ip=PI) + Teleoperator("bi_so_leader") + map_fn
  agent.py                       # Strands Agent(OpenAIModel -> RunPod, tools=[robot, robot_mesh])
```

`teleop_xlerobot.py` sketch (the only new "code"):

```python
from strands_robots import Robot, Teleoperator
from lerobot.teleoperators.so_leader import SOLeaderConfig
import os
pi = os.environ["PI_IP"]
follower = Robot("xlerobot_client", mode="real", remote_ip=pi, mesh=True)
leader = Teleoperator("bi_so_leader",
    left_arm_config=SOLeaderConfig(port=os.environ["LEFT_LEADER_PORT"], id="left_leader"),
    right_arm_config=SOLeaderConfig(port=os.environ["RIGHT_LEADER_PORT"], id="right_leader"))
def map_fn(a):
    out = {k.replace("left_", "left_arm_", 1).replace("right_", "right_arm_", 1): v for k, v in a.items()}
    out.update({"head_motor_1.pos": 0.0, "head_motor_2.pos": 0.0, "x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
    return out
follower.attach_teleop(leader, map_fn=map_fn)
follower.teleoperate(hz=30, block=True)   # Pi host loops at 30 Hz
```

Fallback if `bi_so_leader` kwargs don't bind through Strands' kwarg allowlist: attach two
`Teleoperator("so101_leader", port=..)` devices with per-device `map_fn` prefixes. If the XLeRobot
plugin's lerobot pin conflicts with Strands' `[lerobot]` range, vendor `xlerobot_client.py` +
`config_xlerobot.py` into `deploy/xlerobot_client/` as a tiny `lerobot_robot_xlerobot_client` plugin.

## Checkpoints (in order; update `plan.md` status as each lands)

**CP0. Fork and scaffold** (desktop, no hardware)
- `gh repo fork strands-labs/robots --clone=false`, clone into `Strands_Fork`, add `upstream`.
- Create the layout above, `plan.md`, `CLAUDE.md`, `.env.example`. Build the image locally
  (`docker compose -f deploy/desktop/docker-compose.yml build`). Commit on `main` of the fork.
- Done when: `docker compose run robot-client strands-robots doctor` runs inside the container.

**CP1. Leader arms on the desktop**
- Identify which `by-id` path is left vs right (unplug test or `lerobot-find-port`). Record in CLAUDE.md.
- Calibrate each leader inside the container: `lerobot-calibrate --teleop.type=so101_leader
  --teleop.port=... --teleop.id=left_leader` (and right). Calibration files persist via the mounted
  `~/.cache/huggingface/lerobot` / `STRANDS_BASE_DIR` volume.
- Done when: `lerobot-teleoperate`-style read of both leaders prints joint positions.

**CP2. Pi runs the XLeRobot host** (needs Pi SSH access; see open questions)
- On the Pi: lerobot + `pip install -e software/plugins/xlerobot_model software/plugins/lerobot_robot_xlerobot`,
  follower calibration if not already done, then `python -m lerobot_robot_xlerobot.xlerobot_host`
  (exact module path confirmed on the Pi) as a systemd service so it survives reboots.
- Record Pi hostname/IP, serial ports, robot `id` in CLAUDE.md. Pin the Pi's DHCP lease or use hostname.
- Done when: from the desktop, `nc -zv <PI_IP> 5555 5556` succeeds and the host logs "Waiting for commands".

**CP3. Wireless teleop, plain lerobot first, then Strands**
- Sanity check with lerobot only (fastest proof the hardware chain works):
  `lerobot-teleoperate --robot.type=xlerobot_client --robot.remote_ip=<PI> --teleop.type=bi_so_leader
  --teleop.left_arm_config.port=... --teleop.right_arm_config.port=...`.
- Then `docker compose run robot-client python scripts/teleop_xlerobot.py` (Strands path, with
  `user_robots.json` registering `xlerobot_client`). Accept the operator consent prompt; for the POC set
  `STRANDS_ROBOT_COMMAND_ALLOW` / `BYPASS_TOOL_CONSENT` as documented in CLAUDE.md.
- Done when: moving a leader moves the matching follower over WiFi. **This is the POC milestone.**

**CP4. Proxmox VM + control plane**
- In the already-open Proxmox Chrome tab: create VM `strands-control` (Ubuntu 24.04 cloud image or
  Debian 12, 4 vCPU, 8 GB, 40 GB, bridge on the LAN). Credentials from 1Password "Jbit Kingdom Lab"
  (1Password MCP failed to connect this session; use the browser or retry later).
- Install docker + tailscale; `tailscale up` on VM and desktop (desktop is currently logged out).
- Deploy `deploy/vm/docker-compose.yml`: agent/dashboard container with `STRANDS_MESH_LOCAL_DEV=true`,
  `ZENOH_LISTEN=tcp/0.0.0.0:7447`, dashboard on 8000. Desktop `robot-client` gets
  `ZENOH_CONNECT=tcp/<vm-ip>:7447`.
- Done when: `strands-robots doctor` on the VM lists the desktop's `xlerobot_client` peer, and the
  dashboard shows it.

**CP5. RunPod LLM**
- In the open RunPod tab: launch a vLLM pod (RunPod "vLLM" template; model e.g. `Qwen/Qwen3-32B-AWQ`
  or whatever fits one 24-48 GB GPU; tool calling enabled: `--enable-auto-tool-choice
  --tool-call-parser hermes`). Expose the HTTP port with an API key, or join the pod to Tailscale.
- Set `OPENAI_BASE_URL=https://<pod>/v1`, `OPENAI_API_KEY`, `MODEL_ID` in the VM `.env`;
  `scripts/agent.py` uses `OpenAIModel`. Smoke prompt: "list robots on the mesh, then move the left
  arm to home" via `robot_mesh` `send`/`tell`.
- Done when: the agent on the VM answers a question about the robot and a gated motion reaches the Pi.

**CP6. Docs** - fill `CLAUDE.md` mappings (hosts/IPs, Tailscale names, serial by-id → left/right,
calibration IDs, ZMQ/Zenoh/dashboard ports, env vars, one-line commands per host), mark checkpoints
done in `plan.md`, push.

## Decisions baked in

- Containers everywhere except the Pi (systemd + venv on the Pi unless it already has docker; the Pi
  side is upstream XLeRobot code, not Strands).
- No mTLS, no ACL, no policy server for the POC. Flagged as follow-ups in `plan.md`.
- Head motors and wheel base are sent zeros during leader teleop; keyboard/gamepad base control comes later.
- No `pip install strands` (unrelated PyPI package); always `strands-robots`.

## Open questions (answer when convenient; CP0-CP1 proceed regardless)

1. Pi access: hostname/IP, SSH user, and is XLeRobot software already installed and calibrated there?
2. Which arm is left vs right among the two CH343 boards (or I determine it by unplugging in CP1).
3. GitHub repo name: keep `Jacob-Brokloff/robots` or rename (e.g. `jacere-strands-robots`)?
4. VM OS preference (default Ubuntu 24.04) and whether the Proxmox bridge is on `192.168.1.0/24`.
5. RunPod model/GPU budget preference (default: one 48 GB GPU, Qwen3-32B-AWQ).

## Verification

- CP3 is the acceptance test: physical leader motion → follower motion over WiFi, started from a container.
- `strands-robots doctor` on desktop and VM; dashboard reachable on the VM; agent smoke prompt in CP5.
- No unit tests added; upstream `hatch run test` is not run (fork adds only deploy files and scripts).

## Checkpoint status

| Checkpoint | Status | Notes |
|---|---|---|
| CP0 Fork and scaffold | **done** | Fork `Jacob-Brokloff/robots` created by Jacob; `origin` pushed. `doctor` runs in the container. |
| CP1 Leader arms | **done** | 5B79017318 = left, 5B90040979 = right (EEPROM homing offsets match the existing calibrations). Calibrations copied to `leader_left.json` / `leader_right.json`; `teleop_xlerobot.py --check-leaders` prints both arms. |
| CP2 Pi host | **done** | Pi `Woodside` 192.168.1.114, **2-wheel** XLeRobot, calibration `woodside`. 2026-10-25 16:48: after the C300 USB outputs were power-cycled (which also rebooted the Pi), both follower buses answered (port1 ids 1-8, port2 ids 1-6, 9, 10). Woodside's guarded `maintenance stop` then succeeded, and `xlerobot-host` started, restored calibration and opened ZMQ 5555/5556 (reachable from the desktop). Earlier dead left bus: the C300 port/PD negotiation had dropped 12 V; fixed by toggling the station's USB outputs. |
| CP3 Wireless teleop (POC milestone) | **ready, waiting on Jacob's "go"** | Desktop and host verified; follower read back over WiFi (leader-vs-follower gaps up to 33 units on shoulder pan). `teleop_xlerobot.py` now glides 3 s from the follower's pose to the leaders' before following live, and holds the head where it is. |
| CP4 Proxmox VM | **done** | VM 102 `strands-control` (192.168.1.82). Docker, fork at `~/robots`, dashboard + Zenoh hub up on 8090/7447. VM's `robot_mesh peers` lists the desktop's `xlerobot_2wheels_client` peer. Tailscale skipped (LAN only); follow-up. |
| CP5 RunPod LLM | **done except motion** | Pod `strands-vllm` (A40, $0.60/hr), vLLM 0.11.0 + Qwen3-32B-AWQ, reached over the VM's SSH tunnel. The agent on the VM answered "list the robots on the mesh" correctly via `robot_mesh`. A gated motion reaching the Pi waits on CP3. |
| CP6 Docs / CLAUDE.md | **done for what has landed** | Hosts, buses, calibrations, tunnel, commands recorded. |

## Corrections found while implementing (2026-10-25)

- Cross-host mesh with auth off needs `STRANDS_MESH_I_KNOW_THIS_IS_INSECURE=1` as well as
  `STRANDS_MESH_LOCAL_DEV=true` (LOCAL_DEV alone only covers loopback). In `.env.example`.
- Dashboard default port is **8090**, not 8000, and binding 0.0.0.0 is refused unless a passkey is
  enrolled or `DASHBOARD_AUTH_TOKEN` is set.
- `lerobot_robot_xlerobot` does not export `XLerobotClient`, so `xlerobot_client` cannot be built from
  it. Fixed by `deploy/xlerobot_client/` (plugin `lerobot_robot_xlerobot_client`), not by vendoring.
- XLeRobot client needs `pyzmq`, which neither strands-robots nor the plugin declares; the image adds it.
- `SOLeaderConfig` has no `id`; `bi_so_leader` names arm calibrations `{id}_left` / `{id}_right`.
- The robot is the 2-wheel build, not the 3-omniwheel `xlerobot`. Its plugin exports its client and
  its host takes `--robot.id/--robot.port1/--robot.port2`; on this Pi port1 must be 5B8E114351.
- The Pi already runs Woodside LeLab, which holds the motor buses. The XLeRobot host can only
  run while that supervisor is stopped.
- The RunPod vLLM sits behind an SSH tunnel from the VM, not the public proxy, so no API key needed.
- Follow-ups: mTLS/ACL on the mesh, Tailscale, keyboard/gamepad base control, a pod-restart
  script that refreshes the tunnel's POD_HOST/POD_PORT.

## Hand-off notes for the next session

- Working directory: `/home/jacob-jbit/Documents/jacere-robotics/Strands_Fork` (git repo, `main`).
- Image: `docker compose -f deploy/desktop/docker-compose.yml build` -> `strands-xlerobot:latest` (~7 GB, CPU torch).
- `deploy/.env` exists on the desktop and the VM (gitignored); the VM's holds the dashboard token.
- Next step: Jacob decides whether to stop `woodside-supervisor` for CP3; then run the Pi commands in CLAUDE.md.
- The RunPod pod bills $0.60/hr while running; stop it in the console when idle.
- Update the status table above and `CLAUDE.md` as each checkpoint lands. Keep this file as the single hand-off doc.
