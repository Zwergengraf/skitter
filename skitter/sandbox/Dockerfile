FROM ubuntu:latest

RUN useradd -m -s /bin/bash linuxbrew && \
    mkdir -p /home/linuxbrew/.linuxbrew && \
    chown -R linuxbrew:linuxbrew /home/linuxbrew

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash build-essential curl file git gnupg ca-certificates zip jq procps tmux \
    python3 python3-pip \
    nodejs npm && \
    curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg \
      https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" \
      > /etc/apt/sources.list.d/brave-browser-release.list && \
    apt-get update && apt-get install -y --no-install-recommends brave-browser && \
    su - linuxbrew -c 'NONINTERACTIVE=1 CI=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' && \
    printf '%s\n' '#!/usr/bin/env bash' \
      'set -euo pipefail' \
      'exec /usr/sbin/runuser -u linuxbrew -- /home/linuxbrew/.linuxbrew/bin/brew "$@"' \
      > /usr/local/bin/brew && \
    chmod +x /usr/local/bin/brew && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --break-system-packages fastapi uvicorn httpx pydantic playwright && \
    python3 -m playwright install --with-deps chromium

# Install UV from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Codex using Homebrew
RUN brew install codex
RUN mkdir -p /workspace/.codex
ENV CODEX_HOME=/workspace/.codex

RUN mkdir -p /tmp/tmux-sockets

WORKDIR /app

COPY skitter/sandbox/runner.py /app/runner.py

ENV SKITTER_WORKSPACE_ROOT=/workspace
ENV SKITTER_BROWSER_EXECUTABLE=/usr/bin/brave-browser
ENV HOMEBREW_PREFIX=/home/linuxbrew/.linuxbrew
ENV HOMEBREW_CELLAR=/home/linuxbrew/.linuxbrew/Cellar
ENV HOMEBREW_REPOSITORY=/home/linuxbrew/.linuxbrew/Homebrew
ENV HOMEBREW_NO_ANALYTICS=1
ENV HOMEBREW_NO_AUTO_UPDATE=1
ENV PATH=/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:$PATH

EXPOSE 9080

CMD ["python3", "/app/runner.py"]
