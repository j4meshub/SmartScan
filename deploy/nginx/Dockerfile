ARG NGINX_BASE_IMAGE
FROM ${NGINX_BASE_IMAGE}

LABEL org.opencontainers.image.title="SmartScan Web" \
      org.opencontainers.image.description="SmartScan H5、管理后台与内部文件发送入口"

COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY apps/h5 /var/www/h5
COPY apps/admin-web /var/www/admin
