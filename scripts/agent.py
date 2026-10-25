"""Strands agent on the control-plane VM: LLM on RunPod (OpenAI-compatible vLLM), robots via the mesh.

    python scripts/agent.py                     # interactive REPL
    python scripts/agent.py "list robots on the mesh"

Env: OPENAI_BASE_URL, OPENAI_API_KEY, MODEL_ID, ZENOH_CONNECT (see deploy/.env.example).
Mesh motion (tell/send/broadcast/stop) still asks the operator at this terminal unless
STRANDS_MESH_HITL_ACTIONS or BYPASS_TOOL_CONSENT says otherwise.
"""

from __future__ import annotations

import os
import sys

from strands import Agent
from strands.models.openai import OpenAIModel

from strands_robots.tools import robot_mesh

SYSTEM_PROMPT = (
    "You operate robots on a Strands Robots Zenoh mesh. Use the robot_mesh tool: 'peers' to discover "
    "robots, 'status' for a summary, 'tell'/'send' to command one robot, 'stop' or 'emergency_stop' "
    "to halt. The XLeRobot appears as an xlerobot_client peer driven from a desktop. Prefer small, "
    "reversible motions and say what you are about to do before you do it."
)


def build_agent() -> Agent:
    model = OpenAIModel(
        client_args={"base_url": os.environ["OPENAI_BASE_URL"], "api_key": os.environ["OPENAI_API_KEY"]},
        model_id=os.environ.get("MODEL_ID", "Qwen/Qwen3-32B-AWQ"),
    )
    return Agent(model=model, tools=[robot_mesh], system_prompt=SYSTEM_PROMPT)


def main() -> None:
    agent = build_agent()
    if len(sys.argv) > 1:
        agent(" ".join(sys.argv[1:]))
        return
    while True:
        try:
            prompt = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if prompt:
            agent(prompt)


if __name__ == "__main__":
    main()
