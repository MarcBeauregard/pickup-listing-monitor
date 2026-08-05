#!/usr/bin/env python3
"""Découvre et publie des deals de pickups pour le tableau statique."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from monitor import USER_AGENT, fetch_listing


TAX_RATE = 0.14975
UNKNOWN_ENRICHMENT = {"status": "unconfirmed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_html(url: str, timeout: float) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.7",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def discover_urls(document: str, source: dict[str, Any]) -> list[str]:
    domain = source.get("listing_domain", "www.autohebdo.net")
    listing_path = source.get("listing_path_pattern", r"/annonces/[^\"'<>\s]+")
    absolute = re.findall(rf'https?://{re.escape(domain)}{listing_path}', document, flags=re.IGNORECASE)
    relative = re.findall(rf'["\']({listing_path})', document, flags=re.IGNORECASE)
    candidates = [unescape(url).rstrip("/,") for url in absolute]
    base_url = source.get("base_url", f"https://{domain}")
    candidates.extend(urljoin(base_url, unescape(url).rstrip("/,")) for url in relative)
    unique = []
    seen = set()
    for url in candidates:
        parts = urlsplit(url)
        canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
        if canonical not in seen:
            seen.add(canonical)
            unique.append(canonical)
    return unique[: int(source.get("max_listings", 30))]


def monthly_payment(price: int, annual_rate: float = 0.07, months: int = 84) -> int:
    principal = price * (1 + TAX_RATE)
    monthly_rate = annual_rate / 12
    payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -months)
    return round(payment)


def evaluate(current: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, list[str], int]:
    reasons = []
    score = 100
    price = current.get("price")
    year = current.get("year")
    mileage = current.get("mileage")
    title = " ".join(
        str(value or "")
        for value in (current.get("title"), current.get("description"), current.get("engine"), current.get("trim"), current.get("cab"))
    ).lower()

    profiles = criteria.get("profiles", [])
    if profiles:
        profile = next((item for item in profiles if item.get("model") == current.get("model")), None)
        if not profile:
            reasons.append("modèle hors sélection")
            score -= 40
        else:
            allowed_cabs = profile.get("cab_classes", [])
            if allowed_cabs and current.get("cab_class") not in allowed_cabs:
                reasons.append(profile.get("cab_reason", "grande cabine non confirmée"))
                score -= 25
            engine_terms = profile.get("engine_terms", [])
            if engine_terms and not any(term.lower() in title for term in engine_terms):
                reasons.append("motorisation admissible non confirmée")
                score -= 25
            trims = profile.get("trims", [])
            if trims and not any(trim.lower() in title for trim in trims):
                reasons.append("finition admissible non confirmée")
                score -= 15

    if current.get("status") != "active":
        reasons.append("annonce inactive ou illisible")
        score -= 100
    if price is None or price > criteria["max_price"]:
        reasons.append("prix hors cible ou inconnu")
        score -= 35
    elif criteria.get("min_monthly") and monthly_payment(price) < criteria["min_monthly"]:
        reasons.append("paiement estimé sous la fourchette")
        score -= 10
    elif criteria.get("max_monthly") and monthly_payment(price) > criteria["max_monthly"]:
        reasons.append("paiement estimé au-dessus de la fourchette")
        score -= 35
    if year is None or year < criteria["min_year"]:
        reasons.append("année hors cible ou inconnue")
        score -= 20
    if mileage is None:
        reasons.append("kilométrage inconnu")
        score -= 15
    elif mileage > criteria["max_mileage"]:
        reasons.append("kilométrage au-dessus de la cible")
        score -= 25
    if not profiles and not any(term.lower() in title for term in criteria["engine_terms"]):
        reasons.append("EcoBoost 2.7L/3.5L non confirmé")
        score -= 25
    if not profiles and criteria.get("require_supercrew") and not any(term in title for term in ("supercrew", "super crew", "crew cab")):
        reasons.append("cabine SuperCrew non confirmée")
        score -= 25
    if not profiles and not any(trim.lower() in title for trim in criteria["trims"]):
        reasons.append("finition Lariat/XLT non confirmée")
        score -= 15

    eligible = not reasons
    if eligible:
        if current.get("trim") == "Lariat":
            score += 15
        if mileage is not None and mileage <= 100_000:
            score += 10
        if price is not None and monthly_payment(price) <= 700:
            score += 5
    return eligible, reasons, max(score, 0)


def deal_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def unconfirmed(value: dict[str, Any] | None = None, *, mechanical_mismatch: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = dict(UNKNOWN_ENRICHMENT)
    if value:
        if isinstance(value.get("name"), str) and value["name"].strip():
            result["name"] = value["name"].strip()
        if isinstance(value.get("reason"), str) and value["reason"].strip():
            result["reason"] = value["reason"].strip()
    if mechanical_mismatch and "reason" not in result:
        result["reason"] = "configuration mécanique non concordante"
    return result


def normalized_mechanical(field: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if field == "transmission" and ("automatic" in normalized or "automatique" in normalized or "as10" in normalized):
        return "automatic"
    if field == "drivetrain" and ("4wd" in normalized or "4x4" in normalized or "4rm" in normalized):
        return "4WD"
    return value.strip()


def enrichment_for(url: str, current: dict[str, Any], enrichments: dict[str, Any]) -> dict[str, Any]:
    """Retourne uniquement un enrichissement dont l'annonce et la mécanique concordent exactement."""
    entry = next((item for item in enrichments.get("listings", []) if item.get("url") == url), None)
    if not entry:
        return {"seller_reputation": unconfirmed(), "fuel_economy": unconfirmed()}

    seller = entry.get("seller_reputation") or UNKNOWN_ENRICHMENT
    fuel = entry.get("fuel_economy") or UNKNOWN_ENRICHMENT
    seller_fields = ("name", "rating", "review_count", "source_url", "verified_at")
    seller_confirmed = (
        seller.get("status") == "confirmed"
        and all(seller.get(field) is not None for field in seller_fields)
        and isinstance(seller.get("rating"), (int, float))
        and 0 <= seller["rating"] <= 5
        and isinstance(seller.get("review_count"), int)
        and seller["review_count"] >= 0
        and str(seller.get("source_url", "")).startswith("https://")
    )
    required = fuel.get("match", {})
    mechanical_fields = ("year", "engine", "transmission", "drivetrain")
    fuel_fields = ("city_l_per_100km", "highway_l_per_100km", "source_url", "verified_at")
    exact_match = (
        fuel.get("status") == "confirmed"
        and all(fuel.get(field) is not None for field in fuel_fields)
        and all(isinstance(fuel.get(field), (int, float)) and 0 < fuel[field] < 100 for field in ("city_l_per_100km", "highway_l_per_100km"))
        and str(fuel.get("source_url", "")).startswith("https://")
        and all(
            required.get(field) is not None
            and normalized_mechanical(field, required.get(field)) == normalized_mechanical(field, current.get(field))
            for field in mechanical_fields
        )
    )
    return {
        "seller_reputation": seller if seller_confirmed else unconfirmed(seller),
        "fuel_economy": fuel if exact_match else unconfirmed(fuel, mechanical_mismatch=fuel.get("status") == "confirmed"),
    }


