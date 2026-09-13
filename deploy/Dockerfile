# VidUniq Telegram bot — Linux-контейнер со статическим ffmpeg (без Qt). ~200 МБ.
ARG PYTHON_VERSION=3.12

# --- статические ffmpeg/ffprobe (те же сборки, что и в macOS-приложении) ---
FROM debian:bookworm-slim AS ffmpeg
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    base="https://ffmpeg.martin-riedl.de/redirect/latest/linux/${TARGETARCH}/release"; \
    for tool in ffmpeg ffprobe; do \
      curl -fL --retry 3 -o /tmp/$tool.zip "$base/$tool.zip"; \
      unzip -oq /tmp/$tool.zip -d /tmp/$tool; \
      install -m 755 "$(find /tmp/$tool -type f -name $tool | head -1)" /usr/local/bin/$tool; \
    done; \
    /usr/local/bin/ffmpeg -version | head -1

# --- приложение ---
FROM python:${PYTHON_VERSION}-slim
COPY --from=ffmpeg /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /usr/local/bin/

WORKDIR /app
COPY pyproject.toml README.md ./
COPY viduniq ./viduniq
RUN pip install --no-cache-dir ".[bot]"

ENV WORK_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
HEALTHCHECK --interval=60s --timeout=10s CMD python -c "import viduniq.bot" || exit 1
CMD ["python", "-m", "viduniq.bot"]
