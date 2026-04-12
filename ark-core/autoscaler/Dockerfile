FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Root — Docker socket is root-owned on typical hosts; map group if you prefer non-root:
#   user: "1003:999"  # uid:docker gid from host
COPY . .
CMD ["python", "autoscaler.py"]
