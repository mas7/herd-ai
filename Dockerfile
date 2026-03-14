FROM python:3.12-slim

WORKDIR /app

# Install system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy source
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY config.yaml ./

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
