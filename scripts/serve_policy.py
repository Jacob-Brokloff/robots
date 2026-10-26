"""Serve the fine-tuned checkpoint to the Pi's control loop, on the RunPod pod (CP14).

    python scripts/serve_policy.py --check       # load the checkpoint, run one chunk on a dataset frame, exit
    python scripts/serve_policy.py               # ws://$POLICY_HOST:8765, one client at a time, no TLS

``PolicyServer(policy_provider="lerobot_local")`` around POLICY_CHECKPOINT (Hub id or local path) with the
inline 2-wheel embodiment from ``scripts/xlerobot_embodiment.py`` (state/action keys in plugin order, driver
units, cameras renamed onto the checkpoint's image features). Bind the pod's tailnet IP, never 0.0.0.0 on
a public interface.

Env: POLICY_CHECKPOINT (required), POLICY_HOST (default 127.0.0.1), POLICY_PORT (8765), POLICY_DEVICE (cuda),
DATASET_REPO_ID / DATA_ROOT (``--check`` reads a recorded frame from it).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from xlerobot_embodiment import REAL

from strands_robots.inference import PolicyServer
from strands_robots.policies import create_policy


def policy_config() -> dict[str, Any]:
    checkpoint = os.environ.get("POLICY_CHECKPOINT")
    if not checkpoint:
        raise SystemExit("POLICY_CHECKPOINT is required (Hub id or local pretrained_model dir)")
    return {
        "pretrained_name_or_path": checkpoint,
        "embodiment": dict(REAL),
        "device": os.environ.get("POLICY_DEVICE", "cuda"),
    }


def recorded_observation() -> tuple[dict[str, Any], str]:
    """One frame of the training dataset as a robot observation (driver keys, HWC uint8 frames)."""
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    repo_id = os.environ["DATASET_REPO_ID"]
    ds = LeRobotDataset(repo_id, root=os.environ.get("DATA_ROOT"))
    item = ds[0]
    state = item["observation.state"].numpy()
    obs: dict[str, Any] = dict(zip(REAL["state_keys"], map(float, state)))
    for key, value in item.items():
        if key.startswith("observation.images."):
            chw = value.numpy()
            obs[key.removeprefix("observation.images.")] = (np.transpose(chw, (1, 2, 0)) * 255).astype(np.uint8)
    return obs, str(item.get("task", ""))


def check() -> None:
    policy = create_policy("lerobot_local", **policy_config())
    policy.set_robot_state_keys(REAL["state_keys"])
    obs, task = recorded_observation()
    chunk = asyncio.run(policy.get_actions(obs, task))
    print(f"chunk: {len(chunk)} actions, keys {list(chunk[0])[:4]}..., first {chunk[0]}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="load + one get_actions on a recorded frame, then exit")
    args = p.parse_args()
    if args.check:
        check()
        return
    host = os.environ.get("POLICY_HOST", "127.0.0.1")
    port = int(os.environ.get("POLICY_PORT", "8765"))
    server = PolicyServer(policy_provider="lerobot_local", policy_config=policy_config(), host=host, port=port)
    print(f"serving {os.environ['POLICY_CHECKPOINT']} on ws://{host}:{port}", flush=True)
    server.serve()


if __name__ == "__main__":
    main()
