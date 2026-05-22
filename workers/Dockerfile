FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY src ./src

ENV PYTHONPATH=/app

CMD ["uv", "run", "python", "-m", "src.main"]
