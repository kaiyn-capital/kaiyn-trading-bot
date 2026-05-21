FROM python:3.11-slim
LABEL org.opencontainers.image.source="https://github.com"

COPY --from=ghcr.io/astral-sh/uv:python3.11-bookworm-slim /usr/local/bin/uv /usr/local/bin/uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

ARG INSTALL_DEV=false

WORKDIR /app

COPY pyproject.toml uv.lock readme.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --locked --no-editable; else uv sync --locked --no-dev --no-editable; fi

COPY . .

CMD ["python", "-m", "app.main"]
