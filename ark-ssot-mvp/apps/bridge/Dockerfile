FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY bridge.py /app/bridge.py

CMD ["python", "-u", "/app/bridge.py"]
