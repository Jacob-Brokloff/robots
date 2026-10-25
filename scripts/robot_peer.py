"""Put the XLeRobot on the Strands mesh so the VM agent can address it (desktop, robot-client container).

    python scripts/robot_peer.py              # until Ctrl+C
    python scripts/robot_peer.py --seconds 300

Registers the ``nudge`` policy provider, so an agent can ask for a small, operator-approved motion:
``robot_mesh(action="send", target=<peer>, command='{"action": "execute", "instruction": "nudge",
"policy_provider": "nudge", "policy_port": 1, "duration": 4}')``. ``policy_port`` is a placeholder the nudge
policy ignores; Strands' hardware path asks for one for any provider outside its static registry.
"""

from __future__ import annotations

import argparse
import os
import time

from nudge_policy import register
from strands_robots import Robot


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seconds", type=float, default=None, help="exit after N seconds (default: run until Ctrl+C)")
    args = p.parse_args()
    register()
    robot = Robot(os.environ.get("XLEROBOT_TYPE", "xlerobot_2wheels_client"), mode="real",
                  remote_ip=os.environ["PI_IP"], mesh=True)
    print("PEER", robot.mesh.peer_id, flush=True)
    deadline = None if args.seconds is None else time.monotonic() + args.seconds
    try:
        while deadline is None or time.monotonic() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
