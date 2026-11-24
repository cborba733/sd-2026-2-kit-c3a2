"""Embeddings sem estado: HashingVectorizer. Como nao precisa "aprender" um vocabulario,
cada texto novo vira vetor na hora e os vetores antigos continuam validos
(o que permite adicionar documentos um a um no armazenamento vetorial)."""
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

# palavras muito comuns do portugues (sem acento): ignoradas, senao "de", "a", "que"
# fazem textos sem relacao parecerem parecidos
STOPWORDS_PT = [
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "com", "sem", "sobre", "ao", "aos",
    "e", "ou", "mas", "que", "se", "como", "qual", "quais", "quando", "onde", "quem",
    "ser", "sao", "foi", "era", "ha", "isso", "isto", "esse", "essa", "este", "esta",
    "seu", "sua", "seus", "suas", "mais", "muito", "ja", "tambem", "pelo", "pela",
    "ele", "ela", "eles", "elas", "nao", "sim", "entre", "ate", "so", "apenas",
]

_vetorizador = HashingVectorizer(n_features=512, alternate_sign=False, norm="l2",
                                 ngram_range=(1, 2), strip_accents="unicode",
                                 stop_words=STOPWORDS_PT)


def vetorizar(texto: str) -> np.ndarray:
    return _vetorizador.transform([texto]).toarray()[0].astype(np.float32)
