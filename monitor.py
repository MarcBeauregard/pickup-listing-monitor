#!/usr/bin/env python3
"""Surveille le prix et la disponibilité d'annonces automobiles."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "PickupListingMonitor/1.0"
)

UNAVAILABLE_PATTERNS = (
    r"annonce (?:n['’]est )?plus disponible",
    r"véhicule (?:a été )?vendu",
    r"vehicle (?:has been )?sold",
    r"listing (?:is )?no longer available",
    r"inventory-status[^>]{0,80}(?:sold|unavailable)",
)

PRICE_PATTERNS = (
    r'<meta[^>]+(?:property|itemprop|name)=["\'](?:product:price:amount|price|og:price:amount)["\'][^>]+content=["\']([0-9][0-9\s,.]*)',
    r'<meta[^>]+content=["\']([0-9][0-9\s,.]*)["\'][^>]+(?:property|itemprop|name)=["\'](?:product:price:amount|price|og:price:amount)["\']',
    r'["\'](?:price|salePrice|vehiclePrice)["\']\s*:\s*["\']?\$?\s*([0-9][0-9\s,.]{2,})',
    r'(?:prix|price)[^0-9]{0,50}([0-9]{2,3}(?:[\s,.][0-9]{3})+)\s*\$?',
)


def parse_price(value: Any) -> int | None:
    """Convertit une représentation de prix CAD en dollars entiers."""
    if isinstance(value, (int, float)) and 1_000 <= value <= 500_000:
        return round(value)
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^0-9]", "", value.split(".")[0])
    if not cleaned:
        return None
    price = int(cleaned)
    return price if 1_000 <= price <= 500_000 else None


def prices_from_json_ld(document: str) -> list[int]:
    prices: list[int] = []
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def visit(node: Any, in_offer: bool = False) -> None:
        if isinstance(node, dict):
            node_type = str(node.get("@type", "")).lower()
            offer = in_offer or "offer" in node_type
            for key, value in node.items():
                if offer and key in {"price", "lowPrice"}:
                    parsed = parse_price(value)
                    if parsed is not None:
                        prices.append(parsed)
                visit(value, offer or key == "offers")
        elif isinstance(node, list):
            for item in node:
                visit(item, in_offer)

    for raw in scripts:
        try:
            visit(json.loads(unescape(raw)))
        except json.JSONDecodeError:
            continue
    return prices


def extract_price(document: str) -> int | None:
    """Extrait le prix annoncé en privilégiant les données structurées."""
    candidates = prices_from_json_ld(document)
    if candidates:
        return candidates[0]
    for pattern in PRICE_PATTERNS:
        match = re.search(pattern, document, flags=re.IGNORECASE | re.DOTALL)
        if match:
            price = parse_price(unescape(match.group(1)))
            if price is not None:
                return price
    return None


def extract_text(document: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, document, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = re.sub(r"<[^>]+>", " ", unescape(match.group(1)))
            return re.sub(r"\s+", " ", value).strip()
    return None


def infer_engine(value: str | None) -> str | None:
    """Normalise un moteur explicite sans compléter une motorisation ambiguë."""
    if not value:
        return None
    search_text = re.sub(r"[-_/]+", " ", value.lower())
    match = re.search(r"\b(2[,.\s]7|3[,.\s]5|3[,.\s]6|5[,.\s]0|5[,.\s]7)\s*([lt])?\b", search_text)
    if not match:
        return None
    engine = re.sub(r"[ ,]", ".", match.group(1)) + "L"
    turbo_ford = match.group(2) == "t" and ("ford" in search_text or re.search(r"\bf\s*150\b", search_text))
    if "ecoboost" in search_text or turbo_ford:
        engine += " EcoBoost"
    elif "duramax" in search_text or "diesel" in search_text:
        engine += " Diesel"
    return engine


def extract_listing_metadata(document: str, url: str) -> dict[str, Any]:
    """Extrait les champs utiles au tableau de bord depuis une fiche véhicule."""
    title = extract_text(
        document,
        (
            r"<h1[^>]*>(.*?)</h1>",
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
            r"<title[^>]*>(.*?)</title>",
        ),
    )
    description = extract_text(
        document,
        (
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        ),
    )

    def json_value(key: str) -> str | None:
        match = re.search(rf'["\']{re.escape(key)}["\']\s*:\s*["\']([^"\']+)', document)
        return unescape(match.group(1)).strip() if match else None

    image = extract_text(
        document,
        (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        ),
    ) or json_value("img")
    mileage = parse_price(json_value("stmil"))
    year_raw = json_value("year")
    year = int(year_raw) if year_raw and year_raw.isdigit() else None
    city = json_value("city")
    province = json_value("province")
    search_text = " ".join(value for value in (title, description, url) if value).lower()
    search_text = re.sub(r"[-_/]+", " ", search_text)

    engine = infer_engine(search_text)
    trim = next(
        (value for value in ("Lariat", "XLT", "XTR", "Platinum", "King Ranch", "SR5", "TRD", "SR", "SLT", "SLE", "Custom") if value.lower() in search_text),
        None,
    )
    if re.search(r"double\s*cab|double\s+cabine|cabine\s+double", search_text):
        cab = "Double Cab"
        cab_class = "double_cab"
    elif re.search(r"access\s*cab|cabine\s+d['’]?acc[eè]s", search_text):
        cab = "Access Cab"
        cab_class = "access_cab"
    elif re.search(r"super\s*crew|crew\s*cab|cabine\s+supercrew|cabine\s+multiplace", search_text):
        cab = "SuperCrew"
        cab_class = "crew_cab"
    else:
        cab = None
        cab_class = "unknown"
    make = next((value for value in ("Toyota", "Ford", "Ram", "Chevrolet", "GMC", "Nissan") if value.lower() in search_text), None)
    model_patterns = (
        ("Tacoma", r"\btacoma\b"),
        ("F-150", r"\bf\s*150\b"),
        ("Silverado", r"\bsilverado\b"),
        ("Sierra", r"\bsierra\b"),
        ("Frontier", r"\bfrontier\b"),
        ("1500", r"\bram\s+1500\b"),
    )
    model = next((value for value, pattern in model_patterns if re.search(pattern, search_text)), None)
    transmission = "automatic" if re.search(r"\bautomatique\b|\bautomatic\b|\bba\b", search_text) else None
    drivetrain = "4WD" if re.search(r"\b4x4\b|\b4wd\b|\b4rm\b", search_text) else None
    return {
        "title": title,
        "description": description,
        "image": image,
        "mileage": mileage,
        "year": year,
        "location": ", ".join(value.replace("_", " ").title() for value in (city, province) if value),
        "engine": engine,
        "trim": trim,
        "cab": cab,
        "cab_class": cab_class,
        "make": make,
        "model": model,
        "transmission": transmission,
        "drivetrain": drivetrain,
    }


def fetch_listing(
    url: str,
    timeout: float,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.7",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status_code = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
            final_url = response.geturl()
    except HTTPError as exc:
        if exc.code in {404, 410}:
            return {"status": "unavailable", "price": None, "http_status": exc.code}
        return {
            "status": "fetch_error",
            "price": None,
            "http_status": exc.code,
            "error": f"HTTP {exc.code}",
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "status": "fetch_error",
            "price": None,
            "http_status": None,
            "error": str(exc),
        }

    normalized = unescape(body).lower()
    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in UNAVAILABLE_PATTERNS):
        return {
            "status": "unavailable",
            "price": None,
            "http_status": status_code,
            "final_url": final_url,
        }
    price = extract_price(body)
    metadata = extract_listing_metadata(body, final_url)
    return {
        "status": "active" if price is not None else "unknown",
        "price": price,
        "http_status": status_code,
        "final_url": final_url,
        **metadata,
        **({"error": "prix introuvable dans la page"} if price is None else {}),
    }


def classify(reference: dict[str, Any], current: dict[str, Any]) -> str:
    if current["status"] in {"unavailable", "fetch_error", "unknown"}:
        return current["status"]
    old_price = reference.get("price")
    new_price = current.get("price")
    if old_price is None or new_price is None:
        return "unknown"
    if new_price < old_price:
        return "price_down"
    if new_price > old_price:
        return "price_up"
    return "unchanged"


def build_report(reference: dict[str, Any], timeout: float) -> dict[str, Any]:
    results = []
    for listing in reference["listings"]:
        current = fetch_listing(listing["url"], timeout)
        change = classify(listing, current)
        results.append(
            {
                "id": listing["id"],
                "name": listing["name"],
                "url": listing["url"],
                "reference": {"status": listing.get("status"), "price": listing.get("price")},
                "current": current,
                "change": change,
                "price_delta": (
                    current["price"] - listing["price"]
                    if current.get("price") is not None and listing.get("price") is not None
                    else None
                ),
            }
        )
    counts = {key: 0 for key in ("unchanged", "price_down", "price_up", "unavailable", "fetch_error", "unknown")}
    for result in results:
        counts[result["change"]] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_checked_at": reference.get("checked_at"),
        "counts": counts,
        "listings": results,
    }


def format_summary(report: dict[str, Any]) -> str:
    labels = {
        "unchanged": "INCHANGÉE",
        "price_down": "PRIX BAISSÉ",
        "price_up": "PRIX MONTÉ",
        "unavailable": "DISPARUE",
        "fetch_error": "ERREUR DE LECTURE",
        "unknown": "STATUT INCONNU",
    }
    lines = [
        "# Rapport de veille des annonces",
        "",
        f"Généré : {report['generated_at']}",
        f"Référence : {report.get('reference_checked_at') or 'non datée'}",
        "",
    ]
    for item in report["listings"]:
        current = item["current"]
        price = f"{current['price']:,} $".replace(",", " ") if current.get("price") else "—"
        delta = item.get("price_delta")
        delta_text = f" ({delta:+,} $)".replace(",", " ") if delta else ""
        detail = current.get("error")
        lines.append(f"- [{labels[item['change']]}] {item['name']} : {price}{delta_text}")
        if detail:
            lines.append(f"  Détail : {detail}")
    counts = report["counts"]
    lines.extend(
        [
            "",
            "## Totaux",
            "",
            ", ".join(f"{labels[key].lower()} : {value}" for key, value in counts.items()),
            "",
            "> Une erreur de lecture ou un statut inconnu n'est jamais assimilé à une annonce disparue.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=Path("data/reference.json"))
    parser.add_argument("--json", type=Path, default=Path("reports/latest.json"))
    parser.add_argument("--summary", type=Path, default=Path("reports/latest.md"))
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    report = build_report(reference, args.timeout)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = format_summary(report)
    args.summary.write_text(summary, encoding="utf-8")
    print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
