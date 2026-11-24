"""Autenticacao entre servicos: o gateway e o worker enviam um token compartilhado
(SERVICE_TOKEN) no cabecalho X-Service-Token. Sem ele, inferencia e vetorial recusam (401).
Se SERVICE_TOKEN estiver vazio, a checagem fica desligada (so para desenvolvimento local).
"""
import hmac
import os

from fastapi import HTTPException, Request


def exigir_token_servico(request: Request):
    esperado = os.getenv("SERVICE_TOKEN", "")
    if not esperado:
        return
    recebido = request.headers.get("x-service-token", "")
    if not hmac.compare_digest(recebido, esperado):
        raise HTTPException(status_code=401, detail="token de servico invalido")


def cabecalhos_servico():
    token = os.getenv("SERVICE_TOKEN", "")
    return {"X-Service-Token": token} if token else {}
