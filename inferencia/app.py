"""Servico de INFERENCIA: recebe um texto e devolve o sentimento (modelo scikit-learn).
So aceita chamadas com o token de servico (ver comum/seguranca.py).

Rodar: uvicorn inferencia.app:app --port 8001
"""
import time

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from comum.log import criar_logger
from comum.seguranca import exigir_token_servico
from comum.tracing import configurar_tracing
from inferencia.modelo import carregar_modelo

logger = criar_logger("inferencia")
app = FastAPI(title="Inferencia - C3.A2")
configurar_tracing("inferencia", app)
modelo = carregar_modelo()


class Entrada(BaseModel):
    texto: str = Field(max_length=2000)


@app.post("/predict", dependencies=[Depends(exigir_token_servico)])
def predict(entrada: Entrada):
    texto = entrada.texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="texto vazio")
    inicio = time.time()
    resultado = modelo.prever(texto)
    tempo_ms = round((time.time() - inicio) * 1000, 2)
    logger.info("predict tamanho_texto=%d sentimento=%s tempo_ms=%s",
                len(texto), resultado["sentimento"], tempo_ms)       # nunca loga o texto
    return {**resultado, "tempo_ms": tempo_ms}


@app.get("/saude")
def saude():
    return {"status": "ok", "servico": "inferencia"}
