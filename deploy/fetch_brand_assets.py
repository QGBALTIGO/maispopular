"""Download de assets de marca; sem dependência de CDN no Mini App."""
import concurrent.futures
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUGS = "instagram tiktok youtube telegram facebook whatsapp kwai x threads spotify twitch discord linkedin pinterest soundcloud snackvideo roblox bluesky kick google netflix disneyplus primevideo hbo openai canva capcut globoplay paramountplus rakutenviki nordvpn brainly duolingo xbox crunchyroll".split()
BASE = "https://raw.githubusercontent.com/simple-icons/simple-icons/13.21.0/"


def main():
    folder = ROOT / "webapp_static" / "brands"
    folder.mkdir(exist_ok=True)
    metadata = httpx.get(BASE + "_data/simple-icons.json", timeout=30)
    metadata.raise_for_status()
    icons = metadata.json()["icons"]
    sources = []

    def fetch(slug):
        response = httpx.get(BASE + f"icons/{slug}.svg", timeout=30)
        if response.status_code != 200:
            return slug
        item = next((i for i in icons if re.sub(r"[^a-z0-9]", "", i["title"].lower().replace("+", "plus")) == slug), {})
        svg = response.text.replace('<svg ', f'<svg fill="#{item.get("hex", "172033")}" ')
        (folder / f"{slug}.svg").write_text(svg, encoding="utf-8")
        sources.append({"slug": slug, **item})
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        missing = list(filter(None, pool.map(fetch, SLUGS)))
    (folder / "SOURCES.json").write_text(json.dumps(sorted(sources, key=lambda x: x["slug"]), ensure_ascii=False, indent=2), encoding="utf-8")
    print("Brand assets:", len(sources), "Unavailable:", missing)
    # Reuse the bot's existing identity, never expose the token in a public URL.
    from config import Settings
    settings = Settings.load()
    with httpx.Client(timeout=30) as client:
        base = "https://api.telegram.org/bot" + settings.bot_token
        me = client.get(base + "/getMe").json()["result"]
        photos = client.get(base + "/getUserProfilePhotos", params={"user_id": me["id"], "limit": 1}).json()["result"]["photos"]
        if photos:
            file = client.get(base + "/getFile", params={"file_id": photos[0][-1]["file_id"]}).json()["result"]
            result = client.get("https://api.telegram.org/file/bot" + settings.bot_token + "/" + file["file_path"])
            result.raise_for_status()
            (ROOT / "webapp_static" / "logo.jpg").write_bytes(result.content)
            print("Bot logo saved")


if __name__ == "__main__":
    main()
