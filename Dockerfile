FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

COPY . /app

CMD ["python", "-m", "skittermander.server"]
