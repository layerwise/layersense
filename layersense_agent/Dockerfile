FROM python:3.14-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY layersense_domain/pyproject.toml layersense_domain/README.md layersense_domain/
COPY layersense_domain/src/ layersense_domain/src/

COPY layersense_agent/pyproject.toml layersense_agent/README.md layersense_agent/
COPY layersense_agent/src/ layersense_agent/src/
COPY layersense_agent/assets/ layersense_agent/assets/

RUN uv pip install --system --no-cache ./layersense_domain ./layersense_agent

FROM base AS debug

RUN uv pip install --system --no-cache debugpy

EXPOSE 8000
EXPOSE 5678

CMD ["uvicorn", "layersense_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS final

EXPOSE 8000

CMD ["uvicorn", "layersense_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
