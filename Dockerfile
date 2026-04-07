FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . /app

RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python --no-cache .

CMD ["python", "-m", "skitter.server"]
