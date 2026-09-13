"""Use first-party favicon assets where a brand is absent from Simple Icons."""
import concurrent.futures
import json
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1] / "webapp_static" / "brands"
SITES = {"kwai":"https://www.kwai.com/pt-BR/brand-resource",
         "snackvideo":"https://www.snackvideo.com", "capcut":"https://www.capcut.com",
         "globoplay":"https://globoplay.globo.com", "rakutenviki":"https://www.viki.com",
         "brainly":"https://brainly.com.br", "qconcursos":"https://www.qconcursos.com",
         "premiere":"https://premiere.globo.com"}


def fetch(pair):
    slug, url = pair
    try:
        with httpx.Client(timeout=25, follow_redirects=True) as client:
            response = client.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            candidates = soup.select('link[rel*="icon"]')
            candidates.sort(key=lambda x: "apple" not in " ".join(x.get("rel", [])))
            for node in candidates:
                href = urljoin(str(response.url), node.get("href", ""))
                data = client.get(href)
                if data.status_code != 200 or len(data.content) > 1000000:
                    continue
                mime = data.headers.get("content-type", "")
                ext = "svg" if "svg" in mime else "png" if data.content.startswith(b"\x89PNG") else "ico" if data.content.startswith(b"\x00\x00\x01\x00") else ""
                if not ext:
                    continue
                (ROOT / f"{slug}.{ext}").write_bytes(data.content)
                return slug, {"file":f"{slug}.{ext}","source":href,"website":url}
            return slug, {"error":f"No icon ({response.status_code})"}
    except httpx.HTTPError as exc:
        return slug, {"error":type(exc).__name__}


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        result = dict(pool.map(fetch, SITES.items()))
    for slug, remote in {"disneyplus":"disney-plus", "xbox":"xbox"}.items():
        url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{remote}.svg"
        response = httpx.get(url, timeout=20)
        response.raise_for_status()
        (ROOT / f"{slug}.svg").write_bytes(response.content)
        result[slug] = {"file":f"{slug}.svg", "source":url}
    for slug, app_id in {"brainly":"co.brainly", "qconcursos":"com.qconcursos.QCX"}.items():
        url = f"https://play.google.com/store/apps/details?id={app_id}&hl=pt_BR"
        response = httpx.get(url, timeout=25)
        node = BeautifulSoup(response.text, "html.parser").select_one('meta[property="og:image"]')
        if node:
            asset_url = node["content"]
            image = httpx.get(asset_url, timeout=25)
            image.raise_for_status()
            ext = "png" if image.content.startswith(b"\x89PNG") else "webp" if image.content.startswith(b"RIFF") else "jpg"
            (ROOT / f"{slug}.{ext}").write_bytes(image.content)
            result[slug] = {"file":f"{slug}.{ext}", "source":asset_url, "website":url}
    (ROOT / "FIRST_PARTY_SOURCES.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result, indent=2))
