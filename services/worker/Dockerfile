FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY services ./services
RUN pip install --no-cache-dir ".[vision]"
RUN useradd --create-home --uid 10001 smartscan && chown -R smartscan:smartscan /app
USER smartscan
CMD ["python", "-m", "services.worker.app.main"]

