FROM manimcommunity/manim:v0.20.1


# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy package files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install our package (no dev deps in prod)
USER root
RUN uv pip install --system --no-cache .

ENV LAYERSENSE_SCENES_DIR=/scenes
ENV LAYERSENSE_ARTIFACTS_DIR=/artifacts

EXPOSE 8001

CMD ["uvicorn", "layersense_controller.main:app", "--host", "0.0.0.0", "--port", "8001"]
