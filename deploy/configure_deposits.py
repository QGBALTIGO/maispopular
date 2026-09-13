"""Provision wallet offers in R$5 steps; never creates a payment or transfers money.

Read-only unless --apply is passed. Reuses matching active offers for the same
product. POST is intentionally not retried after ambiguous network failures.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import set_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
from domain import decimal_value
from payments import Cakto


async def main(apply):
    settings = Settings.load()
    client = Cakto(settings.cakto_client_id, settings.cakto_client_secret)
    try:
        base = await client.validate_offer(settings.cakto_offers[20], 20)
        product = base["product"]
        if isinstance(product, dict):
            product = product["id"]
        candidates = []
        for page in range(1, 101):
            data = await client._request("GET", f"offers/?page={page}")
            candidates.extend(data.get("results", []))
            if not data.get("next"):
                break
        else:
            raise RuntimeError("Offer pagination exceeded limit; no changes applied.")
        mapping = {}
        for amount in range(20, 101, 5):
            existing = next((r for r in candidates if (r.get("product", {}).get("id") if isinstance(r.get("product"), dict) else r.get("product")) == product
                and r.get("status") == "active" and r.get("type") == "unique" and decimal_value(r["price"]) == amount), None)
            if not existing and amount in settings.cakto_offers:
                existing = await client.validate_offer(settings.cakto_offers[amount], amount)
            if not existing:
                print(f"Missing wallet offer: BRL {amount}", flush=True)
                if not apply:
                    continue
                token = await client._token()
                response = await client.client.post("offers/", headers={"Authorization": f"Bearer {token}"},
                    json={"name": f"Recarga Mais Popular - R$ {amount}", "price": amount, "product": product})
                if response.status_code != 201:
                    raise RuntimeError(f"Offer create failed with HTTP {response.status_code}; stopped without retries.")
                existing = response.json()
            await client.validate_offer(str(existing["id"]), amount)
            mapping[amount] = str(existing["id"])
        print(json.dumps({"verifiedAmounts": sorted(mapping), "apply": apply}), flush=True)
        if apply:
            if len(mapping) != 17:
                raise RuntimeError("Incomplete offer mapping")
            env = Path(".env").resolve()
            original_stat = env.stat()
            set_key(env, "CAKTO_OFFERS_JSON", json.dumps(mapping, separators=(",", ":")))
            set_key(env, "MAX_DEPOSIT_BRL", "100")
            env.chmod(original_stat.st_mode & 0o777)
            if hasattr(os, "chown"):
                os.chown(env, original_stat.st_uid, original_stat.st_gid)
            print("Wallet offer configuration updated. No payments created.")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    try:
        asyncio.run(main(parser.parse_args().apply))
    except Exception as exc:  # noqa: BLE001 -- never print credential-bearing HTTP tracebacks
        print(f"Stopped: {type(exc).__name__}. Inspect configuration without exposing credentials.", file=sys.stderr)
        sys.exit(1)
