"""The XLeRobot 2-wheel host with cameras (CP11). Wraps the plugin's ``xlerobot_2wheels_host``.

    python xlerobot_host.py --robot.id=woodside --robot.port1=... --robot.port2=... --cameras cameras.json

At the pinned XLeRobot ref the plugin configures no cameras and its host CLI cannot set any, so this
builds ``XLerobot2WheelsConfig(cameras=...)`` from ``cameras.json`` (the same file the clients read,
``scripts/pi_control.py --cameras``) and runs the plugin's ``XLerobot2WheelsHost`` unchanged.
The JSON is name -> ``{"type": "opencv", "index_or_path", "width", "height", "fps"}``; head is the
D415's colour node (``/dev/video4``), read as a plain V4L2 camera, no pyrealsense2.
"""

from __future__ import annotations

import argparse
import json
import logging

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.robots.utils import ensure_safe_goal_position
from lerobot_robot_xlerobot_2wheels.config_xlerobot_2wheels import XLerobot2WheelsConfig, XLerobot2WheelsHostConfig
from lerobot_robot_xlerobot_2wheels.xlerobot_2wheels_host import XLerobot2WheelsHost

logger = logging.getLogger("xlerobot_host")


def load_cameras(path: str | None) -> dict[str, OpenCVCameraConfig]:
    if not path:
        return {}
    with open(path) as f:
        entries = json.load(f)
    cameras = {}
    for name, entry in entries.items():
        entry = dict(entry)
        if entry.pop("type", "opencv") != "opencv":
            raise ValueError(f"camera {name!r}: only type 'opencv' is supported here")
        cameras[name] = OpenCVCameraConfig(**entry)
    return cameras


def cap_relative_target(robot, max_step: float) -> None:
    """Clamp every commanded joint to ``max_step`` from where it is now, per command.

    The plugin's own ``max_relative_target`` path looks present positions up without the ``.pos`` suffix
    (``KeyError: 'left_arm_shoulder_pan.pos'``), so with it set the host refused every command. Same
    clamp (lerobot's ``ensure_safe_goal_position``), keys fixed, the plugin's option left at None.
    """
    inner = robot.send_action

    def send_action(action):
        goal = {k: v for k, v in action.items() if k.endswith(".pos")}
        if goal:
            present = {}
            for bus, motors in (
                (robot.bus1, robot.left_arm_motors + robot.head_motors),
                (robot.bus2, robot.right_arm_motors),
            ):
                present.update({f"{m}.pos": v for m, v in bus.sync_read("Present_Position", motors).items()})
            safe = ensure_safe_goal_position({k: (g, present[k]) for k, g in goal.items() if k in present}, float(max_step))
            action = {**action, **safe}
        return inner(action)

    robot.send_action = send_action


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--robot.id", dest="robot_id", default="xlerobot_2wheels")
    p.add_argument("--robot.port1", dest="port1", default="/dev/ttyACM0", help="left arm + head bus")
    p.add_argument("--robot.port2", dest="port2", default="/dev/ttyACM1", help="right arm + wheels bus")
    p.add_argument("--cameras", help="cameras.json; omit for no cameras")
    p.add_argument(
        "--robot.max_relative_target", dest="max_relative_target", type=float, default=None,
        help="cap each command's step from the present position, per joint (arm/head units); none by default",
    )
    p.add_argument("--host.connection_time_s", dest="connection_time_s", type=int, default=3600)
    p.add_argument("--host.max_loop_freq_hz", dest="max_loop_freq_hz", type=int, default=30)
    args = p.parse_args()

    cameras = load_cameras(args.cameras)
    logger.info("cameras: %s", {n: c.index_or_path for n, c in cameras.items()} or "none")
    robot_config = XLerobot2WheelsConfig(id=args.robot_id, port1=args.port1, port2=args.port2, cameras=cameras)
    host_config = XLerobot2WheelsHostConfig(
        connection_time_s=args.connection_time_s, max_loop_freq_hz=args.max_loop_freq_hz
    )
    host = XLerobot2WheelsHost(robot_config, host_config)
    if args.max_relative_target is not None:
        cap_relative_target(host.robot, args.max_relative_target)
    logger.info("max_relative_target: %s", args.max_relative_target)
    try:
        host.connect()
        host.run()
    except Exception:
        logger.exception("host error")
        host.stop()
        raise


if __name__ == "__main__":
    main()
