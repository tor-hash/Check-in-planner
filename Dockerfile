FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run serves static files from the container through WhiteNoise.
# Dummy env vars let collectstatic import Django settings at build time;
# real production values are provided by Cloud Run at runtime.
RUN DJANGO_ENVIRONMENT=production \
    DJANGO_DEBUG=False \
    DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_ALLOWED_HOSTS=localhost \
    DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost \
    GOOGLE_OAUTH2_KEY=build-time-placeholder \
    GOOGLE_OAUTH2_SECRET=build-time-placeholder \
    DATABASE_URL=sqlite:///db.sqlite3 \
    python backend/manage.py collectstatic --noinput

CMD ["sh", "-c", "gunicorn config.wsgi:application --chdir backend --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120"]
