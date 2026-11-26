FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0t64 libgomp1 \
    && install -d /usr/local/lib /usr/share/doc/smartscan-gl-runtime \
    && install -m 0644 "$(readlink -f /usr/lib/x86_64-linux-gnu/libGL.so.1)" /usr/local/lib/libGL.so.1 \
    && install -m 0644 "$(readlink -f /usr/lib/x86_64-linux-gnu/libGLX.so.0)" /usr/local/lib/libGLX.so.0 \
    && install -m 0644 "$(readlink -f /usr/lib/x86_64-linux-gnu/libGLdispatch.so.0)" /usr/local/lib/libGLdispatch.so.0 \
    && cp /usr/share/doc/libgl1/copyright /usr/share/doc/smartscan-gl-runtime/libgl1.copyright \
    && cp /usr/share/doc/libglx0/copyright /usr/share/doc/smartscan-gl-runtime/libglx0.copyright \
    && cp /usr/share/doc/libglvnd0/copyright /usr/share/doc/smartscan-gl-runtime/libglvnd0.copyright \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY services ./services
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[vision,ocr]" \
    && apt-get purge -y libxml2 \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 smartscan && chown -R smartscan:smartscan /app
USER smartscan
CMD ["python", "-m", "services.worker.app.main"]

