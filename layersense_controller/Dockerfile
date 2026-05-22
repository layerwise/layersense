FROM manimcommunity/manim:v0.20.1 AS base


# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY layersense_domain/pyproject.toml layersense_domain/README.md layersense_domain/
COPY layersense_domain/src/ layersense_domain/src/

COPY layersense_persistence/pyproject.toml layersense_persistence/README.md layersense_persistence/
COPY layersense_persistence/src/ layersense_persistence/src/

COPY layersense_controller/pyproject.toml layersense_controller/README.md layersense_controller/
COPY layersense_controller/src/ layersense_controller/src/

# Install the controller into Manim's prebuilt virtualenv.
# The base image already contains Manim and its native/system dependencies,
# so resolving against /opt/venv reuses that stack instead of rebuilding it.
USER root
RUN uv pip install --python /opt/venv/bin/python --no-cache ./layersense_domain ./layersense_persistence ./layersense_controller

FROM base AS debug

RUN uv pip install --python /opt/venv/bin/python --no-cache debugpy

EXPOSE 8001
EXPOSE 5679

CMD ["uvicorn", "layersense_controller.main:app", "--host", "0.0.0.0", "--port", "8001"]

FROM base AS final

EXPOSE 8001

CMD ["uvicorn", "layersense_controller.main:app", "--host", "0.0.0.0", "--port", "8001"]
