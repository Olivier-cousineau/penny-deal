#!/usr/bin/env python3
"""Scrape Home Depot liquidation deals and save to JSON."""
from __future__ import annotations

import argparse
import json
import inspect
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import csv

import httpx
from parsel import Selector

BASE_URL = "https://www.homedepot.ca"
CLEARANCE_URL = "https://www.homedepot.ca/en/home/categories/all/collections/clearance.html"
OUTPUT_PATH = Path("data/homedepot/liquidations.json")


def normalize_price(raw_price: str) -> float | None:
    cleaned = raw_price.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_url(store_id: str | None) -> str:
    if store_id:
        return f"{CLEARANCE_URL}?store={store_id}"
    return CLEARANCE_URL


def fetch_with_retries(
    client: httpx.Client, url: str, retries: int, backoff: float
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            response = client.get(url)
            response.raise_for_status()
            return response
        except httpx.TimeoutException:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(backoff * attempt)


def scrape_deals(
    url: str,
    user_agent: str | None = None,
    proxy: str | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    backoff: float = 2.0,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    headers = {
        "user-agent": ua,
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "fr-CA,fr;q=0.9,en;q=0.8",
    }
    client_kwargs: dict[str, object] = {
        "headers": headers,
        "follow_redirects": True,
        "timeout": timeout,
    }
    if proxy:
        proxy_config = {"http://": proxy, "https://": proxy}
        client_signature = inspect.signature(httpx.Client)
        if "proxies" in client_signature.parameters:
            client_kwargs["proxies"] = proxy_config
        elif "proxy" in client_signature.parameters:
            client_kwargs["proxy"] = proxy
    with httpx.Client(**client_kwargs) as client:
        response = fetch_with_retries(client, url, retries=retries, backoff=backoff)
        selector = Selector(response.text)

    cards = selector.css("[data-testid='product-grid'] [data-testid='product-card']")
    scraped_at = datetime.now(timezone.utc).isoformat()
    for card in cards:
        title = " ".join(card.css("[data-testid='product-card-title']::text").getall()).strip()
        price_text = " ".join(card.css("[data-testid='product-card-price']::text").getall()).strip()
        discount = " ".join(card.css("[data-testid='product-card-badge']::text").getall()).strip()
        if not discount:
            discount = " ".join(card.css("[data-testid='product-card-discount']::text").getall()).strip()
        url_path = card.css("a::attr(href)").get()
        if not url_path:
            continue
        full_url = url_path if url_path.startswith("http") else f"{BASE_URL}{url_path}"
        results.append(
            {
                "title": title,
                "price": price_text,
                "discount": discount,
                "url": full_url,
                "scraped_at": scraped_at,
            }
        )

    return results


def filter_penny_deals(results: Iterable[dict[str, str]], max_price: float = 5.00) -> list[dict[str, str]]:
    penny_deals: list[dict[str, str]] = []
    for deal in results:
        price_value = normalize_price(deal.get("price", ""))
        if price_value is None:
            continue
        if price_value < max_price:
            penny_deals.append(deal)
    return penny_deals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Home Depot liquidation deals.")
    parser.add_argument("--store", help="Optional store ID to filter results.")
    parser.add_argument("--user-agent", help="Custom user agent string.")
    parser.add_argument("--proxy", help="Proxy server, e.g. http://proxy:port.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    parser.add_argument("--retries", type=int, default=2, help="Retry count on timeouts.")
    parser.add_argument("--backoff", type=float, default=2.0, help="Backoff multiplier in seconds.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_url = build_url(args.store)
    results = scrape_deals(
        source_url,
        args.user_agent,
        args.proxy,
        timeout=args.timeout,
        retries=args.retries,
        backoff=args.backoff,
    )
    penny_deals = filter_penny_deals(results)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = output_path.with_suffix(".csv")

    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "deal_count": len(results),
        "penny_deal_count": len(penny_deals),
        "deals": results,
        "penny_deals": penny_deals,
    }

    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["title", "price", "discount", "url", "scraped_at"])
        writer.writeheader()
        writer.writerows(results)

    print(
        f"Saved {len(results)} deals ({len(penny_deals)} penny deals) to {output_path} and {csv_path}"
    )


if __name__ == "__main__":
    main()
