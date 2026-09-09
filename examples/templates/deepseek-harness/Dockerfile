FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates \
    gnupg \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python 3.11 via deadsnakes PPA
RUN add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22.x via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create Python virtual environment and install packages
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
    "openai>=1.0" \
    httpx \
    rich
RUN pip install --no-cache-dir serverless-sandbox

# Set environment variables
ENV DEEPSEEK_API_KEY=""
ENV WORKSPACE="/workspace"

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

CMD ["python", "commands.py"]
