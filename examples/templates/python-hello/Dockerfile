FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Install serverless-sandbox SDK.
# When building locally via `sbox template build-local`, the SDK wheel
# is automatically injected into the build context as .whl file.
# Fallback: install from PyPI if the wheel is not present.
COPY *.whl /tmp/
RUN if ls /tmp/*.whl 1>/dev/null 2>&1; then \
        pip3 install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl; \
    else \
        pip3 install --no-cache-dir serverless-sandbox; \
    fi

WORKDIR /app
COPY commands.py .
EXPOSE 9000
CMD ["python3", "commands.py"]
