FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum ./comum
COPY gateway ./gateway
RUN useradd -m app && mkdir -p /dados && chown -R app /app /dados
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn gateway.app:app --host 0.0.0.0 --port ${PORT}"]
