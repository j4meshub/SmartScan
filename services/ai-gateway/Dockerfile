FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY services ./services
RUN pip install --no-cache-dir .
WORKDIR /app/services/ai-gateway
RUN useradd --create-home --uid 10001 smartscan && chown -R smartscan:smartscan /app
USER smartscan
EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]
