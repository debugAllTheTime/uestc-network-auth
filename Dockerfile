# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check

FROM dependencies AS runtime
COPY src/ ./src/
ENV PYTHONPATH=/app/src
STOPSIGNAL SIGTERM
CMD ["python", "-m", "uestc_auth"]
