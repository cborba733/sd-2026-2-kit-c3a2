"""Teste ponta a ponta da plataforma (so biblioteca padrao do Python, sem instalar nada).

Uso:
  python3 scripts/smoke_test.py                       # contra http://localhost:8000
  python3 scripts/smoke_test.py https://SEU-GATEWAY.onrender.com
  python3 scripts/smoke_test.py URL --limite          # tambem testa o limite (429)

Usuario e senha: variaveis ADMIN_USER / ADMIN_PASSWORD (padrao: admin / troque-esta-senha).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
        else "http://localhost:8000").rstrip("/")
USUARIO = os.getenv("ADMIN_USER", "admin")
SENHA = os.getenv("ADMIN_PASSWORD", "troque-esta-senha")
falhas = 0


def req(metodo, caminho, corpo=None, token=None, espera=120):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(BASE + caminho, data=dados, method=metodo)
    r.add_header("content-type", "application/json")
    if token:
        r.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=espera) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as erro:
        try:
            return erro.code, json.loads(erro.read() or b"{}")
        except ValueError:
            return erro.code, {}


def checar(nome, ok, detalhe=""):
    global falhas
    print(f"[{'OK' if ok else 'FALHOU'}] {nome} {detalhe}")
    if not ok:
        falhas += 1


print(f"Testando {BASE}\n(se for o deploy gratuito, a primeira chamada pode levar ~1 min: o servico acorda)\n")
codigo, corpo = req("GET", "/saude")
checar("GET /saude responde 200", codigo == 200, str(corpo))

codigo, _ = req("POST", "/predict", {"texto": "adorei"})
checar("POST /predict SEM token e recusado (401)", codigo == 401, f"-> {codigo}")

codigo, _ = req("POST", "/login", {"usuario": USUARIO, "senha": "senha-errada-xyz"})
checar("login com senha errada e recusado (401)", codigo == 401, f"-> {codigo}")

codigo, corpo = req("POST", "/login", {"usuario": USUARIO, "senha": SENHA})
checar("login correto devolve um token JWT", codigo == 200 and "access_token" in corpo, f"-> {codigo}")
token = corpo.get("access_token")
if not token:
    print("\nSem token nao da para continuar (confira ADMIN_USER / ADMIN_PASSWORD).")
    sys.exit(1)

codigo, corpo = req("POST", "/predict", {"texto": "o atendimento foi muito bom"}, token)
checar("POST /predict com token (sincrono)", codigo == 200 and corpo.get("sentimento") == "positivo",
       f"-> {codigo} {corpo}")

codigo, corpo = req("POST", "/jobs", {"texto": "o time jogou muito bem hoje"}, token)
checar("POST /jobs enfileira (202)", codigo == 202 and "id" in corpo, f"-> {codigo}")
job = corpo.get("id")
status = None
for _ in range(90):                     # ate ~90 s (o worker gratuito pode estar dormindo)
    codigo, corpo = req("GET", f"/jobs/{job}", token=token)
    status = corpo.get("status")
    if status in ("pronto", "falhou"):
        break
    time.sleep(1)
checar("o worker processou o job da fila", status == "pronto", f"-> status={status}")
checar("o texto foi guardado no armazenamento vetorial", corpo.get("indexado") is True)

codigo, corpo = req("POST", "/similares", {"texto": "o time jogou bem", "k": 2}, token)
checar("POST /similares encontra textos parecidos", codigo == 200 and len(corpo.get("resultados", [])) >= 1,
       f"-> {codigo}")

codigo, corpo = req("DELETE", f"/jobs/{job}", token=token)
checar("DELETE /jobs/{id} apaga os dados (LGPD)", codigo == 200 and corpo.get("removido") is True)

if "--limite" in sys.argv:
    codigos = [req("POST", "/predict", {"texto": "ok"}, token)[0] for _ in range(60)]
    checar("limite de requisicoes por minuto devolve 429", 429 in codigos)

print("\nRESULTADO:", "tudo certo" if falhas == 0 else f"{falhas} verificacao(oes) falharam")
sys.exit(1 if falhas else 0)
