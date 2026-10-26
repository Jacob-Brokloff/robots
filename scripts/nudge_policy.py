"""A tiny, bounded "nudge" policy, so a Strands agent can trigger a real motion without a policy server.

On its first call it captures the robot's live pose. It then opens one joint (default the left gripper)
by ``amount`` over 1 s, holds 1 s, closes back over 1 s, and afterwards holds the start pose. Every other
joint is commanded to exactly where it started and every base velocity to 0, so nothing can jump.

Registered as provider ``nudge`` by :func:`register`; the robot peer (``scripts/robot_peer.py``) calls it.
"""

from __future__ import annotations

import math
import time
from typing import Any

from strands_robots.policies.base import Policy

MAX_AMOUNT = 15.0
_RAMP_S = 1.0
_HOLD_S = 1.0


class NudgePolicy(Policy):
    reads_instruction: bool = False
    instruction_free_actions: str | None = "a small open-and-close of one joint from the live pose"

    def __init__(self, joint: str = "left_arm_gripper.pos", amount: float = 10.0, **kwargs: Any) -> None:
        if not math.isfinite(float(amount)) or not 0 < float(amount) <= MAX_AMOUNT:
            raise ValueError(f"NudgePolicy: amount must be in (0, {MAX_AMOUNT}], got {amount!r}")
        self.joint = joint
        self.amount = float(amount)
        self.robot_state_keys: list[str] = []
        self._start: dict[str, float] | None = None
        self._t0 = 0.0

    @property
    def provider_name(self) -> str:
        return "nudge"

    @property
    def requires_images(self) -> bool:
        return False

    def set_robot_state_keys(self, robot_state_keys: list[str]) -> None:
        self.robot_state_keys = list(robot_state_keys)

    def reset(self, seed: int | None = None) -> None:
        self._start = None

    def _offset(self, t: float) -> float:
        if t < _RAMP_S:
            return self.amount * t / _RAMP_S
        if t < _RAMP_S + _HOLD_S:
            return self.amount
        if t < 2 * _RAMP_S + _HOLD_S:
            return self.amount * (1 - (t - _RAMP_S - _HOLD_S) / _RAMP_S)
        return 0.0

    async def get_actions(self, observation_dict: dict[str, Any], instruction: str, **kwargs: Any) -> list[dict[str, Any]]:
        keys = self.robot_state_keys or [k for k in observation_dict if k.endswith((".pos", ".vel"))]
        if self._start is None:
            self._start = {}
            for k in keys:
                v = observation_dict.get(k, observation_dict.get(f"{k}.pos"))
                if v is None:
                    raise ValueError(f"NudgePolicy: observation has no value for {k!r}; refusing to guess a pose")
                if getattr(v, "ndim", 0):
                    continue  # a packed vector, e.g. the 2-wheel client's ``observation.state``; not a joint
                self._start[k] = float(v)
            if not any(k in (self.joint, self.joint.removesuffix(".pos")) for k in self._start):
                raise ValueError(f"NudgePolicy: joint {self.joint!r} is not one of the robot's keys")
            self._t0 = time.monotonic()
        offset = self._offset(time.monotonic() - self._t0)
        action = {}
        for k, v in self._start.items():
            if k.endswith(".vel"):
                action[k] = 0.0
            elif k in (self.joint, self.joint.removesuffix(".pos")):
                action[k] = v + offset
            else:
                action[k] = v
        return [action]


def register() -> None:
    from strands_robots.policies import register_policy

    register_policy("nudge", lambda: NudgePolicy)
