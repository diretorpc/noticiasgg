import os
from flask import Flask, jsonify
from bs4 import BeautifulSoup
import requests
import re

app = Flask(__name__)

SCRAPINGBEE_KEY = os.environ["SCRAPINGBEE_KEY"]
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"

CEPEA_PRODUTOS = {
    "Acucar Cristal SP":   ("https://www.cepea.org.br/br/indicador/acucar.aspx",    "R$/sc 50kg"),
    "Boi Gordo SP":        ("https://www.cepea.org.br/br/indicador/boi-gordo.aspx", "R$/@"),
    "Cafe Arabica SP":     ("https://www.cepea.org.br/br/indicador/cafe.aspx",      "R$/sc 60kg"),
    "Soja PR":             ("https://www.cepea.org.br/br/indicador/soja.aspx",      "R$/sc 60kg"),
    "Milho SP":            ("https://www.cepea.org.br/br/indicador/milho.aspx",     "R$/sc 60kg"),
    "Trigo PR":            ("https://www.cepea.org.br/br/indicador/trigo.aspx",     "R$/sc 60kg"),
    "Frango congelado SP": ("https://www.cepea.org.br/br/indicador/frango.aspx",    "R$/kg"),
    "Suino vivo PR":       ("https://www.cepea.org.br/br/indicador/suino.aspx",     "R$/kg"),
    "Arroz tipo 1 RS":     ("https://www.cepea.org.br/br/indicador/arroz.aspx",     "R$/sc 50kg"),
}


def _parse_br_float(texto: str):
    try:
        return float(texto.strip().replace(".", "").replace(",", ".").replace("+", "").replace("%", ""))
    except Exception:
        return None


def _scrape_cepea(url: str, unidade: str) -> dict:
    try:
        resp = requests.get(
            SCRAPINGBEE_URL,
            params={
                "api_key": SCRAPINGBEE_KEY,
                "url": url,
                "render_js": "true",
                "stealth_proxy": "true",
            },
            timeout=120,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        tabela = soup.find("table", {"id": re.compile(r"imagenet-indicador", re.I)})
        if not tabela:
            tabela = soup.find("table")
        if not tabela:
            return {"preco": None, "variacao_pct": None, "erro": "tabela nao encontrada", "unidade": unidade, "moeda": "BRL"}

        linhas = [l for l in tabela.find_all("tr") if l.find("td")]
        if not linhas:
            return {"preco": None, "variacao_pct": None, "erro": "sem linhas", "unidade": unidade, "moeda": "BRL"}

        # Estrutura CEPEA: [Data, Valor R$, Var./Dia, Var./Mês, Valor US$]
        cols = [c.get_text(strip=True) for c in linhas[0].find_all("td")]
        preco = _parse_br_float(cols[1]) if len(cols) > 1 else None
        variacao = _parse_br_float(cols[2]) if len(cols) > 2 else None

        return {"preco": preco, "variacao_pct": variacao, "unidade": unidade, "moeda": "BRL"}

    except requests.HTTPError as e:
        return {"preco": None, "variacao_pct": None, "erro": f"HTTP {e.response.status_code}", "unidade": unidade, "moeda": "BRL"}
    except Exception as e:
        return {"preco": None, "variacao_pct": None, "erro": str(e), "unidade": unidade, "moeda": "BRL"}


@app.route("/cepea")
def get_cepea():
    resultado = {}
    for nome, (url, unidade) in CEPEA_PRODUTOS.items():
        resultado[nome] = _scrape_cepea(url, unidade)
    return jsonify({"data": resultado})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001)
