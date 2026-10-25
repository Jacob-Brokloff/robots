"""Teleoperate a wireless XLeRobot from two SO-101 leader arms through Strands.

Runs on the desktop (robot-client container). The follower is ``xlerobot_client``,
which talks ZMQ to ``xlerobot_host`` on the Pi; nothing about the robot is wired here.

    python scripts/teleop_xlerobot.py                 # teleop (needs PI_IP)
    python scripts/teleop_xlerobot.py --check-leaders # CP1: print leader joints, no robot
    python scripts/teleop_xlerobot.py --two-devices   # fallback: two so101_leader devices

Env: PI_IP, LEFT_LEADER_PORT, RIGHT_LEADER_PORT (see deploy/.env.example).
"""

from __future__ import annotations

import argparse
import os
import time

from strands_robots import Robot, Teleoperator

# Head and base are not driven from the leader arms in the POC; hold them still.
_HOLD = {"head_motor_1.pos": 0.0, "head_motor_2.pos": 0.0, "x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}


def _bimanual_leader():
    from lerobot.teleoperators.so_leader import SOLeaderConfig

    return Teleoperator(
        "bi_so_leader",
        id="leader",  # lerobot names the arms' calibrations leader_left / leader_right
        left_arm_config=SOLeaderConfig(port=os.environ["LEFT_LEADER_PORT"]),
        right_arm_config=SOLeaderConfig(port=os.environ["RIGHT_LEADER_PORT"]),
    )


def bimanual_map(action: dict) -> dict:
    """``left_shoulder_pan.pos`` -> ``left_arm_shoulder_pan.pos`` (same for right), plus holds."""
    out = {k.replace("left_", "left_arm_", 1).replace("right_", "right_arm_", 1): v for k, v in action.items()}
    out.update(_HOLD)
    return out


def _prefix_map(prefix: str, hold: bool):
    def map_fn(action: dict) -> dict:
        out = {f"{prefix}{k}": v for k, v in action.items()}
        if hold:
            out.update(_HOLD)
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


def teleop(two_devices: bool, hz: float, mesh: bool) -> None:
    follower = Robot("xlerobot_client", mode="real", remote_ip=os.environ["PI_IP"], mesh=mesh)
    if two_devices:
        follower.attach_teleop(
            "so101_leader", name="left", port=os.environ["LEFT_LEADER_PORT"], id="leader_left",
            map_fn=_prefix_map("left_arm_", hold=True),
        )
        follower.attach_teleop(
            "so101_leader", name="right", port=os.environ["RIGHT_LEADER_PORT"], id="leader_right",
            map_fn=_prefix_map("right_arm_", hold=False),
        )
    else:
        follower.attach_teleop(_bimanual_leader(), name="leader", map_fn=bimanual_map)
    print(follower.teleoperate(hz=hz, block=True))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check-leaders", action="store_true", help="print leader joint positions and exit on Ctrl+C")
    p.add_argument("--two-devices", action="store_true", help="two so101_leader devices instead of bi_so_leader")
    p.add_argument("--hz", type=float, default=30.0, help="control rate (the Pi host loops at 30 Hz)")
    p.add_argument("--no-mesh", action="store_true", help="do not join the Zenoh mesh")
    args = p.parse_args()
    if args.check_leaders:
        check_leaders()
    else:
        teleop(args.two_devices, args.hz, mesh=not args.no_mesh)


if __name__ == "__main__":
    main()
