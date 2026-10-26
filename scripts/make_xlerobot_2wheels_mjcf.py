#!/usr/bin/env python3
"""Derive the 2-wheel XLeRobot MJCF from the upstream 3-omniwheel model.

    python scripts/make_xlerobot_2wheels_mjcf.py <upstream simulation/mujoco dir> deploy/sim/xlerobot_2wheels

Upstream (Vector-Wangel/XLeRobot, simulation/mujoco/xlerobot.xml) drives the base with planar
slide/hinge joints and spins three omni wheels for show. The real robot is the 2-wheel build, so:

- the planar base joints, the omni tendons and the three drive-motor mounts (with their wheels) go;
- the frame box becomes visual only (massless, no contacts);
- the chassis gets a free joint, two drive wheels (``left_wheel`` / ``right_wheel`` hinges with
  velocity actuators) and two frictionless casters;
- the head gets position actuators (upstream leaves its joints unactuated);
- arms are unchanged; meshes are read from the upstream download (``../xlerobot/assets/``), so the
  ``xlerobot`` asset must be in the cache first.

Wheel geometry is the plugin's (``XLerobot2WheelsConfig``: wheel_radius 0.05 m, wheelbase 0.25 m),
so ``x.vel`` / ``theta.vel`` map onto the wheels as the hardware does:
left = (x - theta * wheelbase / 2) / r, right = (x + theta * wheelbase / 2) / r (theta in rad/s).
"""

from __future__ import annotations

import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

WHEEL_RADIUS = 0.05
WHEELBASE = 0.25
WHEEL_HALF_WIDTH = 0.0125
CASTER_RADIUS = 0.02
CASTER_X = 0.15
CASTER_LIFT = 0.002  # casters clear the floor by this much at rest, so the wheels carry the weight

BASE_JOINTS = {"slide_joint_x", "slide_joint_y", "hinge_joint_z"}
OMNI_MOUNTS = {"drive_motor_mount-v4-1", "drive_motor_mount-v4-2", "drive_motor_mount-v4-3"}
DROPPED_ACTUATORS = {"slider_actuator_x", "slider_actuator_y", "hinge_actuator_z", "wheel1", "wheel2", "wheel3"}


def _remove_children(parent: ET.Element, pred) -> int:
    gone = [c for c in parent if pred(c)]
    for c in gone:
        parent.remove(c)
    return len(gone)


def _wheel(name: str, y: float) -> ET.Element:
    body = ET.Element("body", name=f"{name}_link", pos=f"0 {y} 0")
    ET.SubElement(body, "joint", name=name, type="hinge", axis="0 1 0", damping="0.05")
    ET.SubElement(
        body,
        "geom",
        name=f"{name}_geom",
        type="cylinder",
        size=f"{WHEEL_RADIUS} {WHEEL_HALF_WIDTH}",
        euler="1.5708 0 0",
        mass="0.2",
        friction="1.5 0.005 0.0001",
        rgba="0.15 0.15 0.15 1",
    )
    return body


def build(model: ET.ElementTree) -> ET.ElementTree:
    root = model.getroot()
    root.set("model", "xlerobot_2wheels")
    root.find("compiler").set("meshdir", "../xlerobot/assets/")

    _remove_children(root, lambda c: c.tag == "tendon")

    chassis = root.find("./worldbody/body[@name='chassis']")
    # Wheel axles sit at the chassis origin, so the origin is one wheel radius above the floor.
    chassis.set("pos", f"0 0 {WHEEL_RADIUS}")
    assert _remove_children(chassis, lambda c: c.tag == "joint" and c.get("name") in BASE_JOINTS) == 3
    chassis.insert(0, ET.Element("freejoint", name="base_free"))
    # Upstream's translucent frame box has no mass, so MuJoCo gives it ~120 kg (density 1000). Harmless on
    # upstream's kinematic base; on a free base it would bury the casters. Keep it as a visual only.
    frame = next(c for c in chassis if c.tag == "geom" and c.get("type") == "box")
    frame.set("contype", "0")
    frame.set("conaffinity", "0")
    frame.set("mass", "0")

    plate = chassis.find("./body[@name='base_plate_layer1-v5-1']")
    assert _remove_children(plate, lambda c: c.tag == "body" and c.get("name") in OMNI_MOUNTS) == 3

    # Chassis frame: +x is forward (the arms' side), +y left. Casters are condim 1 (frictionless).
    at = 1 + sum(1 for c in chassis if c.tag in ("freejoint", "geom"))
    for i, el in enumerate(
        [
            _wheel("left_wheel", WHEELBASE / 2),
            _wheel("right_wheel", -WHEELBASE / 2),
            *(
                ET.Element(
                    "geom",
                    name=f"caster_{tag}",
                    type="sphere",
                    size=str(CASTER_RADIUS),
                    pos=f"{x:g} 0 {CASTER_RADIUS - WHEEL_RADIUS + CASTER_LIFT:g}",
                    condim="1",
                    mass="0.05",
                    rgba="0.6 0.6 0.6 1",
                )
                for tag, x in (("front", CASTER_X), ("rear", -CASTER_X))
            ),
        ]
    ):
        chassis.insert(at + i, el)

    act = root.find("actuator")
    assert _remove_children(act, lambda c: c.get("name") in DROPPED_ACTUATORS) == 6
    ctrl = 1.0 / WHEEL_RADIUS  # 1 m/s at the rim
    for side in ("left_wheel", "right_wheel"):
        act.append(ET.Element("velocity", name=side, joint=side, kv="5", ctrlrange=f"{-ctrl:g} {ctrl:g}"))
    for joint, frc in (("head_pan_joint", "0.32"), ("head_tilt_joint", "0.68")):
        rng = root.find(f".//joint[@name='{joint}']").get("range")
        act.append(
            ET.Element("position", name=joint, joint=joint, kp="5", dampratio="1", ctrlrange=rng, forcerange=f"-{frc} {frc}")
        )
    return model


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("upstream", type=Path, help="upstream simulation/mujoco directory")
    ap.add_argument("out", type=Path, help="output directory")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    model = build(ET.parse(args.upstream / "xlerobot.xml"))
    ET.indent(model, space="  ")
    out_xml = args.out / "xlerobot_2wheels.xml"
    header = f"<!-- Generated by scripts/make_xlerobot_2wheels_mjcf.py from upstream XLeRobot simulation/mujoco/xlerobot.xml; edit the script, not this file. -->\n"
    out_xml.write_text(header + ET.tostring(model.getroot(), encoding="unicode") + "\n")

    scene = (args.upstream / "scene.xml").read_text().replace("./xlerobot.xml", "./xlerobot_2wheels.xml")
    scene = scene.replace('model="xlerobot_scene"', 'model="xlerobot_2wheels_scene"')
    (args.out / "scene.xml").write_text(scene)
    shutil.copymode(args.upstream / "scene.xml", args.out / "scene.xml")
    print(f"wrote {out_xml} and {args.out / 'scene.xml'}")


if __name__ == "__main__":
    main()
