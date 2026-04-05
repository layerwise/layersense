FROM python:3.14-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY README.md .
COPY src/ src/
COPY assets/ assets/

RUN uv pip install --system --no-cache .

FROM base AS debug

RUN uv pip install --system --no-cache debugpy

EXPOSE 8000
EXPOSE 5678

CMD ["uvicorn", "layersense_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS final

EXPOSE 8000

CMD ["uvicorn", "layersense_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
