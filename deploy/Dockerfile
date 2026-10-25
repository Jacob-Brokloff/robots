# Strands Robots image for the XLeRobot POC (desktop robot-client and VM agent/dashboard).
# Build context is the repo root:  docker compose -f deploy/desktop/docker-compose.yml build
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
        git libgl1 libglib2.0-0 ffmpeg netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

ENV UV_SYSTEM_PYTHON=1 \
    UV_TORCH_BACKEND=cpu \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    STRANDS_BASE_DIR=/strands \
    HF_HOME=/root/.cache/huggingface

WORKDIR /opt/strands
COPY . /opt/strands

# .git is not in the build context, so hatch-vcs gets the version from here.
ARG STRANDS_VERSION=0.0.0+jacere
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${STRANDS_VERSION}

# The fork itself, with the extras the POC needs. CPU torch: nothing here runs a policy.
RUN uv pip install -e ".[lerobot,mesh,dashboard,serial]" "strands-agents[openai]" pyzmq

# XLeRobot lerobot plugin (xlerobot / xlerobot_client robot types), pinned.
ARG XLEROBOT_REF=b017b5e6354bd9f61f4247a920c72622ca0aade0
RUN git clone https://github.com/Vector-Wangel/XLeRobot.git /opt/XLeRobot \
    && git -C /opt/XLeRobot checkout "$XLEROBOT_REF" \
    && uv pip install --no-deps \
        /opt/XLeRobot/software/plugins/xlerobot_model \
        /opt/XLeRobot/software/plugins/lerobot_robot_xlerobot \
    && uv pip install -e /opt/strands/deploy/xlerobot_client

CMD ["strands-robots", "doctor"]
