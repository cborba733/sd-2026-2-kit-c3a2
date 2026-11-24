"""Classificador de sentimento (positivo/negativo) em portugues.
Treina localmente na primeira execucao (no build da imagem Docker) e salva em .joblib.
Nao precisa de internet nem de GPU: a IA aqui e so a carga de trabalho do sistema.
"""
import os

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

CAMINHO = os.path.join(os.path.dirname(__file__), "modelo.joblib")

TREINO = [
    ("adorei o produto, recomendo demais", 1),
    ("o atendimento foi excelente e muito rapido", 1),
    ("o time jogou muito bem e mereceu a vitoria", 1),
    ("qualidade incrivel, superou minhas expectativas", 1),
    ("entrega rapida, tudo perfeito", 1),
    ("gostei muito, voltarei a comprar", 1),
    ("que partida emocionante, gol lindo", 1),
    ("servico otimo, equipe muito simpatica", 1),
    ("produto maravilhoso, vale cada centavo", 1),
    ("fiquei feliz com o resultado, muito bom", 1),
    ("excelente custo beneficio, adorei", 1),
    ("o jogo foi fantastico, torcida animada", 1),
    ("tudo funcionou perfeitamente, nota dez", 1),
    ("muito satisfeito com a compra", 1),
    ("atendimento atencioso e resolveu meu problema", 1),
    ("horrivel, quero meu dinheiro de volta", 0),
    ("o atendimento foi pessimo e demorado", 0),
    ("o time jogou mal e perdeu feio", 0),
    ("qualidade ruim, quebrou em um dia", 0),
    ("entrega atrasada e produto danificado", 0),
    ("nao gostei, nao recomendo a ninguem", 0),
    ("que partida chata, nenhum gol", 0),
    ("servico terrivel, equipe mal educada", 0),
    ("produto horroroso, perdi meu dinheiro", 0),
    ("fiquei decepcionado com o resultado", 0),
    ("caro demais para o que entrega", 0),
    ("o jogo foi um desastre, torcida revoltada", 0),
    ("nada funcionou, uma perda de tempo", 0),
    ("muito insatisfeito com a compra", 0),
    ("ninguem resolveu meu problema, descaso total", 0),
]


class ModeloSentimento:
    def __init__(self, pipeline):
        self._pipeline = pipeline

    def prever(self, texto: str) -> dict:
        proba = self._pipeline.predict_proba([texto])[0]
        idx = int(proba.argmax())
        return {"sentimento": "positivo" if idx == 1 else "negativo",
                "confianca": round(float(proba[idx]), 4)}


def treinar():
    pipeline = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=1),
                             LogisticRegression(max_iter=1000))
    pipeline.fit([t for t, _ in TREINO], [r for _, r in TREINO])
    joblib.dump(pipeline, CAMINHO)
    return pipeline


def carregar_modelo() -> ModeloSentimento:
    pipeline = joblib.load(CAMINHO) if os.path.exists(CAMINHO) else treinar()
    return ModeloSentimento(pipeline)


if __name__ == "__main__":      # usado no Dockerfile: python -m inferencia.modelo
    treinar()
    print("modelo treinado e salvo em", CAMINHO)
