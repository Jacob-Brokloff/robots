"""Serve the bounded nudge policy over the network, for the first remote motion (CP11; run on the VM).

    python scripts/serve_nudge.py --host <vm-tailnet-ip>            # ws://<host>:8765
    python scripts/serve_nudge.py --joint left_arm_gripper.pos --amount 10

Wraps ``scripts/nudge_policy.py`` (open one joint by ``amount`` over 1 s, hold 1 s, close back, then hold
the start pose; every other joint holds, base velocities 0) in a ``PolicyServer``. The Pi's
``scripts/pi_control.py`` dials it with ``POLICY_ENDPOINT=ws://<host>:8765``. One client at a time, no TLS:
bind a tailnet or loopback address, never a public one.
"""

from __future__ import annotations

import argparse

from nudge_policy import MAX_AMOUNT, NudgePolicy
from strands_robots.inference import PolicyServer


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1", help="bind address (default loopback; use the tailnet IP)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--joint", default="left_arm_gripper.pos")
    p.add_argument("--amount", type=float, default=10.0, help=f"joint units, at most {MAX_AMOUNT}")
    args = p.parse_args()
    server = PolicyServer(policy=NudgePolicy(joint=args.joint, amount=args.amount), host=args.host, port=args.port)
    print(f"serving nudge ({args.joint} +{args.amount}) on ws://{args.host}:{args.port}", flush=True)
    server.serve()


if __name__ == "__main__":
    main()
