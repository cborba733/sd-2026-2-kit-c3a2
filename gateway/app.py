"""
API GATEWAY: unico ponto de entrada publico da plataforma.

  POST /login          usuario+senha -> token JWT
  POST /predict        (JWT) sentimento de um texto, resposta imediata (sincrono)
  POST /jobs           (JWT) enfileira um texto para processamento assincrono -> 202 + id
  GET  /jobs/{id}      (JWT) consulta o resultado do job
  DELETE /jobs/{id}    (JWT) apaga o resultado e o texto guardado (direito de eliminacao)
  POST /similares      (JWT) textos parecidos ja armazenados no armazenamento vetorial
  GET  /saude          sem autenticacao

Rodar: uvicorn gateway.app:app --port 8000
"""
import hmac
import json
import os
import threading
import time
import uuid

import jwt
import redis
import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, Field

from comum.log import criar_logger
from comum.resiliencia import CircuitBreaker, CircuitoAberto, chamar_servico
from comum.seguranca import cabecalhos_servico
from comum.tracing import configurar_tracing
from gateway.limite import LimiteTaxa

logger = criar_logger("gateway")

JWT_SEGREDO = os.getenv("JWT_SEGREDO", "troque-este-segredo")
JWT_EXPIRA_MIN = int(os.getenv("JWT_EXPIRA_MIN", "60"))
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "troque-esta-senha")
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")
URL_VETORIAL = os.getenv("URL_VETORIAL", "http://localhost:8002")
WORKER_URL = os.getenv("WORKER_URL", "")          # so no deploy (acorda o worker)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULT_TTL = int(os.getenv("RESULT_TTL_SECONDS", "3600"))
FILA = "fila_jobs"

app = FastAPI(title="Gateway - C3.A2")
tracer = configurar_tracing("gateway", app)
fila = redis.Redis.from_url(REDIS_URL, decode_responses=True)

limite_api = LimiteTaxa(int(os.getenv("RATE_LIMIT_POR_MIN", "30")))
limite_login = LimiteTaxa(int(os.getenv("RATE_LIMIT_LOGIN_POR_MIN", "10")))
disjuntor_inferencia = CircuitBreaker("inferencia")
disjuntor_vetorial = CircuitBreaker("vetorial")

if JWT_SEGREDO == "troque-este-segredo" or ADMIN_PASSWORD == "troque-esta-senha":
    logger.warning("usando segredo/senha PADRAO: defina JWT_SEGREDO e ADMIN_PASSWORD em producao")


# ---------- modelos ----------
class Credenciais(BaseModel):
    usuario: str
    senha: str


class Texto(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class Similares(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=3, ge=1, le=20)


# ---------- seguranca ----------
def _ip_cliente(request: Request):
    encaminhado = request.headers.get("x-forwarded-for", "")
    return encaminhado.split(",")[0].strip() if encaminhado else request.client.host


from fastapi.security import HTTPBearer  # noqa: E402

_esquema_bearer = HTTPBearer(auto_error=False, description="Cole o token devolvido por POST /login")


def autenticar(request: Request, _credencial=Depends(_esquema_bearer)) -> str:
    """Exige 'Authorization: Bearer <jwt>' valido e aplica o limite por usuario."""
    cabecalho = request.headers.get("authorization", "")
    if not cabecalho.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="token ausente",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        dados = jwt.decode(cabecalho[7:], JWT_SEGREDO, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expirado",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="token invalido",
                            headers={"WWW-Authenticate": "Bearer"})
    usuario = dados["sub"]
    permitido, espera = limite_api.permitir(usuario)
    if not permitido:
        raise HTTPException(status_code=429, detail="limite de requisicoes por minuto excedido",
                            headers={"Retry-After": str(espera)})
    return usuario


# ---------- chamadas internas (com resiliencia) ----------
def chamar(disjuntor, metodo, url, **kwargs):
    try:
        resposta = chamar_servico(disjuntor, metodo, url,
                                  headers=cabecalhos_servico(), **kwargs)
    except CircuitoAberto:
        raise HTTPException(status_code=503,
                            detail="servico temporariamente indisponivel (disjuntor aberto)")
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="falha ao chamar o servico interno")
    if resposta.status_code in (400, 422):
        raise HTTPException(status_code=resposta.status_code, detail="requisicao invalida")
    if resposta.status_code >= 400:
        raise HTTPException(status_code=502, detail="resposta inesperada do servico interno")
    return resposta.json()


