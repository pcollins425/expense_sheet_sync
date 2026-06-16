FROM python:3.12-slim-bullseye

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN pip install --no-cache-dir -r /tmp/requirements-docker.txt \
    && rm /tmp/requirements-docker.txt

COPY expense_sheet_out_watcher/ /app/expense_sheet_out_watcher/
COPY scripts/usb_env_dotenv.py scripts/__init__.py /app/scripts/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MASTER_CREDENTIALS_ENV=/app/secrets/.env

RUN useradd -m -u 1000 sheetapp \
    && chown -R sheetapp:sheetapp /app
USER sheetapp
