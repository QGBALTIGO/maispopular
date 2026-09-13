"""Importa descrições públicas, sem login, cookies, preços ou dados de clientes.

Executar manualmente após revisar alterações do fornecedor. A API continua
sendo a única fonte de disponibilidade, limites e preço.
"""
import json
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def main():
    response = httpx.get("https://soupopular.net/services", timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for row in soup.select("tr.table-mobile-card"):
        identity = row.select_one('[data-title="ID"]')
        name = row.select_one('[data-title="Serviço"]')
        body = row.select_one(".modal-body")
        if not identity or not name or not body:
            continue
        description = body.get_text("\n", strip=True)
        if description:
            records[identity.get_text(strip=True)] = {
                "sourceName": name.get_text(strip=True), "description": description}
    if len(records) < 50:
        sys.exit("Importação cancelada: estrutura da página mudou.")
    target = ROOT / "catalog_content.json"
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Descrições importadas: {len(records)}")


if __name__ == "__main__":
    main()
