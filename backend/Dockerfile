FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && \
    apt-get install -y default-jre-headless && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Enable bytecode compilation for faster container startup times
ENV UV_COMPILE_BYTECODE=1

# Force uv to use the system Python environment (prevents creating a .venv)
ENV UV_SYSTEM_PYTHON=1

COPY pyproject.toml uv.lock* ./

RUN uv pip install -r pyproject.toml

COPY . .
