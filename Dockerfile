# Backend image: Flask + Socket.IO (the broadcaster has its own future image).
# Kept slim; system packages are limited to what the Python deps need at runtime.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libmagic is used by python-magic / filetype for mimetype sniffing in media uploads.
# curl is convenient for healthchecks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5001

# Commit 3 will prepend `alembic upgrade head &&` here so the DB is current at boot.
CMD ["python", "run.py"]
