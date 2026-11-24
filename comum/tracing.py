"""Rastreamento distribuido com OpenTelemetry.

- O FastAPI e a biblioteca requests sao instrumentados: cada requisicao vira um "span" e o
  cabecalho traceparent viaja de servico em servico.
- A FILA nao leva cabecalhos HTTP, entao o gateway coloca o traceparent DENTRO da mensagem
  e o worker retoma o mesmo trace (ver gateway/app.py e worker/app.py).

Para onde os spans vao (configuracao por variavel de ambiente):
- OTEL_EXPORTER_OTLP_ENDPOINT definido (ex.: http://jaeger:4318): envia ao Jaeger.
- OTEL_CONSOLE=1: imprime os spans no log do container.
- nenhum dos dois: os spans existem (e o trace_id aparece nos logs), mas nao sao exportados.
"""
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (BatchSpanProcessor, ConsoleSpanExporter,
                                            SimpleSpanProcessor)


def configurar_tracing(nome_servico, app=None):
    provider = TracerProvider(resource=Resource.create({"service.name": nome_servico}))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if os.getenv("OTEL_CONSOLE") == "1":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, excluded_urls="saude")
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()
    except ImportError:  # inferencia e vetorial nao fazem chamadas de saida
        pass
    return trace.get_tracer(nome_servico)
