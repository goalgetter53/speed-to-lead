FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY speed_to_lead ./speed_to_lead
RUN pip install --no-cache-dir ".[postgres]" && useradd -m app && mkdir -p /app/data && chown app /app/data
USER app
EXPOSE 8000
# Render/Koyeb/Cloud Run pass $PORT; default 8000 locally.
CMD ["sh", "-c", "python -m speed_to_lead serve --port ${PORT:-8000}"]
