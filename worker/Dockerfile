FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8003
WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum ./comum
COPY worker ./worker
RUN useradd -m app && mkdir -p /dados && chown -R app /app /dados
USER app
EXPOSE 8003
CMD ["sh", "-c", "uvicorn worker.app:app --host 0.0.0.0 --port ${PORT}"]
