"""
WORKER DE FILA: consome a fila Redis, chama a inferencia, guarda o texto no armazenamento
vetorial e grava o resultado do job. Tambem expoe /saude por HTTP: no plano gratuito do
Render so "web services" sao gratuitos, entao o worker roda dentro de um.

Rodar: uvicorn worker.app:app --port 8003
"""
import json
import os
import threading
import time
from contextlib import asynccontextmanager

import redis
import requests
from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from comum.log import criar_logger
from comum.resiliencia import CircuitBreaker, CircuitoAberto, chamar_servico
from comum.seguranca import cabecalhos_servico
from comum.tracing import configurar_tracing

logger = criar_logger("worker")

URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")
URL_VETORIAL = os.getenv("URL_VETORIAL", "http://localhost:8002")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULT_TTL = int(os.getenv("RESULT_TTL_SECONDS", "3600"))
FILA = "fila_jobs"
FILA_FALHAS = "fila_jobs_falhas"          # so IDs; o conteudo fica em falha:<id> com TTL
MAX_TENTATIVAS = 3

fila = redis.Redis.from_url(REDIS_URL, decode_responses=True)
disjuntor_inferencia = CircuitBreaker("inferencia")
disjuntor_vetorial = CircuitBreaker("vetorial")


def processar(msg):
    texto = msg["texto"]
    resposta = chamar_servico(disjuntor_inferencia, "POST", f"{URL_INFERENCIA}/predict",
                              json={"texto": texto},
                              headers=cabecalhos_servico())
    resposta.raise_for_status()
    resultado = resposta.json()

    indexado = True        # se o armazenamento vetorial falhar, o job ainda termina (degrada)
    try:
        r = chamar_servico(disjuntor_vetorial, "POST", f"{URL_VETORIAL}/documentos",
                           headers=cabecalhos_servico(),
                           json={"id": msg["id"], "texto": texto,
                                 "metadados": {"sentimento": resultado["sentimento"],
                                               "confianca": resultado["confianca"]}})
        r.raise_for_status()
    except (requests.RequestException, CircuitoAberto) as erro:
        indexado = False
        logger.warning("job %s: nao foi possivel armazenar o vetor: %s", msg["id"], erro)

    fila.set(f"job:{msg['id']}",
             json.dumps({"status": "pronto", "owner": msg["owner"],
                         "resultado": resultado, "indexado": indexado}), ex=RESULT_TTL)


def laco_do_worker(parar: threading.Event):
    tracer = trace.get_tracer("worker")
    logger.info("worker pronto, aguardando jobs na fila '%s'", FILA)
    while not parar.is_set():
        try:
            item = fila.blpop(FILA, timeout=5)
        except redis.RedisError as erro:
            logger.warning("redis indisponivel: %s", erro)
            time.sleep(2)
            continue
        if not item:
            continue
        msg = json.loads(item[1])
        contexto = propagate.extract(msg.get("traceparent", {}))     # retoma o trace do gateway
        with tracer.start_as_current_span("worker.processar_job", context=contexto,
                                          kind=SpanKind.CONSUMER) as span:
            span.set_attribute("job.id", msg["id"])
            for tentativa in range(1, MAX_TENTATIVAS + 1):
                inicio = time.time()
                try:
                    processar(msg)
                    logger.info("job %s concluido (tentativa %d, %.0f ms)",
                                msg["id"], tentativa, (time.time() - inicio) * 1000)
                    break
                except CircuitoAberto:
                    # inferencia fora do ar: devolve o job para a fila e espera (a fila absorve a falha)
                    fila.rpush(FILA, item[1])
                    logger.warning("job %s devolvido a fila: disjuntor aberto", msg["id"])
                    time.sleep(2)
                    break
                except Exception as erro:  # noqa: BLE001
                    logger.warning("job %s falhou (tentativa %d/%d): %s",
                                   msg["id"], tentativa, MAX_TENTATIVAS, erro)
                    if tentativa == MAX_TENTATIVAS:
                        fila.set(f"falha:{msg['id']}", item[1], ex=RESULT_TTL)
                        fila.rpush(FILA_FALHAS, msg["id"])
                        fila.set(f"job:{msg['id']}",
                                 json.dumps({"status": "falhou", "owner": msg["owner"],
                                             "erro": "nao foi possivel processar o texto"}),
                                 ex=RESULT_TTL)
                        span.set_status(Status(StatusCode.ERROR, str(erro)))
                    else:
                        time.sleep(tentativa)


@asynccontextmanager
async def ciclo_de_vida(app):
    parar = threading.Event()
    threading.Thread(target=laco_do_worker, args=(parar,), daemon=True).start()
    yield
    parar.set()


app = FastAPI(title="Worker - C3.A2", lifespan=ciclo_de_vida)
configurar_tracing("worker", app)


@app.get("/saude")
def saude():
    try:
        pendentes = fila.llen(FILA)
    except redis.RedisError:
        pendentes = None
    return {"status": "ok", "servico": "worker", "na_fila": pendentes}
