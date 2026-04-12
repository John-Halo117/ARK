FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --uid 10001 --create-home ark \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /runtime

COPY runtime/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY runtime/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY runtime/ .

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "runtime.py"]
