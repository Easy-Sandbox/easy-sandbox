FROM node:20-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install global Node.js packages
RUN npm install -g yarn nodemon pm2

# Install Python and easy-sandbox for command server
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir --break-system-packages easy-sandbox

# Set environment variables
ENV NODE_ENV=production
ENV PORT=3000

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace
COPY commands.py .

EXPOSE 3000

CMD ["python3", "commands.py"]
