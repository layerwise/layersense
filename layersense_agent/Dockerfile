FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY README.md .
COPY src/ src/
COPY assets/ assets/

RUN uv pip install --system --no-cache .

ENV SCENES_DIR=/scenes

EXPOSE 8000

CMD ["uvicorn", "layersense_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
