"""The robot's Strands peer on the Pi, and the control loop that runs policies through it (CP11/CP14).

    python scripts/pi_control.py serve                           # the `woodside` peer (xlerobot-control.service)
    python scripts/pi_control.py observe                         # observation keys + frame shapes, via the peer
    python scripts/pi_control.py run --instruction "..." --duration 10
    python scripts/pi_control.py stop

``serve`` owns the one client of ``xlerobot-host`` (ZMQ on 127.0.0.1:5555/5556) for as long as it runs. The
host has a single observation PUSH socket, which round-robins between connected clients, so the dashboard
view and the policy loop have to share one process: this one. It joins the mesh as ``woodside`` (state,
cameras at ``STRANDS_MESH_CAMERA_HZ``, fleet ``stop``) and listens on a local Unix socket
(``PI_CONTROL_SOCKET``, default ``$XDG_RUNTIME_DIR/strands-control.sock``) for the other subcommands.
``run`` asks it to run the policy at ``POLICY_ENDPOINT`` (a ``ws://`` PolicyServer: ``scripts/serve_nudge.py``
on the VM, ``scripts/serve_policy.py`` on the pod) with ``Robot.run_policy``, one rollout at a time, and
prints the result; Ctrl+C / SIGTERM on ``run`` sends ``stop``.

Env (``~/strands-control.env``; flags win): POLICY_ENDPOINT, POLICY_INSTRUCTION, POLICY_DURATION,
CONTROL_FREQUENCY, ROBOT_REMOTE_IP, MESH_PEER_ID, XLEROBOT_TYPE, ROBOT_CAMERAS (the host's
``deploy/pi/cameras.json``: the client drops frames whose names it does not know), PI_CONTROL_SOCKET.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import socketserver
import statistics
import threading
import time
from typing import Any

DEFAULT_TYPE = "xlerobot_2wheels"  # registry name with both the sim model and the real client (hardware.lerobot_type), so the twin button spawns the sim
DEFAULT_CAMERAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "pi", "cameras.json")
DEFAULT_SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "strands-control.sock")


def _describe(value: Any) -> str:
    shape = getattr(value, "shape", None)
    if shape is not None:
        return f"array{tuple(shape)} {getattr(value, 'dtype', '')}".strip()
    return f"{type(value).__name__} {value!r}"[:80]


def _client_is_calibrated(robot: Any) -> None:
    """The plugin client's ``is_calibrated`` is a bare ``pass`` (None), which Strands' connect gate refuses.

    Calibration belongs to the host: ``xlerobot-host`` restores ``woodside.json`` onto the motors at connect.
    lerobot's contract for the property is "always True if not applicable", so say so for the client class.
    """
    cls = type(robot.robot)
    if cls.__name__.endswith("Client") and cls.__dict__.get("is_calibrated") is not None:
        cls.is_calibrated = property(lambda self: True)


# Measured base velocity below these is wheel-encoder noise on a robot standing still (theta.vel read
# ~0.9 deg/s at rest).
VEL_DEADBAND = {"x.vel": 0.01, "theta.vel": 2.0}  # m/s, deg/s


def _clean_observation(robot: Any) -> None:
    """Make the client's observations read still when the robot is still, for the mesh and the dashboard.

    * Drop ``observation.state`` (the 16 keys again, as one vector): Strands takes every non-camera key as a
      joint, so it went onto the mesh state topic as a 17th "joint".
    * Zero measured base velocities inside ``VEL_DEADBAND``. The dashboard calls a peer moving when any recent
      change exceeds 5% of the largest recent change, so constant encoder noise on a still robot read as
      "arm is MOVING with no task".
    """
    client = robot.robot
    inner = client.get_observation

    def get_observation() -> dict[str, Any]:
        obs = inner()
        obs.pop("observation.state", None)
        for key, band in VEL_DEADBAND.items():
            if key in obs and abs(obs[key]) < band:
                obs[key] = 0.0
        return obs

    client.get_observation = get_observation


def observe(robot: Any) -> dict[str, Any]:
    from strands_robots.bus_access import read_observation

    client = robot.robot
    obs = read_observation(client)
    return {
        "keys": {key: _describe(obs[key]) for key in sorted(obs)},
        "camera_frames": sum(getattr(v, "ndim", 0) >= 2 for v in obs.values()),
        "cameras_in_config": list(getattr(client.config, "cameras", {}) or {}),
    }


def _time_inference(policy: Any) -> list[float]:
    """Wrap ``policy.get_actions`` (instance attribute) and collect per-call wall time in ms.

    The hardware loop sends every camera frame whatever the policy's ``requires_images`` says. Three raw
    640x480 frames are ~3.7 MB per call on the wire, ~1 s over the Pi's WiFi (4 ms without), so frames are
    dropped here when the server says it does not need them.
    """
    samples: list[float] = []
    inner = policy.get_actions

    async def timed(observation_dict: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        if not policy.requires_images:
            observation_dict = {k: v for k, v in observation_dict.items() if getattr(v, "ndim", 0) < 2}
        t0 = time.perf_counter()
        try:
            return await inner(observation_dict, *args, **kwargs)
        finally:
            samples.append((time.perf_counter() - t0) * 1000.0)

    policy.get_actions = timed
    return samples


def run(robot: Any, endpoint: str, instruction: str, duration: float) -> dict[str, Any]:
    """One bounded rollout (blocking). ``robot.stop_task()`` from another thread or the mesh ends it early."""
    from strands_robots.policies import create_policy

    policy = create_policy(endpoint)
    samples = _time_inference(policy)
    result: dict[str, Any] = {"run": robot.run_policy(policy_object=policy, instruction=instruction, duration=duration)}
    result["inference_calls"] = len(samples)
    if samples:
        result["avg_inference_ms"] = round(statistics.fmean(samples), 1)
        result["p95_inference_ms"] = round(sorted(samples)[int(0.95 * (len(samples) - 1))], 1)
    return result


def serve(args: argparse.Namespace) -> None:
    from strands_robots import Robot

    cameras = None
    if args.cameras:
        with open(args.cameras) as f:
            cameras = json.load(f)
    robot = Robot(
        args.robot_type,
        cameras=cameras,
        mode="real",
        remote_ip=args.remote_ip,
        mesh=True,
        peer_id=args.peer_id,
        control_frequency=args.control_frequency,
    )
    _client_is_calibrated(robot)
    _clean_observation(robot)
    # Strands' own connect path (calibration gate, half-open rollback); rollouts reuse the open client, and the
    # mesh state and camera loops publish only while it is connected.
    ok, error = asyncio.run(robot._connect_robot())
    if not ok:
        raise SystemExit(f"connect failed: {error}")
    rollout = threading.Lock()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                request = json.loads(self.rfile.readline() or b"{}")
                reply = dispatch(request)
            except Exception as exc:  # noqa: BLE001 - one bad request must not take the peer down
                reply = {"error": f"{type(exc).__name__}: {exc}"}
            self.wfile.write((json.dumps(reply, default=str) + "\n").encode())

    def dispatch(request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        if op == "observe":
            return observe(robot)
        if op == "stop":
            return {"stop": robot.stop_task()}
        if op == "status":
            return {"status": robot.get_task_status(), "rollout_running": rollout.locked()}
        if op == "run":
            if not request.get("endpoint"):
                return {"error": "run needs an endpoint (ws://host:8765)"}
            if not rollout.acquire(blocking=False):
                return {"error": "a rollout is already running; stop it first"}
            try:
                print(f"run: {request['endpoint']} {request.get('duration')} s {request.get('instruction')!r}", flush=True)
                result = run(robot, request["endpoint"], request.get("instruction", ""), float(request["duration"]))
                print(f"run done: {json.dumps(result, default=str)[:500]}", flush=True)
                return result
            finally:
                rollout.release()
        return {"error": f"unknown op {op!r}"}

    if os.path.exists(args.socket):
        os.unlink(args.socket)
    old_umask = os.umask(0o077)
    server = socketserver.ThreadingUnixStreamServer(args.socket, Handler)
    os.umask(old_umask)
    server.daemon_threads = True

    def shutdown(signum: int, _frame: Any) -> None:
        print(f"signal {signum}: stop_task, shutting down", flush=True)
        robot.stop_task()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"peer {args.peer_id} up, cameras {list(cameras or {})}, socket {args.socket}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if os.path.exists(args.socket):
            os.unlink(args.socket)
        robot.cleanup()


def _ask(path: str, request: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        try:
            s.connect(path)
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise SystemExit(f"no peer at {path} ({exc}); is xlerobot-control running?") from exc
        s.sendall((json.dumps(request) + "\n").encode())
        with s.makefile("rb") as f:
            return json.loads(f.readline() or b"{}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    env = os.environ.get
    p.add_argument("command", choices=["serve", "observe", "run", "stop", "status"])
    p.add_argument("--socket", default=env("PI_CONTROL_SOCKET", DEFAULT_SOCKET))
    p.add_argument("--endpoint", default=env("POLICY_ENDPOINT"), help="run: ws://host:8765 PolicyServer")
    p.add_argument("--instruction", default=env("POLICY_INSTRUCTION", ""))
    p.add_argument("--duration", type=float, default=float(env("POLICY_DURATION", "10")), help="run: seconds (default 10)")
    p.add_argument("--control-frequency", type=float, default=float(env("CONTROL_FREQUENCY", "30")), help="Hz (host loops at 30)")
    p.add_argument("--remote-ip", default=env("ROBOT_REMOTE_IP", "127.0.0.1"), help="serve: xlerobot-host address")
    p.add_argument("--peer-id", default=env("MESH_PEER_ID", "woodside"))
    p.add_argument("--robot-type", default=env("XLEROBOT_TYPE", DEFAULT_TYPE))
    p.add_argument("--cameras", default=env("ROBOT_CAMERAS", DEFAULT_CAMERAS), help="serve: cameras.json ('' for none)")
    args = p.parse_args()

    if args.command == "serve":
        serve(args)
        return
    if args.command != "run":
        print(json.dumps(_ask(args.socket, {"op": args.command}), indent=2, default=str), flush=True)
        return
    if not args.endpoint:
        p.error("--endpoint or POLICY_ENDPOINT is required (ws://host:8765)")

    def stop(signum: int, _frame: Any) -> None:
        print(f"signal {signum}: stop", flush=True)
        _ask(args.socket, {"op": "stop"})

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    request = {"op": "run", "endpoint": args.endpoint, "instruction": args.instruction, "duration": args.duration}
    print(json.dumps(_ask(args.socket, request), indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
