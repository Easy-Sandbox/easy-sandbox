FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Install system packages including Python 3 and browser dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    xvfb \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir \
    "playwright>=1.40.0" \
    beautifulsoup4 \
    lxml \
    httpx \
    Pillow
COPY *.whl /tmp/
RUN if ls /tmp/*.whl 1>/dev/null 2>&1; then \
        pip3 install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl; \
    else \
        pip3 install --no-cache-dir easy-sandbox; \
    fi

# Install Playwright browsers (Chromium only for smaller image size)
RUN python3 -m playwright install chromium \
    && python3 -m playwright install-deps chromium

# Set environment variables
ENV DISPLAY=:99
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

CMD ["python3", "commands.py"]
