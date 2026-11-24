FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8001
WORKDIR /app
COPY inferencia/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum ./comum
COPY inferencia ./inferencia
RUN python -m inferencia.modelo
RUN useradd -m app && mkdir -p /dados && chown -R app /app /dados
USER app
EXPOSE 8001
CMD ["sh", "-c", "uvicorn inferencia.app:app --host 0.0.0.0 --port ${PORT}"]
