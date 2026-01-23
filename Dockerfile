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

# Copy Service Code
COPY llm-agents-sandbox-runtime /app/llm-agents-sandbox-runtime

# Install Dependencies
WORKDIR /app/llm-agents-sandbox-runtime
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Set PYTHONPATH to include src
ENV PYTHONPATH=/app/llm-agents-sandbox-runtime/src

CMD ["uvicorn", "sandbox_runtime.api:app", "--host", "0.0.0.0", "--port", "8000"]