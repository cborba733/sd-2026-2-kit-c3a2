FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8002
WORKDIR /app
COPY vetorial/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum ./comum
COPY vetorial ./vetorial
RUN useradd -m app && mkdir -p /dados && chown -R app /app /dados
USER app
EXPOSE 8002
CMD ["sh", "-c", "uvicorn vetorial.app:app --host 0.0.0.0 --port ${PORT}"]
