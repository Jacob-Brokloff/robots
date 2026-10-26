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
| CP3 Wireless teleop (POC milestone) | **done** | 2026-10-25 ~17:10, Jacob at the robot: `teleop_xlerobot.py --duration 120` from the desktop container glided 3 s to the leaders' pose, then followed live over WiFi. Strands result: 3600 frames, 0 errors, 0 slew rejections, 30.0 Hz over 120 s; Jacob confirmed the follower tracked the leaders smoothly. |
| CP4 Proxmox VM | **done** | VM 102 `strands-control` (192.168.1.82). Docker, fork at `~/robots`, dashboard + Zenoh hub up on 8090/7447. VM's `robot_mesh peers` lists the desktop's `xlerobot_2wheels_client` peer. Tailscale skipped (LAN only); follow-up. |
| CP5 RunPod LLM | **done, motion blocked by design** | Pod `strands-vllm` (A40) served Qwen3-32B-AWQ via the VM tunnel; the VM agent answered robot questions and sent gated mesh commands. Agent `stop` reached the robot peer. An agent `execute` with the bounded `nudge` policy passed the operator gate (Jacob typed y at `Approve? [y/N]`) but the robot refused it: "the sample carried no publisher session id". Strands only accepts remote motion from an attributed sender, which needs mesh mTLS. Nothing moved. **Pod stopped 2026-10-25 ~17:30 ($0.00/hr; its vLLM install is gone).** |
| CP6 Docs / CLAUDE.md | **done** | CLAUDE.md has hosts, buses, calibrations, tunnel, commands and gotchas; this table is current. |

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
- Both XLeRobot clients define `connect(self)`, but Strands calls `robot.connect(False)`; every live
  teleop frame failed until the shim plugin accepted (and ignored) `calibrate`. The glide, which calls
  the client directly, did move the follower over WiFi (left pan 22.8 -> 3.4).
- Right leader's 5 V supply still sags (gripper id 6 flags undervoltage on connect); the script retries the connect. A better 5 V/3 A adapter is the real fix.
- Follow-ups: a policy server for agent-driven motion, mTLS/ACL on the mesh, Tailscale, keyboard/gamepad base control, a pod-restart
  script that refreshes the tunnel's POD_HOST/POD_PORT.

## State at hand-off (2026-10-25 ~17:30)

| Thing | State | Turn it back on |
|---|---|---|
| RunPod pod `strands-vllm` | **stopped**, $0.00/hr, no volume (vLLM + model cache wiped) | Start it in the RunPod console, then on the pod: `uv venv` + `uv pip install vllm==0.11.0 transformers==4.57.1` in `/workspace/vllm-venv` and run `/workspace/serve.sh` (CLAUDE.md). Update `POD_HOST`/`POD_PORT` for the VM tunnel. |
| VM `runpod-vllm-tunnel` | **disabled** | `sudo systemctl enable --now runpod-vllm-tunnel` on the VM once the pod is up |
| VM dashboard + Zenoh hub (102, 192.168.1.82) | running, idle | already up (`restart: unless-stopped`) |
| Desktop dashboard | **running** at http://localhost:8090, passkey enrolled by Jacob | `docker compose -f deploy/desktop/docker-compose.yml up -d dashboard` |
| Pi `xlerobot-host` | **stopped** | `ssh xlerobot 'systemctl --user stop woodside-supervisor && systemctl --user start xlerobot-host'` |
| Pi `woodside-supervisor` | **running, RECOVERY_REQUIRED**: the host left the follower torque on; Woodside will not cut it on its own | Jacob supports the arms and clears recovery from the Woodside desktop app |

## Phase 2: VLA on RunPod, control loop on the Pi, sim in the container (planned 2026-10-26)

### Why

The Qwen3/vLLM agent of CP5 was only the chat and tool-calling layer of a Strands Agent; it never
produced motion, and Jacob does not want LLM-driven robots. Direction for phase 2:

- Motion comes from a **VLA served on RunPod**. Nothing policy-related runs locally; the only local
  compute in the loop is a **control loop on the Pi**. The Qwen/vLLM path is retired.
- **Tailscale** on Pi, VM, desktop and pod. Replaces the SSH tunnel and carries the PolicyServer
  WebSocket (plain ws by design) and Zenoh.
- **MuJoCo sim in the desktop container**, viewed through the dashboard (Devices panel spawns a
  registry robot, MJPEG stream at 12 fps; `strands_robots/dashboard/routes_sim.py`). The VM has
  no GPU and stays the mesh hub.
