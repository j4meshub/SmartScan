FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY services ./services
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 smartscan && chown -R smartscan:smartscan /app
USER smartscan
EXPOSE 8000
CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

