FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY services ./services
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[vision,ocr]"
RUN useradd --create-home --uid 10001 smartscan && chown -R smartscan:smartscan /app
USER smartscan
CMD ["python", "-m", "services.worker.app.main"]

