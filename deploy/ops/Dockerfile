ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY services ./services
COPY alembic.ini ./
COPY migrations ./migrations
COPY tools ./tools

RUN pip install --no-cache-dir . "pyyaml>=6.0,<7"
RUN useradd --create-home --uid 10001 smartscan && chown -R smartscan:smartscan /app

LABEL org.opencontainers.image.title="SmartScan 运维工具" \
      org.opencontainers.image.description="SmartScan 迁移、配置校验与备份恢复证据工具"

USER smartscan
ENTRYPOINT ["python"]
CMD ["-m", "services.api.app.migrations", "drift"]
