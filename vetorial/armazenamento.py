"""Armazenamento vetorial: guarda texto + vetor + metadados e busca por similaridade de
cosseno. Persiste em arquivo JSON (so texto e metadados; os vetores sao recalculados ao
carregar) e APAGA o que passou do prazo de retencao (RETENCAO_HORAS, padrao 24 h).
"""
import json
import os
import threading
import time

import numpy as np

from vetorial.embeddings import vetorizar

CAMINHO = os.getenv("VETORIAL_PATH", "dados/vetorial.json")
RETENCAO_SEGUNDOS = float(os.getenv("RETENCAO_HORAS", "24")) * 3600


class Armazenamento:
    def __init__(self):
        self._lock = threading.Lock()
        self._docs = {}                      # id -> {texto, metadados, criado_em, vetor}
        self._carregar()

    def _carregar(self):
        if not os.path.exists(CAMINHO):
            return
        with open(CAMINHO, encoding="utf-8") as f:
            for id_, d in json.load(f).items():
                d["vetor"] = vetorizar(d["texto"])
                self._docs[id_] = d
        self._expirar()

    def _salvar(self):
        pasta = os.path.dirname(CAMINHO)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        tmp = CAMINHO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({i: {k: v for k, v in d.items() if k != "vetor"}
                       for i, d in self._docs.items()}, f, ensure_ascii=False)
        os.replace(tmp, CAMINHO)

    def _expirar(self):
        limite = time.time() - RETENCAO_SEGUNDOS
        velhos = [i for i, d in self._docs.items() if d["criado_em"] < limite]
        for i in velhos:
            del self._docs[i]
        return len(velhos)

    def adicionar(self, id_, texto, metadados):
        with self._lock:
            self._expirar()
            self._docs[id_] = {"texto": texto, "metadados": metadados,
                               "criado_em": time.time(), "vetor": vetorizar(texto)}
            self._salvar()
            return len(self._docs)

    def remover(self, id_):
        with self._lock:
            existia = self._docs.pop(id_, None) is not None
            if existia:
                self._salvar()
            return existia

    def buscar(self, texto, k):
        with self._lock:
            if self._expirar():
                self._salvar()
            if not self._docs:
                return []
            consulta = vetorizar(texto)
            ids = list(self._docs)
            matriz = np.stack([self._docs[i]["vetor"] for i in ids])
            notas = matriz @ consulta                    # vetores ja normalizados = cosseno
            ordem = np.argsort(-notas)[:k]
            return [{"id": ids[j], "texto": self._docs[ids[j]]["texto"],
                     "score": round(float(notas[j]), 4),
                     "metadados": self._docs[ids[j]]["metadados"]}
                    for j in ordem if notas[j] > 0]

    def total(self):
        with self._lock:
            return len(self._docs)
