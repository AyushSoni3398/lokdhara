# The API and the worker, for the local demo (docs/DEMO.md). Same image for both; the command
# differs. Ubuntu 24.04 gives the FFmpeg 6.1 that CI pins (docs/DEPLOYMENT.md).
FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY content ./content
RUN uv sync --locked --no-dev

# Never run as root; /data holds the local object store and is owned by this user.
RUN useradd --create-home lokdhara && mkdir -p /data && chown lokdhara /data
USER lokdhara
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
