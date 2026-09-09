FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    build-essential \
    ripgrep \
    jq \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22.x via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create Python virtual environment and install packages
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
    "openai>=1.0" \
    rich \
    httpx

# Install Node.js packages globally
# @openai/codex: OpenAI Codex CLI (https://www.npmjs.com/package/@openai/codex)
RUN npm install -g @openai/codex

RUN pip install --no-cache-dir serverless-sandbox

# Set environment variables
ENV OPENAI_API_KEY=""
ENV CODEX_SANDBOX_MODE="true"
ENV WORKSPACE="/workspace"

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

CMD ["python", "commands.py"]
