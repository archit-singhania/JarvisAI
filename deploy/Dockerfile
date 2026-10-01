FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEDNESDAY_DATA_DIR=/data DATA_DIR=/data VECTOR_DB_PATH=/data/vectordb
WORKDIR /app
COPY backend/requirements-core.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home wednesday && mkdir -p /data /app/models /app/logs && chown -R wednesday:wednesday /data /app
COPY --chown=wednesday:wednesday backend/app ./backend/app
COPY --chown=wednesday:wednesday ui ./ui
USER wednesday
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"
CMD ["python","-m","uvicorn","app.main:app","--app-dir","backend","--host","0.0.0.0","--port","8000"]
