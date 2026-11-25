"""Resiliencia nas chamadas entre servicos: TEMPO-LIMITE + RETENTATIVA com espera
progressiva + CIRCUIT BREAKER (disjuntor) por fora de tudo.
"""
import os
import threading
import time

from urllib.parse import urlparse

import requests

from comum.log import criar_logger

logger = criar_logger("resiliencia")


class CircuitoAberto(Exception):
    """O disjuntor esta aberto: a chamada foi recusada sem tentar o servico."""


class CircuitBreaker:
    """fechado -> (N falhas seguidas) -> aberto -> (passou o tempo) -> meio-aberto
    No meio-aberto uma chamada de teste passa: se der certo fecha, se falhar abre de novo."""

    def __init__(self, nome, limite_falhas=3, espera_segundos=20):
        self.nome = nome
        self.limite_falhas = limite_falhas
        self.espera_segundos = espera_segundos
        self._falhas = 0
        self._aberto_em = None
        self._lock = threading.Lock()

    @property
    def estado(self):
        with self._lock:
            if self._aberto_em is None:
                return "fechado"
            if time.time() - self._aberto_em >= self.espera_segundos:
                return "meio-aberto"
            return "aberto"

    def chamar(self, funcao, *args, **kwargs):
        if self.estado == "aberto":
            raise CircuitoAberto(f"disjuntor de '{self.nome}' aberto")
        try:
            resultado = funcao(*args, **kwargs)
        except Exception:
            with self._lock:
                self._falhas += 1
                if self._falhas >= self.limite_falhas or self._aberto_em is not None:
                    self._aberto_em = time.time()
                    logger.warning("disjuntor '%s' ABERTO", self.nome)
            raise
        with self._lock:
            self._falhas = 0
            self._aberto_em = None
        return resultado


def _acordar(url, timeout):
    """Plano gratuito: servico dormindo devolve 502 para POST, mas SEGURA um GET ate acordar.
    Faz um GET em /saude do mesmo servico. Devolve True se ele respondeu 200."""
    partes = urlparse(url)
    try:
        r = requests.get(f"{partes.scheme}://{partes.netloc}/saude", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def chamar_servico(breaker, metodo, url, tentativas=None, espera_base=None, timeout=None, **kwargs):
    """Chama outro servico por HTTP. Erro de rede, tempo esgotado e resposta 5xx sao
    retentados (espera 0,5s, 1s, 2s...). Resposta 4xx volta direto para quem chamou.
    Padroes por variavel de ambiente (no Render gratuito, que "dorme", sobem os valores):
    TENTATIVAS_SERVICO=3, ESPERA_BASE=0.5 (s), TIMEOUT_SERVICO=5 (s)."""
    tentativas = tentativas or int(os.getenv("TENTATIVAS_SERVICO", "3"))
    espera_base = espera_base or float(os.getenv("ESPERA_BASE", "0.5"))
    timeout = timeout or float(os.getenv("TIMEOUT_SERVICO", "5"))

    def com_retentativa():
        for tentativa in range(1, tentativas + 1):
            try:
                resposta = requests.request(metodo, url, timeout=timeout, **kwargs)
                if resposta.status_code >= 500:
                    raise requests.HTTPError(f"resposta {resposta.status_code}")
                return resposta
            except requests.RequestException as erro:
                logger.warning("falha ao chamar %s (tentativa %d/%d): %s",
                               breaker.nome, tentativa, tentativas, erro)
                if tentativa == tentativas:
                    raise
                if tentativa == 1 and _acordar(url, timeout):
                    continue          # acordou: repete ja, sem esperar
                time.sleep(espera_base * 2 ** (tentativa - 1))

    return breaker.chamar(com_retentativa)