def scan(
    config: dict[str, Any],
    previous: dict[str, Any] | None,
    timeout: float,
    source_fetcher: Callable[[str, float], str] = fetch_html,
    listing_fetcher: Callable[[str, float], dict[str, Any]] = fetch_listing,
    enrichments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    discovered = []
    source_errors = []
    for source in config["sources"]:
        try:
            page = source_fetcher(source["url"], timeout)
            source_urls = discover_urls(page, source)
            if not source_urls:
                source_errors.append({"source": source["name"], "error": "aucune annonce découverte; structure possiblement changée"})
            discovered.extend(source_urls)
        except Exception as exc:  # la source doit être isolée du reste du scan
            source_errors.append({"source": source["name"], "error": str(exc)})

    urls = list(dict.fromkeys(discovered))
    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(len(urls), 1))) as executor:
        futures = {executor.submit(listing_fetcher, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                fetched[url] = future.result()
            except Exception as exc:
                fetched[url] = {"status": "fetch_error", "price": None, "error": str(exc)}

    previous_deals = {deal["id"]: deal for deal in (previous or {}).get("deals", [])}
    checked_at = utc_now()
    checked_datetime = datetime.fromisoformat(checked_at)
    deals = []
    for url in urls:
        current = fetched[url]
        eligible, reasons, score = evaluate(current, config["criteria"])
        identifier = deal_id(url)
        price = current.get("price")
        previous_deal = previous_deals.get(identifier, {})
        enrichment = enrichment_for(url, current, enrichments or {})
        first_seen_at = previous_deal.get("first_seen_at") or checked_at
        try:
            recent = checked_datetime - datetime.fromisoformat(first_seen_at) <= timedelta(hours=72)
        except ValueError:
            first_seen_at = checked_at
            recent = True
        deals.append(
            {
                "id": identifier,
                "title": current.get("title") or "Ford F-150 — détails à confirmer",
                "url": url,
                "image": current.get("image"),
                "price": price,
                "monthly_7pct": monthly_payment(price) if price else None,
                "year": current.get("year"),
                "mileage": current.get("mileage"),
                "engine": current.get("engine"),
                "trim": current.get("trim"),
                "cab": current.get("cab"),
                "cab_class": current.get("cab_class", "unknown"),
                "make": current.get("make"),
                "model": current.get("model"),
                "transmission": current.get("transmission"),
                "drivetrain": current.get("drivetrain"),
                "location": current.get("location"),
                **enrichment,
                "status": current.get("status"),
                "eligible": eligible,
                "score": score,
                "reasons": reasons,
                "first_seen_at": first_seen_at,
                "is_new": recent,
                "new_in_run": identifier not in previous_deals,
                "checked_at": checked_at,
            }
        )
    deals.sort(key=lambda item: (not item["eligible"], -item["score"], item["price"] or 999_999))
    return {
        "schema_version": 2,
        "last_checked_at": checked_at,
        "scan_status": "ok" if not source_errors else "partial",
        "source_errors": source_errors,
        "criteria": config["criteria"],
        "counts": {
            "discovered": len(deals),
            "eligible": sum(deal["eligible"] for deal in deals),
            "new": sum(deal["is_new"] for deal in deals),
            "new_eligible": sum(deal["is_new"] and deal["eligible"] for deal in deals),
            "new_in_run": sum(deal["new_in_run"] for deal in deals),
        },
        "deals": deals,
    }


def update_history(previous_history: list[dict[str, Any]], result: dict[str, Any]) -> list[dict[str, Any]]:
    entry = {
        "checked_at": result["last_checked_at"],
        "status": result["scan_status"],
        "discovered": result["counts"]["discovered"],
        "eligible": result["counts"]["eligible"],
        "new_ids": [deal["id"] for deal in result["deals"] if deal["new_in_run"]],
    }
    return ([entry] + previous_history)[:40]


def load_json(path: Path, fallback: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/sources.json"))
    parser.add_argument("--deals", type=Path, default=Path("docs/data/deals.json"))
    parser.add_argument("--history", type=Path, default=Path("docs/data/history.json"))
    parser.add_argument("--enrichments", type=Path, default=Path("data/enrichments.json"))
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_json(args.config, {})
    previous = load_json(args.deals, None)
    history = load_json(args.history, [])
    enrichments = load_json(args.enrichments, {"schema_version": 1, "listings": []})
    result = scan(config, previous, args.timeout, enrichments=enrichments)
    write_json(args.deals, result)
    write_json(args.history, update_history(history, result))
    print(json.dumps({"status": result["scan_status"], **result["counts"]}, ensure_ascii=False))
    return 0 if result["scan_status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