- **XLeRobot sim model**: upstream `simulation/mujoco/xlerobot.xml` first (3-omniwheel), then a
  **2-wheel variant** matching the real robot.

### Which VLA

**pi0.5 first, SmolVLA as the fallback on the same dataset.** XLeRobot's docs cover ACT (single
arm), SmolVLA (bimanual drawer and zipper tasks from ~20 episodes, three cameras) and pi0.5 (dual
arm, run by a community member through an openpi fork; dataset `xuweiwu/bimanual-toy-box-cleanup`,
no scores). Outside XLeRobot a HF team reports pi0.5 beating SmolVLA on SO-101 across four tasks
with ~10x fewer training steps. The openpi fork is not needed: lerobot 0.6.1 ships `pi05`
(`lerobot/pi05_base`), Strands `lerobot_local` handles pi0/pi0.5 (32-D action truncation, language
tokens, RTC) and `TrainSpec` takes `policy_type="pi05"` with `method="lora"`. The Pi's lerobot
already has the module. pi0.5 is 3B-class, so LoRA on the A40 (48 GB); if it does not fit, swap
`base_model="lerobot/smolvla_base"`, `policy_type="smolvla"` in the same spec.

### Facts verified 2026-10-26

- Hardware `Robot.run_policy(policy_object)` / `start_task(policy_provider="ws://...")` run the
  policy **inside the robot process**. No mesh sender attribution is involved, so the mTLS blocker
  from CP5 does not apply to this path.
- `RemotePolicy` (`strands-robots[inference]`, websockets only) dials `PolicyServer` on 8765 and
  mirrors `requires_images`, chunking and RTC. The server binds 127.0.0.1 unless `host="0.0.0.0"`;
  one client at a time; no TLS (tailnet).
- The 2-wheel plugin's `XLerobot2WheelsConfig.cameras` defaults to RealSense + two USB cams, so the
  host should already put frames in observations (verify). Pi 5, 8 GB, Python 3.13, torch 2.11 cpu
  in `~/xlerobot-runtime`; plugin source at `~/xlerobot-source/software/plugins/`. `strands-robots`
  needs Python >= 3.12.
- Registry overlay `user_robots.json` merges over `robots.json`; non-Menagerie sim robots download
  with `asset.source: {type: github, repo, subdir}` (`strands_robots/assets/download.py` ~L853).
  Only `github` and `menagerie` sources exist, so the 2-wheel MJCF lives in this fork on GitHub and
  is pulled the same way.
- Embodiments: `create_policy(..., embodiment=<inline dict>)` works for a robot
  `embodiments.json` does not know; no package edit.
- Hardware robots do not implement `start_recording`; on hardware, recording is lerobot's own
  `lerobot-record` (Strands wraps it as `lerobot_teleoperate(action="start", dataset_*=...)`).
- XLeRobot `xlerobot.xml` joints: `Rotation_L/R, Pitch_L/R, Elbow_L/R, Wrist_Pitch_L/R,
  Wrist_Roll_L/R, Jaw_L/R, head_pan_joint, head_tilt_joint`; base `slide_joint_x/y, hinge_joint_z`
  plus three omni-wheel hinges; `scene.xml` includes it; meshes under `assets/`.
- The sim is upstream code already in this fork (`strands_robots/simulation/mujoco/`); the image
  just omits the `sim-mujoco` extra, which is why `doctor` shows MuJoCo FAILs in the container.

### Target architecture

```
[RunPod pod, Tailscale]                     [Pi Woodside, Tailscale]
  PolicyServer :8765                          xlerobot-host (as today, ZMQ 5555/5556 on loopback)
  lerobot_local pi05 fine-tune   <--ws-->     xlerobot-control: Robot("xlerobot_2wheels_client",
  (A40; training also here)                     remote_ip=127.0.0.1, mesh=True)
                                                 + create_policy("ws://pod:8765") -> run_policy
                                                         | zenoh 7447 (tailnet)
[Desktop]                                    [VM strands-control]
  leaders + robot-client (teleop, recording)   zenoh hub + dashboard (fleet view, e-stop)
  dashboard + MuJoCo sim (container, EGL)
```

### Repo changes (fork only; upstream package untouched)

