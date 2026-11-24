"""Servico de ARMAZENAMENTO VETORIAL: guarda textos como vetores e busca os mais parecidos.
So aceita chamadas com o token de servico.

Rodar: uvicorn vetorial.app:app --port 8002
"""
import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from comum.log import criar_logger
from comum.seguranca import exigir_token_servico
from comum.tracing import configurar_tracing
from vetorial.armazenamento import Armazenamento

logger = criar_logger("vetorial")
app = FastAPI(title="Armazenamento vetorial - C3.A2")
configurar_tracing("vetorial", app)
armazenamento = Armazenamento()


class NovoDocumento(BaseModel):
    id: str | None = None
    texto: str = Field(min_length=1, max_length=2000)
    metadados: dict = {}


class Busca(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=3, ge=1, le=20)


@app.post("/documentos", status_code=201, dependencies=[Depends(exigir_token_servico)])
def adicionar(doc: NovoDocumento):
    id_ = doc.id or str(uuid.uuid4())
    total = armazenamento.adicionar(id_, doc.texto, doc.metadados)   # mesmo id = atualiza
    logger.info("documento armazenado tamanho_texto=%d total=%d", len(doc.texto), total)
    return {"id": id_, "total": total}


@app.post("/buscar", dependencies=[Depends(exigir_token_servico)])
def buscar(busca: Busca):
    resultados = armazenamento.buscar(busca.texto, busca.k)
    logger.info("busca tamanho_texto=%d devolvidos=%d", len(busca.texto), len(resultados))
    return {"resultados": resultados}


@app.delete("/documentos/{id_}", dependencies=[Depends(exigir_token_servico)])
def remover(id_: str):
    return {"removido": armazenamento.remover(id_)}


@app.get("/saude")
def saude():
    return {"status": "ok", "servico": "vetorial", "documentos": armazenamento.total()}
