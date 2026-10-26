"""Fine-tune pi0.5 (LoRA) on the recorded XLeRobot dataset, on the RunPod pod (CP13).

    python scripts/train_pi05.py --check                 # download the dataset, validate the spec, exit
    python scripts/train_pi05.py                         # train, then push the checkpoint to HUB_MODEL_ID
    POLICY_TYPE=smolvla python scripts/train_pi05.py     # fallback: SmolVLA on the same dataset

Env (``deploy/runpod/train.sh`` sets the paths): DATASET_REPO_ID (required), POLICY_TYPE (pi05 | smolvla),
BASE_MODEL (default lerobot/pi05_base or lerobot/smolvla_base), STEPS (10000), BATCH_SIZE (8; raise
until the A40's 48 GB is full), LORA_R (16), VAL_EPISODES (2), DATA_ROOT, OUTPUT_DIR, HUB_MODEL_ID
(push target; empty = no push), HF_TOKEN.

pi0.5 normalizes state/action with quantiles, so the dataset needs q01..q99 in ``meta/stats.json``.
``--fix-quantiles`` runs lerobot's ``augment_dataset_quantile_stats`` on the local copy when they are missing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from strands_robots.training import TrainSpec, create_trainer

BASES = {"pi05": "lerobot/pi05_base", "smolvla": "lerobot/smolvla_base"}


def spec_from_env(data_root: Path) -> TrainSpec:
    env = os.environ.get
    ptype = env("POLICY_TYPE", "pi05")
    if ptype not in BASES:
        raise SystemExit(f"POLICY_TYPE must be one of {sorted(BASES)}, got {ptype!r}")
    name = env("DATASET_REPO_ID", "").split("/")[-1]
    return TrainSpec(
        dataset_repo_id=env("DATASET_REPO_ID"),
        dataset_root=str(data_root),
        base_model=env("BASE_MODEL", BASES[ptype]),
        output_dir=env("OUTPUT_DIR", f"/workspace/runs/{ptype}_{name}"),
        method="lora",
        lora_r=int(env("LORA_R", "16")),
        steps=int(env("STEPS", "10000")),
        global_batch_size=int(env("BATCH_SIZE", "8")),
        val_episodes=int(env("VAL_EPISODES", "2")),
        extra={"policy_type": ptype},
    )


def fetch_dataset(repo_id: str, root: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=repo_id, repo_type="dataset", local_dir=str(root))


def fix_quantiles(repo_id: str, root: Path) -> None:
    cmd = [sys.executable, "-m", "lerobot.scripts.augment_dataset_quantile_stats", f"--repo-id={repo_id}", f"--root={root}"]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def push(checkpoint: str, model_id: str) -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(model_id, repo_type="model", private=True, exist_ok=True)
    api.upload_folder(folder_path=checkpoint, repo_id=model_id, repo_type="model")
    print(f"pushed {checkpoint} -> https://huggingface.co/{model_id}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="download + validate only")
    p.add_argument("--fix-quantiles", action="store_true", help="add q01..q99 stats to the local copy if missing")
    args = p.parse_args()

    repo_id = os.environ.get("DATASET_REPO_ID")
    if not repo_id:
        p.error("DATASET_REPO_ID is required (e.g. Jacob-Brokloff/xlerobot_<task>)")
    data_root = Path(os.environ.get("DATA_ROOT", f"/workspace/datasets/{repo_id.split('/')[-1]}"))
    fetch_dataset(repo_id, data_root)

    spec = spec_from_env(data_root)
    trainer = create_trainer("lerobot_local")
    problems = trainer.validate(spec)
    if problems and args.fix_quantiles and any("quantile" in m for m in problems):
        fix_quantiles(repo_id, data_root)
        problems = trainer.validate(spec)
    for m in problems:
        print("PROBLEM:", m, flush=True)
    print(f"spec: {spec.extra['policy_type']} from {spec.base_model}, {spec.steps} steps, batch {spec.global_batch_size}, "
          f"lora_r {spec.lora_r}, out {spec.output_dir}", flush=True)
    if problems or args.check:
        raise SystemExit(1 if problems else 0)

    result = trainer.train(spec)
    print(f"train: {result.status} {result.message or ''}\n  checkpoint: {result.checkpoint_dir}\n  metrics: {result.metrics}", flush=True)
    if result.status != "success" or not result.checkpoint_dir:
        raise SystemExit(1)
    model_id = os.environ.get("HUB_MODEL_ID", "")
    if model_id:
        push(trainer.export(spec, result.checkpoint_dir), model_id)


if __name__ == "__main__":
    main()
