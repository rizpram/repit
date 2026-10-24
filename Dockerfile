FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && pip check && useradd --create-home --uid 10001 bot
COPY app ./app
USER bot
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD python -c "from app.security import healthy; raise SystemExit(0 if healthy() else 1)"
CMD ["python", "-m", "app.main"]
