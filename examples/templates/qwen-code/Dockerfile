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
    wget \
    ripgrep \
    jq \
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

# Install qwen-code CLI (locked version)
RUN npm install -g @qwen-code/qwen-code@0.23.0

# Create Python virtual environment and install packages
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
    dashscope \
    "openai>=1.0" \
    httpx \
    rich
RUN pip install --no-cache-dir serverless-sandbox

# Pre-configure qwen-code for non-interactive / env-based auth
RUN mkdir -p /root/.qwen && \
    echo '{"security":{"auth":{"selectedType":"env-based"}},"core":{"nonInteractive":true}}' \
    > /root/.qwen/settings.json

# Install the fc-deploy skill for qwen-code
RUN mkdir -p /root/.qwen/skills/fc-deploy && \
    cat > /root/.qwen/skills/fc-deploy/SKILL.md << 'SKILL_EOF'
---
name: fc-deploy
description: 分析项目结构，安装依赖，构建，启动服务
---
# FC Sandbox 部署
1. 扫描 /workspace 确定项目类型和框架
2. 安装依赖 (pip install / npm install / go mod download)
3. 如需构建则执行构建命令
4. 启动服务并验证端口可达
5. 报告部署结果（JSON 格式：{"status", "url", "port", "logs"}）
SKILL_EOF

# Set environment variables — actual keys injected at runtime
ENV DASHSCOPE_API_KEY=""
ENV WORKSPACE="/workspace"
ENV OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
ENV OPENAI_MODEL="qwen3-coder-plus"

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

CMD ["python", "commands.py"]
