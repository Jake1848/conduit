FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY conduit_core ./conduit_core

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "conduit_core.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
