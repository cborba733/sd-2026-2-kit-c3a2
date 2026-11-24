"""Logging unico dos servicos. Cada linha leva o trace_id da requisicao em andamento,
assim da para seguir uma mesma requisicao pelos logs do gateway, da fila e do worker.

REGRA DE PRIVACIDADE: nunca registrar o texto enviado pelo usuario, so o tamanho.
"""
import logging

try:
    from opentelemetry import trace
except ImportError:  # pragma: no cover
    trace = None


class _FiltroTrace(logging.Filter):
    def filter(self, record):
        trace_id = "-"
        if trace is not None:
            ctx = trace.get_current_span().get_span_context()
            if ctx.is_valid:
                trace_id = format(ctx.trace_id, "032x")
        record.trace_id = trace_id
        return True


def criar_logger(nome):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s trace=%(trace_id)s: %(message)s",
                        datefmt="%H:%M:%S")
    for handler in logging.getLogger().handlers:
        handler.addFilter(_FiltroTrace())
    return logging.getLogger(nome)
