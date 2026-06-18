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
COPY expense_sheet_ref_watcher/ /app/expense_sheet_ref_watcher/
COPY expense_sheet_in_watcher/ /app/expense_sheet_in_watcher/
COPY scripts/usb_env_dotenv.py scripts/__init__.py /app/scripts/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MASTER_CREDENTIALS_ENV=/app/secrets/.env \
    EXPENSE_SHEET_REF_STATE_DIR=/app/state/ref_snapshots

RUN useradd -m -u 1000 sheetapp \
    && mkdir -p /app/state/ref_snapshots \
    && chown -R sheetapp:sheetapp /app
USER sheetapp
