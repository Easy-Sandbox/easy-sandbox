FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22.x via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install OpenClaw globally
RUN npm install -g openclaw

# Install Python and easy-sandbox for command server
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir --break-system-packages easy-sandbox

# Set environment variables
ENV ANTHROPIC_API_KEY=""
ENV OPENAI_API_KEY=""
ENV WORKSPACE="/workspace"

# Expose Gateway port
EXPOSE 18789

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

CMD ["python3", "commands.py"]
