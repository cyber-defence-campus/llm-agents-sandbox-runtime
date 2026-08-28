# Stage 1: Base image
FROM python:3.11-slim-bookworm

LABEL description="Minimal AI Agent Execution Environment"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_HOME="/opt/poetry" \
    VIRTUAL_ENV="/app/venv" \
    PATH="/opt/poetry/bin:/app/venv/bin:$PATH"

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    iproute2 \
    tmux \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Create venv
RUN python3 -m venv $VIRTUAL_ENV

WORKDIR /app

# Copy orchestrator dependency files
# Context is project root
COPY llm-agents-orchestrator/pyproject.toml llm-agents-orchestrator/poetry.lock ./llm-agents-orchestrator/

# Install dependencies
WORKDIR /app/llm-agents-orchestrator
RUN poetry install --without dev --no-root

# Copy orchestrator source
COPY llm-agents-orchestrator/src ./src

# Install the project itself
RUN poetry install --without dev

# Setup workspace
WORKDIR /workspace

# Copy entrypoint
COPY llm-agents-sandbox-runtime/containers/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set python path to include src
ENV PYTHONPATH=/app/llm-agents-orchestrator/src

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
