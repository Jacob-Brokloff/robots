"""Inline embodiments for the 2-wheel XLeRobot, real and sim, sharing one key order (CP10/CP14).

    python scripts/xlerobot_embodiment.py        # check sim and real resolve to the same 14 arm/head keys

``REAL`` is the plugin's ``XLerobot2WheelsClient`` state/action order (16: left arm, right arm, head,
``x.vel``, ``theta.vel``) in the driver's own units, which is what ``lerobot-record`` writes and what a
checkpoint trained on that dataset speaks. ``sim()`` is the same order in the ``xlerobot_2wheels`` MJCF's
names, built from the registry's ``joint_labels``, so a key means the same joint in both. The base differs
by design: the real client speaks body-frame ``x.vel``/``theta.vel``, the sim has wheel velocity actuators;
``scripts/xlerobot_2wheels_sim.py:base_to_wheels`` converts. ``obs_rename`` maps the robot's camera names
onto the checkpoint's image features; set ``CAMERA_RENAME`` from the CP12 camera names.
"""

from __future__ import annotations

from typing import Any

ARM = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
JOINTS = [f"{side}_arm_{j}" for side in ("left", "right") for j in ARM] + ["head_motor_1", "head_motor_2"]
BASE = ["x.vel", "theta.vel"]

# Robot camera name -> checkpoint image feature. Filled in at CP12 once the camera names are fixed.
CAMERA_RENAME: dict[str, str] = {
    "head": "observation.images.head",
    "left_wrist": "observation.images.left_wrist",
    "right_wrist": "observation.images.right_wrist",
}

REAL: dict[str, Any] = {
    "name": "xlerobot_2wheels_real",
    "obs_rename": dict(CAMERA_RENAME),
    "state_keys": [f"{j}.pos" for j in JOINTS] + BASE,
    "action_keys": [f"{j}.pos" for j in JOINTS] + BASE,
    "dim_policy": "pad",
}


def sim(registry_name: str = "xlerobot_2wheels") -> dict[str, Any]:
    """The sim embodiment: the same arm/head order in MJCF names, wheel actuators last."""
    from strands_robots.registry import joint_labels

    by_label = {label: joint for joint, label in joint_labels(registry_name).items()}
    missing = [j for j in JOINTS if j not in by_label]
    if missing:
        raise ValueError(f"{registry_name} joint_labels lack {missing}")
    keys = [by_label[j] for j in JOINTS] + [by_label["base_left_wheel"], by_label["base_right_wheel"]]
    return {
        "name": f"{registry_name}_sim",
        "obs_rename": dict(CAMERA_RENAME),
        "state_keys": keys,
        "action_keys": keys,
        "dim_policy": "pad",
    }


def main() -> None:
    from strands_robots.policies.lerobot_local.embodiment import load_embodiment
    from strands_robots.registry import joint_labels

    real, simulated = load_embodiment(REAL), load_embodiment(sim())
    labels = joint_labels("xlerobot_2wheels")
    as_real = [f"{labels[k]}.pos" for k in simulated.state_keys[: len(JOINTS)]]
    same = as_real == real.state_keys[: len(JOINTS)]
    print("real:", real.state_keys)
    print("sim: ", simulated.state_keys)
    print("arm/head keys identical by label:", same)
    raise SystemExit(0 if same else 1)


if __name__ == "__main__":
    main()
