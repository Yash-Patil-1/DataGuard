# ──────────────────────────────────────────────────────────
# DataGuard — Dockerfile
# Multi-stage build for smaller final image
# ──────────────────────────────────────────────────────────

FROM python:3.11-slim AS builder

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Runtime Stage ────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (no build tools needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY dashboard.py .
COPY requirements.txt .

# Create data and reports directories
RUN mkdir -p data reports

# Expose Streamlit port
EXPOSE 8501

# Default: run the quality pipeline and generate data if needed
CMD ["bash", "-c", "\
    python src/data_generator.py 2>/dev/null || echo 'Data already exists'; \
    python src/validators.py; \
    python src/detectors.py; \
    echo '--- Pipeline Complete ---' \
"]