def _acordar_worker():
    """No plano gratuito o worker 'dorme' sem trafego; um GET o acorda."""
    if not WORKER_URL:
        return

    def acordar():
        try:
            requests.get(f"{WORKER_URL}/saude", timeout=90)
        except requests.RequestException:
            pass

    threading.Thread(target=acordar, daemon=True).start()


# ---------- middleware de log (sem corpo, sem query: nada de dado pessoal) ----------
@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    if request.url.path != "/saude":
        logger.info("%s %s -> %d (%.1f ms)", request.method, request.url.path,
                    resposta.status_code, (time.time() - inicio) * 1000)
    return resposta


# ---------- rotas ----------
@app.post("/login")
def login(cred: Credenciais, request: Request):
    permitido, espera = limite_login.permitir(_ip_cliente(request))
    if not permitido:
        raise HTTPException(status_code=429, detail="muitas tentativas de login",
                            headers={"Retry-After": str(espera)})
    ok_usuario = hmac.compare_digest(cred.usuario, ADMIN_USER)
    ok_senha = hmac.compare_digest(cred.senha, ADMIN_PASSWORD)
    if not (ok_usuario and ok_senha):
        raise HTTPException(status_code=401, detail="usuario ou senha invalidos")
    agora = int(time.time())
    token = jwt.encode({"sub": cred.usuario, "iat": agora, "exp": agora + JWT_EXPIRA_MIN * 60},
                       JWT_SEGREDO, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expira_em_min": JWT_EXPIRA_MIN}


@app.post("/predict")
def predict(entrada: Texto, usuario: str = Depends(autenticar)):
    logger.info("predict usuario=%s tamanho_texto=%d", usuario, len(entrada.texto))
    return chamar(disjuntor_inferencia, "POST", f"{URL_INFERENCIA}/predict",
                  json={"texto": entrada.texto})


@app.post("/jobs", status_code=202)
def criar_job(entrada: Texto, usuario: str = Depends(autenticar)):
    job_id = str(uuid.uuid4())
    with tracer.start_as_current_span("fila.enfileirar", kind=SpanKind.PRODUCER) as span:
        span.set_attribute("job.id", job_id)
        contexto = {}
        propagate.inject(contexto)          # o trace viaja DENTRO da mensagem da fila
        mensagem = {"id": job_id, "texto": entrada.texto, "owner": usuario,
                    "traceparent": contexto}
        try:
            fila.set(f"job:{job_id}", json.dumps({"status": "na_fila", "owner": usuario}),
                     ex=RESULT_TTL)
            fila.rpush(FILA, json.dumps(mensagem))
        except redis.RedisError:
            raise HTTPException(status_code=503, detail="fila indisponivel")
    _acordar_worker()
    logger.info("job enfileirado id=%s usuario=%s tamanho_texto=%d",
                job_id, usuario, len(entrada.texto))
    return {"id": job_id, "status": "na_fila"}


def _ler_job(job_id, usuario):
    try:
        bruto = fila.get(f"job:{job_id}")
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="fila indisponivel")
    dados = json.loads(bruto) if bruto else None
    if not dados or dados.get("owner") != usuario:       # dono diferente = "nao existe"
        raise HTTPException(status_code=404, detail="job nao encontrado")
    return dados


@app.get("/jobs/{job_id}")
def consultar_job(job_id: str, usuario: str = Depends(autenticar)):
    dados = _ler_job(job_id, usuario)
    dados.pop("owner", None)
    return {"id": job_id, **dados}


@app.delete("/jobs/{job_id}")
def apagar_job(job_id: str, usuario: str = Depends(autenticar)):
    _ler_job(job_id, usuario)
    fila.delete(f"job:{job_id}")
    vetorial_ok = True
    try:
        chamar(disjuntor_vetorial, "DELETE", f"{URL_VETORIAL}/documentos/{job_id}")
    except HTTPException:
        vetorial_ok = False
    return {"removido": True, "armazenamento_vetorial": vetorial_ok}


