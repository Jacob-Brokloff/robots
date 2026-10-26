"""Write the real-to-sim joint map for the 2-wheel XLeRobot twin into ``deploy/strands/user_robots.json``.

    python scripts/make_xlerobot_teleop_map.py <woodside.json> [deploy/sim/xlerobot_2wheels/xlerobot_2wheels.xml]

A teleop frame (from ``leader-arms``, or anything speaking the real robot's keys) carries
``left_arm_shoulder_pan.pos`` .. on lerobot's -100..100 scale (gripper 0..100) over each servo's calibrated
range. The sim wants MJCF joint names in radians. Per joint the map is angle-true:

    arm:     q = center + sign * v / 200 * span      (center = middle of the MJCF range)
    gripper: q = sign * v / 100 * span               (0 = closed)

with ``span`` the follower's calibrated travel (``range_max - range_min`` ticks, 4096 per turn), the result
clamped to the MJCF range and slewed at most ``max_rate`` rad/s. ``SIGNS`` were set by rendering the robot's
folded rest pose and checking each joint live against the leaders in the dashboard. The block lands in the ``xlerobot_2wheels`` entry as
``teleop_from_real``, which the fork's mesh patch applies when a sim twin follows a leader.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "deploy" / "strands" / "user_robots.json"
DEFAULT_MJCF = Path(__file__).resolve().parent.parent / "deploy" / "sim" / "xlerobot_2wheels" / "xlerobot_2wheels.xml"

ARM = {  # MJCF joint suffix -> lerobot motor
    "Rotation": "shoulder_pan",
    "Pitch": "shoulder_lift",
    "Elbow": "elbow_flex",
    "Wrist_Pitch": "wrist_flex",
    "Wrist_Roll": "wrist_roll",
    "Jaw": "gripper",
}
# Upstream's ``*_L`` arm sits at chassis -y, i.e. on the robot's RIGHT with +x forward (see plan.md block 1
# notes), so the real left arm drives the ``*_R`` joints and vice versa. Seen live: left leader moved the twin's
# right arm.
SIDES = {"R": "left", "L": "right"}
SIGNS = {
    "Rotation": 1,
    "Pitch": -1,
    "Elbow": 1,
    "Wrist_Pitch": 1,
    "Wrist_Roll": 1,
    "Jaw": 1,
}


def mjcf_ranges(path: Path) -> dict[str, tuple[float, float]]:
    out = {}
    for tag in re.findall(r"<joint\b[^>]*>", path.read_text()):
        name, rng = re.search(r'name="([^"]+)"', tag), re.search(r'range="([^"]+)"', tag)
        if name and rng:
            lo, hi = map(float, rng.group(1).split())
            out[name.group(1)] = (lo, hi)
    return out


def build(calibration: dict, ranges: dict[str, tuple[float, float]]) -> dict:
    joints = {}
    for side_code, side in SIDES.items():
        for suffix, motor in ARM.items():
            name, key = f"{suffix}_{side_code}", f"{side}_arm_{motor}"
            cal = calibration[key]
            lo, hi = ranges[name]
            joints[name] = {
                "key": f"{key}.pos",
                "scale": "0_100" if motor == "gripper" else "m100_100",
                "span": round((cal["range_max"] - cal["range_min"]) * 2 * math.pi / 4096, 4),
                "center": 0.0 if motor == "gripper" else round((lo + hi) / 2, 4),
                "sign": SIGNS[suffix],
                "range": [lo, hi],
            }
    # rad/s per joint: folding the arms in one frame flips the sim base; any fold of 0.25 s or longer
    # (~14 rad/s) stays upright. 8 rad/s keeps up with a hand on the leaders.
    return {"max_rate": 8.0, "joints": joints}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    calibration = json.loads(Path(sys.argv[1]).read_text())
    mjcf = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MJCF
    registry = json.loads(REGISTRY.read_text())
    robots = registry.get("robots", registry)
    robots["xlerobot_2wheels"]["teleop_from_real"] = build(calibration, mjcf_ranges(mjcf))
    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
    print(f"wrote teleop_from_real ({len(robots['xlerobot_2wheels']['teleop_from_real']['joints'])} joints) to {REGISTRY}")


if __name__ == "__main__":
    main()
