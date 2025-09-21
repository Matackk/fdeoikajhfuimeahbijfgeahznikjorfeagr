# Fly.io container for Telegram bot
FROM python:3.12-slim

# System deps (optional but useful)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY bot.py ./

# Runtime env
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    KEEPALIVE=1

# Create data dir for persistence (mounted via Fly volume)
RUN mkdir -p /data

# Use tini as init to handle signals cleanly
ENTRYPOINT ["/usr/bin/tini", "--"]

# Symlink persistence file to /data so restarts keep state if a volume is mounted
CMD ["/bin/sh","-c","ln -sf /data/bot_state.pickle /app/bot_state.pickle || true; python bot.py"]
