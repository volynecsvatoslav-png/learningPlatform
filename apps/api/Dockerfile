FROM python:3.13.5-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system django \
    && adduser --system --ingroup django django
COPY requirements.lock ./
RUN pip install --no-cache-dir --requirement requirements.lock

COPY --chown=django:django . .
RUN chown -R django:django /app
RUN chmod +x /app/entrypoint.sh
USER django

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000", "--worker-class=gthread", "--workers=2", "--threads=4", "--timeout=30", "--keep-alive=5", "--access-logfile=-", "--error-logfile=-"]