```
deploy/Dockerfile                 + sim-mujoco extra, mesa EGL libs
deploy/desktop/docker-compose.yml + /dev/dri, MUJOCO_GL=egl on dashboard; new `sim` service for scripts/examples
deploy/strands/user_robots.json   + "xlerobot" (upstream MJCF) and "xlerobot_2wheels" (fork MJCF) sim entries
deploy/sim/xlerobot_2wheels/      2-wheel MJCF (xlerobot_2wheels.xml, scene.xml; meshes from the upstream download)
deploy/pi/control/                install.sh (uv venv ~/strands-control), xlerobot-control.service, strands-control.env.example
deploy/runpod/                    bootstrap.sh (uv venv, strands-robots[lerobot,inference] + lerobot[pi], tailscale userspace),
                                  serve_policy.sh, train.sh
scripts/pi_control.py             the Pi loop: client robot + remote policy + run_policy; --dry-run prints obs keys and frame shapes
scripts/serve_nudge.py            PolicyServer around scripts/nudge_policy.py (first remote motion, served from the VM)
scripts/serve_policy.py           PolicyServer(lerobot_local, inline embodiment) reading POLICY_* env
scripts/train_pi05.py             TrainSpec wrapper (pi05 LoRA; smolvla fallback by env)
scripts/record_episodes.sh        lerobot-record through xlerobot_2wheels_client + bi_so_leader
CLAUDE.md                         tailnet table, port 8765, new services, pod bootstrap, one-liners
```

### Checkpoints (in order; update the status table as each lands)

**CP7. Tailscale.** Install on Pi, VM, desktop (installed, logged out) and the pod (userspace:
`tailscaled --tun=userspace-networking`, `tailscale up --ssh`). Each `tailscale up` needs Jacob to
approve the login URL. Record tailnet names/IPs in CLAUDE.md. Disable `runpod-vllm-tunnel` on the VM
(leave the unit file). Zenoh: VM listens as now; desktop and Pi `ZENOH_CONNECT=tcp/<vm-tailnet-ip>:7447`.
Done when: `tailscale ping` works pairwise and the VM dashboard still lists the desktop peer.

**CP8. Sim in the desktop container.** Dockerfile: add `sim-mujoco` to the extras and apt
`libegl1 libgl1-mesa-dri libegl-mesa0`. Compose `dashboard`: `devices: /dev/dri`, `MUJOCO_GL=egl`,
`group_add: [video, render]`. New compose service `sim` (same image, no serial devices) for
`python examples/01_sim_hello_world.py` and `strands-robots doctor`. Image grows a few hundred MB.
Done when: `doctor` passes the MuJoCo and GL rows in the container, and the dashboard Devices panel
spawns `so101` and streams it.

**CP9. XLeRobot upstream MJCF registered.** `user_robots.json` entry `xlerobot`: `category
mobile_manip`, `asset: {dir: "xlerobot", model_xml: "xlerobot.xml", scene_xml: "scene.xml", source:
{type: github, repo: Vector-Wangel/XLeRobot, subdir: simulation/mujoco}}` (pin the Dockerfile's ref
if `_download_from_github` accepts one), `joint_labels` `Rotation_L -> left_arm_shoulder_pan`, ...,
`Jaw_L -> left_arm_gripper`, `head_pan_joint -> head_motor_1`, `head_tilt_joint -> head_motor_2`,
a `gripper` block for the two jaws, `spawn_position` z from the wheel radius.
Done when: `Robot("xlerobot", mode="sim")` builds, `get_robot_state` lists the 14 arm/head joints
with those labels, and the dashboard spawns and streams it.

**CP10. 2-wheel sim variant.** `deploy/sim/xlerobot_2wheels/xlerobot_2wheels.xml`: the upstream model
with the three omni wheels, `slide_joint_x/y` and the omni tendons removed; a free joint on the
base, two drive wheels (`left_wheel`, `right_wheel` hinges with velocity actuators) and a caster;
arms and head unchanged. Mesh references resolve to the STLs the CP9 download placed in the asset
cache (decide symlink vs. path after reading how `dir`/`subdir` lay out on disk). Registered as
`xlerobot_2wheels` with `source: {type: github, repo: Jacob-Brokloff/robots, subdir:
deploy/sim/xlerobot_2wheels}` and `hardware.lerobot_type: xlerobot_2wheels_client`, so sim and
real share one name and joint labels; `x.vel`/`theta.vel` map onto wheel velocities using the
plugin's wheel radius and track.
Done when: it builds, drives forward and turns under a mock base command, and the embodiment
used in CP14 resolves identically in sim and real.

