"""The two SO-101 leader arms as a Strands mesh peer, so the dashboard can teleop from them (desktop).

    docker compose -f deploy/desktop/docker-compose.yml up -d leader      # peer `leader-arms`, always on

The dashboard's teleop works between mesh peers: a follower card's "follow <peer>" points the follower's
``teleop_receive`` at a leader peer's input stream. That needs a leader peer with joints on the mesh which is
already publishing (no peer answers the dashboard's ``teleop/publish`` command), so this process:

* wraps ``bi_so_leader`` in a read-only lerobot ``Robot`` (``LeaderArms``): its observation is the leader
  joints, renamed ``left_shoulder_pan.pos`` -> ``left_arm_shoulder_pan.pos`` (and right) so they are the
  XLeRobot's own keys, and it refuses every action;
* joins the mesh as ``leader-arms`` (joints on the state topic, so the dashboard lists it as a leader);
* publishes the same renamed frames as teleop stream ``leader`` at ``--hz``.

Both the state probe and the publish loop read the bus through ``bus_lock`` on the one device. Followers:
``woodside`` (the real robot; moves) and its sim twin. Env: LEFT_LEADER_PORT, RIGHT_LEADER_PORT, ZENOH_CONNECT.
"""

from __future__ import annotations

import argparse
import signal
import threading
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from lerobot.robots.config import RobotConfig
from lerobot.robots.robot import Robot as LeRobotRobot
from strands_robots.bus_access import bus_lock
from strands_robots.hardware_robot import Robot as HardwareRobot
from strands_robots.mesh import init_mesh
from teleop_xlerobot import _bimanual_leader, _connect_leader

PEER_ID = "leader-arms"


def to_xlerobot_keys(action: dict[str, Any]) -> dict[str, float]:
    return {k.replace("left_", "left_arm_", 1).replace("right_", "right_arm_", 1): float(v) for k, v in action.items()}


@RobotConfig.register_subclass("xlerobot_leader_arms")
@dataclass
class LeaderArmsConfig(RobotConfig):
    pass


class LeaderArms(LeRobotRobot):
    """``bi_so_leader`` read as a robot: observation = leader joints in XLeRobot keys; no actions."""

    config_class = LeaderArmsConfig
    name = "xlerobot_leader_arms"

    def __init__(self, config: LeaderArmsConfig):
        super().__init__(config)
        self.leader = _bimanual_leader()

    @cached_property
    def observation_features(self) -> dict[str, type]:
        arm = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
        return {f"{side}_arm_{j}.pos": float for side in ("left", "right") for j in arm}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return bool(self.leader.is_connected)

    @property
    def is_calibrated(self) -> bool:
        return True  # leader_left / leader_right calibrations are loaded by bi_so_leader itself

    def connect(self, calibrate: bool = True) -> None:
        _connect_leader(self.leader)

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def get_observation(self) -> dict[str, Any]:
        with bus_lock(self):
            return to_xlerobot_keys(self.leader.get_action())

    # The teleop publish loop polls this; same lock and keys as the state probe.
    def get_action(self) -> dict[str, float]:
        return self.get_observation()

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("leader-arms is an input device; it takes no actions")

    def disconnect(self) -> None:
        if self.leader.is_connected:
            self.leader.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--peer-id", default=PEER_ID)
    p.add_argument("--hz", type=float, default=30.0, help="teleop stream rate (the Pi host loops at 30 Hz)")
    args = p.parse_args()

    device = LeaderArms(LeaderArmsConfig(id="leader"))
    device.connect()
    # The Robot() factory takes registry names only; this is what it does for a real robot, around an instance.
    robot = HardwareRobot(tool_name=args.peer_id, robot=device)
    robot.robot_name = LeaderArms.name
    robot.mesh = init_mesh(robot, peer_id=args.peer_id, peer_type="robot", mesh=True)
    if robot.mesh is None:
        raise SystemExit("mesh did not start; check ZENOH_CONNECT and the STRANDS_MESH_* flags")
    robot.peer_id = robot.mesh.peer_id
    print(robot.start_teleop_publish(device, device_name="leader", method="arm", hz=args.hz), flush=True)
    print(f"peer {args.peer_id} up: publishing teleop stream 'leader' at {args.hz} Hz", flush=True)

    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    done.wait()
    robot.stop_teleop()
    robot.cleanup()


if __name__ == "__main__":
    main()
