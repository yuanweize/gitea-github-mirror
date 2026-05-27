FROM python:3.12-alpine

LABEL maintainer="yuanweize"
LABEL description="Bulk mirror all GitHub repositories to a self-hosted Gitea instance"
LABEL org.opencontainers.image.source="https://github.com/yuanweize/gitea-github-mirror"

WORKDIR /app

# Create non-root user for security
RUN adduser -D -u 1000 mirror

# Copy application
COPY mirror.py .

# Create persistent directories
RUN mkdir -p /app/logs /app/reports && \
    chown -R mirror:mirror /app

USER mirror

# Volumes for persistent data
VOLUME ["/app/logs", "/app/reports"]

ENTRYPOINT ["python3", "mirror.py"]
CMD ["--lang", "en", "--yes"]