**CP11. Pi control loop with a bounded policy.** `deploy/pi/control/install.sh`: `uv venv
~/strands-control` (Python 3.13), the fork from a clone at `~/robots` with
`.[lerobot,mesh,inference]`, `deploy/xlerobot_client`, the two XLeRobot plugins from
`~/xlerobot-source` (`--no-deps`, as `deploy/pi/install.sh` does), `pyzmq`, CPU torch.
`scripts/pi_control.py`: `Robot("xlerobot_2wheels_client", mode="real", remote_ip="127.0.0.1",
mesh=True, peer_id="woodside")`, policy from `POLICY_ENDPOINT` (`ws://...`), `--instruction`,
`--duration` (default 10 s), `--dry-run` (connect, print observation keys and camera frame shapes,
exit), logs `avg_inference_ms`, stops on SIGTERM via `stop_task`. `xlerobot-control.service`: user
unit, `After=xlerobot-host`, `EnvironmentFile=%h/strands-control.env`, not enabled. First remote
motion: `scripts/serve_nudge.py` (`PolicyServer` around `scripts/nudge_policy.py`) on the VM.
Done when: a nudge served over the network moves the left arm a few degrees and returns, `stop`
from the dashboard/mesh halts it, and the dry run shows three camera frames in the observation.
Jacob at the robot for any motion; the host still needs `woodside-supervisor` stopped.