@app.post("/similares")
def similares(entrada: Similares, usuario: str = Depends(autenticar)):
    return chamar(disjuntor_vetorial, "POST", f"{URL_VETORIAL}/buscar",
                  json={"texto": entrada.texto, "k": entrada.k})


@app.get("/saude")
def saude():
    try:
        fila_ok = bool(fila.ping())
    except redis.RedisError:
        fila_ok = False
    return {"status": "ok", "fila": "ok" if fila_ok else "indisponivel",
            "disjuntores": {"inferencia": disjuntor_inferencia.estado,
                            "vetorial": disjuntor_vetorial.estado}}


def inicio_json():
    return {"servico": "Plataforma de IA como Servico (C3.A2)",
            "saude": "/saude",
            "documentacao": "/docs",
            "login": "POST /login",
            "readme": "https://github.com/cborba733/sd-2026-2-kit-c3a2"}


_ultimo_aviso = 0.0


def _ping(url):
    try:
        requests.get(url.rstrip("/") + "/saude", timeout=120)
    except requests.RequestException:
        pass


def _acordar_servicos():
    """Plano gratuito: acorda em paralelo inferencia, vetorial e worker (no maximo 1 vez por minuto)."""
    global _ultimo_aviso
    if not WORKER_URL or time.time() - _ultimo_aviso < 60:
        return
    _ultimo_aviso = time.time()
    for url in (URL_INFERENCIA, URL_VETORIAL, WORKER_URL):
        threading.Thread(target=_ping, args=(url,), daemon=True).start()


@app.middleware("http")
async def acordar_no_acesso(request: Request, call_next):
    if request.url.path in ("/", "/login", "/docs"):
        _acordar_servicos()
    return await call_next(request)


from fastapi.responses import HTMLResponse  # noqa: E402

_PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Plataforma de IA como Servico (C3.A2)</title>
<style>body{font-family:system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 16px;line-height:1.5}
li{margin:6px 0}.ok{color:#0a7a2f}.er{color:#b00020}</style></head><body>
<h1>Plataforma de IA como Servi&ccedil;o (C3.A2)</h1>
<p>No plano gratuito do Render os servi&ccedil;os internos dormem sem uso e s&oacute; acordam com chamadas
vindas de fora. Esta p&aacute;gina os acorda a partir do seu navegador. Aguarde todos ficarem prontos
(cerca de 1 minuto) antes de testar.</p>
<ul id="lista"><li>gateway: <span class="ok">pronto</span></li></ul>
<p id="fim"></p>
<p><a href="/docs">Documenta&ccedil;&atilde;o interativa (/docs)</a> &middot; <a href="/saude">/saude</a> &middot;
<a href="https://github.com/cborba733/sd-2026-2-kit-c3a2">C&oacute;digo e README</a></p>
<script>
const alvos = __ALVOS__;
const nomes = Object.keys(alvos);
let pendentes = nomes.length;
const lista = document.getElementById("lista");
const fim = document.getElementById("fim");
if (!pendentes) fim.textContent = "Execucao local: nao ha nada para acordar.";
nomes.forEach(function (n) {
  const li = document.createElement("li");
  li.innerHTML = n + ': <span>acordando...</span>';
  lista.appendChild(li);
  const t0 = Date.now();
  fetch(alvos[n].replace(/\\/$/, "") + "/saude", {mode: "no-cors"})
    .then(function () {
      li.lastChild.textContent = "pronto (" + Math.round((Date.now() - t0) / 1000) + " s)";
      li.lastChild.className = "ok";
    })
    .catch(function () {
      li.lastChild.textContent = "sem resposta (recarregue a pagina)";
      li.lastChild.className = "er";
    })
    .finally(function () {
      if (--pendentes === 0) fim.textContent = "Servicos acordados. Pode usar o /docs ou o smoke test.";
    });
});
</script></body></html>"""


@app.get("/", include_in_schema=False)
def inicio(request: Request):
    if "text/html" not in request.headers.get("accept", ""):
        return inicio_json()
    alvos = {}
    if WORKER_URL:
        alvos = {"inferencia": URL_INFERENCIA, "vetorial": URL_VETORIAL, "worker": WORKER_URL}
    return HTMLResponse(_PAGINA.replace("__ALVOS__", json.dumps(alvos)))
