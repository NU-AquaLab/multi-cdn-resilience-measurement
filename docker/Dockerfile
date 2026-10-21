FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHROME_BINARY=/usr/bin/chromium

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    chromium chromium-driver iptables sudo tshark ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/measure-tiktok
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir .

# Runtime credentials, cookies, and discovery output are supplied separately.
WORKDIR /work
ENTRYPOINT ["measure-tiktok"]
CMD ["--help"]
