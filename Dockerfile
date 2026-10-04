FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes libgomp1 tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY ai_orchestrated_optimization ./ai_orchestrated_optimization
COPY deploy/seed ./deploy/seed
COPY profiles ./profiles
COPY scheduler ./scheduler

RUN python -m pip install . \
    && groupadd --gid 10001 scheduler \
    && useradd --uid 10001 --gid scheduler --no-create-home --shell /usr/sbin/nologin scheduler \
    && mkdir -p /app/outputs \
    && chown -R scheduler:scheduler /app/outputs

USER 10001:10001

EXPOSE 8765

ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["scheduler-web", "--host", "0.0.0.0", "--port", "8765"]
