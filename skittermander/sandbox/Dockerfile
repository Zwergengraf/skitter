FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates && \
    curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg \
      https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" \
      > /etc/apt/sources.list.d/brave-browser-release.list && \
    apt-get update && apt-get install -y --no-install-recommends brave-browser && \
    rm -rf /var/lib/apt/lists/* && \
    pip install fastapi uvicorn httpx pydantic playwright && \
    python -m playwright install --with-deps chromium

WORKDIR /app

COPY skittermander/sandbox/runner.py /app/runner.py

ENV SKITTER_WORKSPACE_ROOT=/workspace
ENV SKITTER_BROWSER_EXECUTABLE=/usr/bin/brave-browser

EXPOSE 9080

CMD ["python", "/app/runner.py"]
