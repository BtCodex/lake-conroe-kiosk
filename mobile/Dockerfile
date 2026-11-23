FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LAKE_DASHBOARD_CACHE_DIR=/var/cache/lake-dashboard
WORKDIR /srv/lake-dashboard

RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home dashboard && install -d -o dashboard -g dashboard /var/cache/lake-dashboard
COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt
COPY app/ ./app/
COPY static/ ./static/
COPY config/settings.example.json ./config/settings.example.json
COPY mobile/__init__.py mobile/main.py ./mobile/
COPY mobile/assets/ ./mobile/assets/
RUN chmod -R a+rX app static config mobile

USER dashboard
EXPOSE 8081
CMD ["sh", "-c", "exec uvicorn mobile.main:app --host 0.0.0.0 --port ${PORT:-8081}"]
