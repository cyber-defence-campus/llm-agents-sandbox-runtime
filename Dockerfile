FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install poetry

# Copy the manifest and lock before the source so the dependency layer is
# cached across source edits, as in the orchestrator image. Copying the whole
# service first invalidated the install layer on every change.
COPY llm-agents-sandbox-runtime/pyproject.toml /app/llm-agents-sandbox-runtime/pyproject.toml
COPY llm-agents-sandbox-runtime/poetry.lock /app/llm-agents-sandbox-runtime/poetry.lock

# Install Dependencies
WORKDIR /app/llm-agents-sandbox-runtime
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

# Now the rest of the service, and install it on top of the cached deps.
COPY llm-agents-sandbox-runtime /app/llm-agents-sandbox-runtime
RUN poetry install --no-interaction --no-ansi --only main

# Set PYTHONPATH to include src
ENV PYTHONPATH=/app/llm-agents-sandbox-runtime/src

CMD ["uvicorn", "sandbox_runtime.api:app", "--host", "0.0.0.0", "--port", "8000"]