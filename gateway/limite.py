"""Limite de requisicoes por cliente por minuto (janela deslizante, em memoria)."""
import threading
import time
from collections import defaultdict, deque


class LimiteTaxa:
    def __init__(self, maximo, janela_segundos=60):
        self.maximo = maximo
        self.janela = janela_segundos
        self._marcas = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, chave):
        """Devolve (permitido, segundos_para_tentar_de_novo)."""
        agora = time.time()
        with self._lock:
            marcas = self._marcas[chave]
            while marcas and agora - marcas[0] >= self.janela:
                marcas.popleft()
            if len(marcas) >= self.maximo:
                return False, int(self.janela - (agora - marcas[0])) + 1
            marcas.append(agora)
            return True, 0
