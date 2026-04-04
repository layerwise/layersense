FROM manimcommunity/manim:v0.20.1 AS base


# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy package files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install the controller into Manim's prebuilt virtualenv.
# The base image already contains Manim and its native/system dependencies,
# so resolving against /opt/venv reuses that stack instead of rebuilding it.
USER root
RUN uv pip install --python /opt/venv/bin/python --no-cache .

ENV LAYERSENSE_SCENES_DIR=/scenes
ENV LAYERSENSE_ARTIFACTS_DIR=/artifacts

FROM base AS debug

RUN uv pip install --python /opt/venv/bin/python --no-cache debugpy

EXPOSE 8001
EXPOSE 5679

CMD ["uvicorn", "layersense_controller.main:app", "--host", "0.0.0.0", "--port", "8001"]

FROM base AS final

EXPOSE 8001

CMD ["uvicorn", "layersense_controller.main:app", "--host", "0.0.0.0", "--port", "8001"]
