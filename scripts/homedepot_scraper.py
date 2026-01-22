#!/usr/bin/env python3
"""Scrape Home Depot liquidation deals and save to JSON."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from playwright.sync_api import sync_playwright

BASE_URL = "https://www.homedepot.ca/en/home/collection/clearance-centre/"
OUTPUT_PATH = Path("data/homedepot/liquidations.json")


def normalize_price(raw_price: str) -> float | None:
    cleaned = raw_price.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_source_url(store_id: str | None) -> str:
    if store_id:
        return f"{BASE_URL}?store={store_id}"
    return BASE_URL


def scrape_deals(url: str, user_agent: str | None, proxy: str | None) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        context_kwargs: dict[str, object] = {}
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}

        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        cards = page.locator("[data-testid='product-grid'] [data-testid='product-card']")
        card_count = cards.count()
        for idx in range(card_count):
            card = cards.nth(idx)
            title = card.locator("[data-testid='product-card-title']").inner_text().strip()
            price_text = card.locator("[data-testid='product-card-price']").inner_text().strip()
            url_path = card.locator("a").first.get_attribute("href")
            if not url_path:
                continue
            full_url = url_path if url_path.startswith("http") else f"https://www.homedepot.ca{url_path}"
            results.append(
                {
                    "title": title,
                    "price": price_text,
                    "url": full_url,
                }
            )

        context.close()
        browser.close()

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
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_url = build_source_url(args.store)
    results = scrape_deals(source_url, args.user_agent, args.proxy)
    penny_deals = filter_penny_deals(results)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "deal_count": len(results),
        "penny_deal_count": len(penny_deals),
        "deals": results,
        "penny_deals": penny_deals,
    }

    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Saved {len(results)} deals ({len(penny_deals)} penny deals) to {output_path}")


if __name__ == "__main__":
    main()
