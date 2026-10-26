"""The control loop on the Pi: the 2-wheel client robot driven by a policy served over the network (CP11/CP14).

    python scripts/pi_control.py --dry-run                       # connect, print observation keys + frame shapes
    python scripts/pi_control.py --instruction "..." --duration 10

Runs next to ``xlerobot-host`` (ZMQ on 127.0.0.1:5555/5556), joins the mesh as ``woodside`` so the
dashboard / fleet ``stop`` reaches it, and runs the policy at ``POLICY_ENDPOINT`` (a ``ws://`` PolicyServer:
``scripts/serve_nudge.py`` on the VM first, ``scripts/serve_policy.py`` on the pod later) with
``Robot.run_policy``, in this process. SIGTERM / Ctrl+C stop the task through ``stop_task``.

Env (``~/strands-control.env`` under ``xlerobot-control.service``; flags win): POLICY_ENDPOINT,
POLICY_INSTRUCTION, POLICY_DURATION, CONTROL_FREQUENCY, ROBOT_REMOTE_IP, MESH_PEER_ID, XLEROBOT_TYPE,
ROBOT_CAMERAS (the host's ``deploy/pi/cameras.json``: the client drops frames whose names it does not know).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import threading
import time
from typing import Any

from strands_robots import Robot
from strands_robots.policies import create_policy

DEFAULT_TYPE = "xlerobot_2wheels_client"
DEFAULT_CAMERAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "pi", "cameras.json")


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


def dry_run(robot: Any) -> None:
    client = robot.robot
    if not client.is_connected:
        client.connect()
    try:
        obs = client.get_observation()
        frames = {k: v for k, v in obs.items() if getattr(v, "ndim", 0) >= 2}
        print(f"observation: {len(obs)} keys, {len(frames)} camera frame(s)")
        for key in sorted(obs):
            print(f"  {key}: {_describe(obs[key])}")
        print("cameras in config:", list(getattr(client.config, "cameras", {}) or {}))
    finally:
        client.disconnect()


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
    policy = create_policy(endpoint)
    samples = _time_inference(policy)
    result: dict[str, Any] = {}

    def work() -> None:
        result["run"] = robot.run_policy(policy_object=policy, instruction=instruction, duration=duration)

    def stop(signum: int, _frame: Any) -> None:
        print(f"signal {signum}: stop_task", flush=True)
        robot.stop_task()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker = threading.Thread(target=work, name="pi-control", daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(0.2)

    result["inference_calls"] = len(samples)
    if samples:
        result["avg_inference_ms"] = round(statistics.fmean(samples), 1)
        result["p95_inference_ms"] = round(sorted(samples)[int(0.95 * (len(samples) - 1))], 1)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    env = os.environ.get
    p.add_argument("--endpoint", default=env("POLICY_ENDPOINT"), help="ws://host:8765 PolicyServer")
    p.add_argument("--instruction", default=env("POLICY_INSTRUCTION", ""))
    p.add_argument("--duration", type=float, default=float(env("POLICY_DURATION", "10")), help="seconds (default 10)")
    p.add_argument("--control-frequency", type=float, default=float(env("CONTROL_FREQUENCY", "30")), help="Hz (host loops at 30)")
    p.add_argument("--remote-ip", default=env("ROBOT_REMOTE_IP", "127.0.0.1"), help="xlerobot-host address")
    p.add_argument("--peer-id", default=env("MESH_PEER_ID", "woodside"))
    p.add_argument("--cameras", default=env("ROBOT_CAMERAS", DEFAULT_CAMERAS), help="cameras.json ('' for none)")
    p.add_argument("--no-mesh", action="store_true", help="do not join the Zenoh mesh")
    p.add_argument("--dry-run", action="store_true", help="connect, print observation keys and frame shapes, exit")
    args = p.parse_args()

    cameras = None
    if args.cameras:
        with open(args.cameras) as f:
            cameras = json.load(f)
    robot = Robot(
        env("XLEROBOT_TYPE", DEFAULT_TYPE),
        cameras=cameras,
        mode="real",
        remote_ip=args.remote_ip,
        mesh=not args.no_mesh,
        peer_id=args.peer_id,
        control_frequency=args.control_frequency,
    )
    _client_is_calibrated(robot)
    if args.dry_run:
        dry_run(robot)
        return
    if not args.endpoint:
        p.error("--endpoint or POLICY_ENDPOINT is required (ws://host:8765)")
    print(json.dumps(run(robot, args.endpoint, args.instruction, args.duration), indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
