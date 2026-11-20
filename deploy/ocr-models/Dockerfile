FROM scratch

ARG SOURCE_REPOSITORY
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.title="SmartScan 离线 OCR 模型制品" \
      org.opencontainers.image.description="PaddleOCR 官方 PP-OCRv6 small 检测与识别模型的未转换离线封装" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.smartscan.artifact.kind="offline-ocr-models" \
      io.smartscan.artifact.version="PP-OCRv6-small-v1"

COPY package/ /models/ocr/
