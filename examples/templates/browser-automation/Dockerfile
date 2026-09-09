FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Install additional system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    xvfb \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
    "playwright>=1.40.0" \
    beautifulsoup4 \
    lxml \
    httpx \
    Pillow
RUN pip install --no-cache-dir serverless-sandbox

# Install Playwright browsers (Chromium only for smaller image size)
RUN python3 -m playwright install chromium \
    && python3 -m playwright install-deps chromium

# Set environment variables
ENV DISPLAY=:99
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

CMD ["python3", "commands.py"]