**CP12. Record the dataset.** `scripts/record_episodes.sh`: `lerobot-record
--robot.type=xlerobot_2wheels_client --robot.remote_ip=<pi> --teleop.type=bi_so_leader ...
--dataset.repo_id=Jacob-Brokloff/xlerobot_<task> --dataset.single_task="..."
--dataset.num_episodes=50 --dataset.fps=30` from the desktop container (frames come from the
host). Fixed head angle and lighting (XLeRobot's docs stress both). `HF_TOKEN` in `deploy/.env`;
push to the Hub. One bimanual table task first. `verify_dataset`.
Done when: 50 episodes, 3 cameras, 12-D or 14-D state/action on the Hub.

**CP13. Train pi0.5 on RunPod.** `deploy/runpod/bootstrap.sh` on a pod with a network volume (the
old pod lost its install when stopped). `scripts/train_pi05.py`: `TrainSpec(dataset_repo_id=...,
base_model="lerobot/pi05_base", method="lora", lora_r=16, steps=10_000, global_batch_size sized to
48 GB, val_episodes=2, extra={"policy_type": "pi05"})`, `create_trainer("lerobot_local")`.
`validate()` needs `q01..q99` stats for pi05; compute them first if the recorder did not. Push the
checkpoint to the Hub. Fallback: SmolVLA, same spec.
Done when: the checkpoint loads through `create_policy("lerobot_local", ...)` on the pod and
`get_actions` returns a chunk on a recorded observation.

**CP14. Serve and run.** `scripts/serve_policy.py`: `PolicyServer(policy_provider="lerobot_local",
policy_config={"pretrained_name_or_path": ..., "embodiment": <inline dict: state/action keys in
plugin order, degrees, gripper indices, obs_rename head/left/right -> the checkpoint's image
features>}, host=<tailnet ip>, port=8765)`. Pi `xlerobot-control` points at it, `duration`
bounded, Jacob at the robot with Woodside's e-stop and the dashboard fleet stop. Measure
`avg_inference_ms` over the internet and size `control_frequency` (pi0.5 chunks absorb ~300 ms).
Done when: the robot performs the recorded task from the pi0.5 checkpoint with the policy only on
RunPod and the loop only on the Pi. Record success over 10 trials here.

**CP15. Docs.** CLAUDE.md: tailnet table, 8765, new services, pod bootstrap, train/serve
one-liners; mark the vLLM/Qwen rows retired; this status table.

### Phase 2 status

| Checkpoint | Status | Notes |
|---|---|---|
| CP7 Tailscale | planned | |
| CP8 Sim in the desktop container | planned | |
| CP9 XLeRobot upstream MJCF | planned | |
| CP10 2-wheel sim variant | planned | |
| CP11 Pi control loop + nudge | planned | |
| CP12 Dataset | planned | |
| CP13 Train pi0.5 | planned | |
| CP14 Serve and run | planned | |
| CP15 Docs | planned | |

### Risks

- pi0.5 LoRA on one A40 should fit at small batch in bf16; otherwise SmolVLA.
- Internet round trip pod to Pi; chunked policies absorb it, a WiFi hiccup stalls a chunk. `duration`
  and the host's 500 ms watchdog bound the damage.
- Pod bills $0.60/hr running; a network volume is ~$0.07/GB/month. Stop the pod when idle.
- `xlerobot-host` still conflicts with Woodside. No `BYPASS_TOOL_CONSENT` is needed on this path.

### Running phase 2 (one prompt, one block per session)

Jacob runs phase 2 as a sequence of fresh sessions. Every session gets the same prompt:

```
Read CLAUDE.md and plan.md, then run the next phase 2 block as "Running phase 2" in plan.md says.
```

The agent then does exactly this:

1. Read the phase 2 status table. The **next block** is the lowest-numbered block in the table
   below whose checkpoints are not all `done`. If every block is done, say so and stop.
2. Do that block's checkpoints in order, verifying each done-when before starting the next one.
   Obey the block's gate line at all times. Never start a checkpoint from a later block.
3. If a done-when cannot be met, write why in the status table (`blocked: <reason>`) and stop
   the block there; do not skip ahead.
4. Finish by updating the status table and CLAUDE.md for what landed, committing on `main`
   with one commit per checkpoint (`CP<n>: <what landed>`), and reporting: what passed, what did
   not, and what Jacob must do by hand before the next block. Then stop. Do not ask whether to
   continue into the next block.

After the report, Jacob reads the status table diff, does any by-hand item, adds a line to the
table or the hand-off section for anything he changed himself, closes the session, and opens a
fresh one with the same prompt.

| Block | Checkpoints | Gate line |
|---|---|---|
| 1 | CP8, CP9, CP10, plus the **files only** for CP11 (`deploy/pi/control/`, `scripts/pi_control.py`, `scripts/serve_nudge.py`) and CP13 (`deploy/runpod/`, `scripts/serve_policy.py`, `scripts/train_pi05.py`) | Do not touch the robot, the Pi's services, Tailscale or the pod. Mark CP11 and CP13 `files written` in the table, not `done`. |
| 2 | CP7 | Jacob approves each Tailscale login URL you print; wait for him at each host. Never run `tailscale up` with a pre-auth key you invented. |
| 3 | CP11 (run) | Jacob is at the robot with the e-stop. Before any command that moves the arm, say what it will do and wait for his yes. Stop `woodside-supervisor` and start `xlerobot-host` only after he confirms the arms are supported. |
| 4 | CP12 | Jacob drives the leaders. Confirm the task text, episode count and head angle with him first; announce each episode start and stop. |
| 5 | CP13 (run) | Give the pod cost estimate (hours x $/hr) and get a yes before training. Stop the pod when the block ends, even on failure. |
| 6 | CP14, CP15 | Same gate as block 3, plus: confirm the pod is up and serving before the Pi loop is started. Stop the pod when the block ends. |

Blocks 2 to 6 need Jacob present; block 1 does not. Block 2 may run before block 1 if Jacob is at
the machines first; nothing in block 1 depends on it.

### Parked from phase 1

Dashboard teleop button and device profiles for `xlerobot_2wheels_client` / `bi_so_leader`
(`routes_mesh.py`, `device_manager.py`); robot cameras surfaced in the dashboard; mesh mTLS
(only needed for agent-issued `execute`, not for the Pi loop); right leader 5 V/3 A adapter.

## Hand-off notes for the next session

- Working directory: `/home/jacob-jbit/Documents/jacere-robotics/Strands_Fork` (git repo, `main`).
- Image: `docker compose -f deploy/desktop/docker-compose.yml build` -> `strands-xlerobot:latest` (~7 GB, CPU torch).
- `deploy/.env` exists on the desktop and the VM (gitignored); the VM's holds the dashboard token.
- POC complete; see "State at hand-off" above for what is running. Phase 2 (VLA on RunPod, Pi
  control loop, sim) is planned above and not started; begin at CP7/CP8.
- C300 gotcha: if a bus goes silent, toggle the station's USB outputs (this also reboots the Pi) and re-run Woodside's guarded `maintenance stop` before starting the host.
- The RunPod pod bills $0.60/hr while running; stop it in the console when idle.
- Update the status table above and `CLAUDE.md` as each checkpoint lands. Keep this file as the single hand-off doc.
