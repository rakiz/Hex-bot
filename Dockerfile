FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hex_bot/ hex_bot/

RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8080

# WEB_CONCURRENCY can be overridden at runtime (e.g. in Kanopy values.yml).
# exec replaces the shell so SIGTERM goes directly to gunicorn (graceful shutdown).
CMD ["sh", "-c", "exec gunicorn --workers ${WEB_CONCURRENCY:-4} --bind 0.0.0.0:8080 --access-logfile - hex_bot.app:app"]
