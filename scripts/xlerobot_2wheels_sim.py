"""Drive the 2-wheel XLeRobot sim with the real robot's base keys (CP10; ``sim`` compose service).

    python scripts/xlerobot_2wheels_sim.py            # settle, drive forward, turn; prints pose and checks
    python scripts/xlerobot_2wheels_sim.py --x 0.1 --theta 30 --seconds 3

``x.vel`` (m/s) and ``theta.vel`` (deg/s) become wheel speeds the way the plugin's
``XLerobot2Wheels._body_to_wheel_raw`` computes them, with its wheel_radius 0.05 m and wheelbase 0.25 m:
left = (x - theta * wheelbase / 2) / r, right = (x + theta * wheelbase / 2) / r (theta in rad/s).
Arms and head hold their start pose. Needs the ``xlerobot`` asset in the cache (the 2-wheel MJCF reads
its meshes) and ``xlerobot_2wheels`` from ``deploy/strands/user_robots.json``.
"""

from __future__ import annotations

import argparse
import math
from typing import Any

import numpy as np

from strands_robots import Robot

WHEEL_RADIUS = 0.05
WHEELBASE = 0.25
NAME = "xlerobot_2wheels"


def base_to_wheels(x_vel: float, theta_vel_deg: float) -> dict[str, float]:
    """``{"left_wheel", "right_wheel"}`` in rad/s for a base command in m/s and deg/s."""
    theta = math.radians(theta_vel_deg)
    return {
        "left_wheel": (x_vel - theta * WHEELBASE / 2) / WHEEL_RADIUS,
        "right_wheel": (x_vel + theta * WHEELBASE / 2) / WHEEL_RADIUS,
    }


def _pose(sim: Any) -> tuple[np.ndarray, float, float]:
    """Chassis world position, yaw (deg) and tilt from vertical (deg)."""
    model, data = sim._world._model, sim._world._data
    bid = next(i for i in range(model.nbody) if model.body(i).name.endswith("chassis"))
    pos = data.xpos[bid].copy()
    mat = data.xmat[bid].reshape(3, 3)
    yaw = math.degrees(math.atan2(mat[1, 0], mat[0, 0]))
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, mat[2, 2]))))
    return pos, yaw, tilt


def drive(sim: Any, x_vel: float, theta_deg: float, seconds: float) -> None:
    model = sim._world._model
    steps = max(1, round(seconds / model.opt.timestep))
    result = sim.send_action(base_to_wheels(x_vel, theta_deg), robot_name=NAME, n_substeps=steps)
    if result.get("status") != "success":
        raise RuntimeError(result)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--x", type=float, default=0.2, help="x.vel, m/s (default 0.2)")
    p.add_argument("--theta", type=float, default=45.0, help="theta.vel, deg/s (default 45)")
    p.add_argument("--seconds", type=float, default=2.0)
    args = p.parse_args()

    sim = Robot(NAME, mode="sim", mesh=False)
    drive(sim, 0.0, 0.0, 1.0)
    p0, yaw0, tilt0 = _pose(sim)
    print(f"settled: pos={np.round(p0, 3).tolist()} yaw={yaw0:.1f} tilt={tilt0:.1f}")

    drive(sim, args.x, 0.0, args.seconds)
    p1, yaw1, tilt1 = _pose(sim)
    heading = np.array([math.cos(math.radians(yaw0)), math.sin(math.radians(yaw0)), 0.0])
    fwd = float(np.dot(p1 - p0, heading))
    print(f"forward {args.x} m/s x {args.seconds}s: moved {fwd:.3f} m along heading (ideal {args.x * args.seconds:.3f}), "
          f"yaw drift {yaw1 - yaw0:+.1f}, tilt {tilt1:.1f}")

    drive(sim, 0.0, 0.0, 0.5)
    _, yaw2, _ = _pose(sim)
    drive(sim, 0.0, args.theta, args.seconds)
    p3, yaw3, tilt3 = _pose(sim)
    turned = (yaw3 - yaw2 + 180) % 360 - 180
    print(f"turn {args.theta} deg/s x {args.seconds}s: turned {turned:+.1f} deg (ideal {args.theta * args.seconds:+.1f}), "
          f"tilt {tilt3:.1f}")

    ok = (
        abs(p0[2] - WHEEL_RADIUS) < 0.02
        and tilt0 < 5
        and fwd > 0.5 * args.x * args.seconds
        and abs(yaw1 - yaw0) < 10
        and math.copysign(1, turned) == math.copysign(1, args.theta)
        and abs(turned) > 0.5 * abs(args.theta * args.seconds)
        and max(tilt1, tilt3) < 10
    )
    print("CHECK", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
