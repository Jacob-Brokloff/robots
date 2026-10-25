"""Teleoperate a wireless XLeRobot from two SO-101 leader arms through Strands.

Runs on the desktop (robot-client container). The follower is ``xlerobot_2wheels_client``
(``XLEROBOT_TYPE=xlerobot_client`` for the 3-omniwheel build), which talks ZMQ to the XLeRobot
host on the Pi; nothing about the robot is wired here.

    python scripts/teleop_xlerobot.py                 # teleop (needs PI_IP)
    python scripts/teleop_xlerobot.py --check-leaders # CP1: print leader joints, no robot
    python scripts/teleop_xlerobot.py --two-devices   # fallback: two so101_leader devices

Env: PI_IP, LEFT_LEADER_PORT, RIGHT_LEADER_PORT, XLEROBOT_TYPE (see deploy/.env.example).
"""

from __future__ import annotations

import argparse
import os
import time

from strands_robots import Robot, Teleoperator

DEFAULT_TYPE = "xlerobot_2wheels_client"


def _bimanual_leader():
    from lerobot.teleoperators.so_leader import SOLeaderConfig

    return Teleoperator(
        "bi_so_leader",
        id="leader",  # lerobot names the arms' calibrations leader_left / leader_right
        left_arm_config=SOLeaderConfig(port=os.environ["LEFT_LEADER_PORT"]),
        right_arm_config=SOLeaderConfig(port=os.environ["RIGHT_LEADER_PORT"]),
    )


_DRIVEN = ("left_arm_", "right_arm_")


def _holds(follower_keys, current: dict | None = None) -> dict:
    """Every follower key the leader arms do not drive: positions (head) held where they are, velocities (base) 0."""
    current = current or {}
    return {
        k: float(current.get(k, 0.0)) if k.endswith(".pos") else 0.0
        for k in follower_keys
        if not k.startswith(_DRIVEN)
    }


def bimanual_map_for(follower_keys, current: dict | None = None):
    """``left_shoulder_pan.pos`` -> ``left_arm_shoulder_pan.pos`` (same for right), plus holds."""
    hold = _holds(follower_keys, current)

    def map_fn(action: dict) -> dict:
        out = {k.replace("left_", "left_arm_", 1).replace("right_", "right_arm_", 1): v for k, v in action.items()}
        out.update(hold)
        return out

    return map_fn


def _prefix_map(prefix: str, hold: dict):
    def map_fn(action: dict) -> dict:
        out = {f"{prefix}{k}": v for k, v in action.items()}
        out.update(hold)
        return out

    return map_fn


def check_leaders() -> None:
    leader = _bimanual_leader()
    leader.connect()
    try:
        while True:
            a = leader.get_action()
            print("  ".join(f"{k}={v:7.2f}" for k, v in sorted(a.items())), flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        leader.disconnect()


def glide(client, follower_keys, seconds: float, hz: float) -> dict:
    """Move the follower smoothly from where it is to the leaders' pose, so live teleop starts without a jump.

    Each tick re-reads the leaders and commands a point that far along the way from the follower's start pose,
    so the leaders can be held still or moved during the glide. Returns the follower's start observation.
    """
    leader = _bimanual_leader()
    to_follower = bimanual_map_for(follower_keys)
    client.connect()
    leader.connect()
    try:
        start = client.get_observation()
        hold = _holds(follower_keys, start)
        steps = max(1, int(seconds * hz))
        print(f"gliding to the leaders' pose over {seconds:.0f}s", flush=True)
        for i in range(1, steps + 1):
            target = to_follower(leader.get_action())
            f = i / steps
            cmd = {k: start[k] + (v - start[k]) * f if k.startswith(_DRIVEN) and k in start else v for k, v in target.items()}
            cmd.update(hold)
            client.send_action(cmd)
            time.sleep(1 / hz)
        print("glide done; following the leaders live", flush=True)
        return start
    finally:
        leader.disconnect()
        client.disconnect()


def teleop(two_devices: bool, hz: float, mesh: bool, glide_s: float, duration: float | None) -> None:
    robot_type = os.environ.get("XLEROBOT_TYPE", DEFAULT_TYPE)
    follower = Robot(robot_type, mode="real", remote_ip=os.environ["PI_IP"], mesh=mesh)
    follower_keys = list(follower.robot.action_features)
    current = glide(follower.robot, follower_keys, glide_s, hz) if glide_s > 0 else {}
    if two_devices:
        follower.attach_teleop(
            "so101_leader", name="left", port=os.environ["LEFT_LEADER_PORT"], id="leader_left",
            map_fn=_prefix_map("left_arm_", hold=_holds(follower_keys, current)),
        )
        follower.attach_teleop(
            "so101_leader", name="right", port=os.environ["RIGHT_LEADER_PORT"], id="leader_right",
            map_fn=_prefix_map("right_arm_", hold={}),
        )
    else:
        follower.attach_teleop(_bimanual_leader(), name="leader", map_fn=bimanual_map_for(follower_keys, current))
    print(follower.teleoperate(hz=hz, block=True, duration=duration))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check-leaders", action="store_true", help="print leader joint positions and exit on Ctrl+C")
    p.add_argument("--two-devices", action="store_true", help="two so101_leader devices instead of bi_so_leader")
    p.add_argument("--hz", type=float, default=30.0, help="control rate (the Pi host loops at 30 Hz)")
    p.add_argument("--no-mesh", action="store_true", help="do not join the Zenoh mesh")
    p.add_argument("--glide", type=float, default=3.0, help="seconds to glide from the robot's pose to the leaders' (0 = skip)")
    p.add_argument("--duration", type=float, default=None, help="stop after N seconds (default: Ctrl+C)")
    args = p.parse_args()
    if args.check_leaders:
        check_leaders()
    else:
        teleop(args.two_devices, args.hz, mesh=not args.no_mesh, glide_s=args.glide, duration=args.duration)


if __name__ == "__main__":
    main()
