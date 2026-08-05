"""
Formule de score de confiance vendeur — implémentation de référence.
Contrat: RESEARCH/PICKUP_SCORE_CONFIANCE_SPEC_2026-08-05.md
"""
import math
from datetime import date, datetime

BANDS = {
    "rouge": (0, 20),
    "jaune": (21, 50),
    "vigilance_homonymie": (51, 70),
}
NON_AUDITE_CAP = 80
F_MIN = 0.5          # plancher du multiplicateur de fraîcheur (jamais 0, jamais NaN)
F_STEP_DAYS = 90      # taille d'une tranche de décroissance
F_STEP_PENALTY = 0.05 # perte de multiplicateur par tranche de 90 jours

def parse_date(d):
    if isinstance(d, date):
        return d
    return datetime.strptime(d, "%Y-%m-%d").date()

def freshness_multiplier(verified_at, computed_at, invalid=False):
    """Retourne (F, days_elapsed_or_None, flag_invalid).
    Règle: date manquante ou invalide -> plancher F_MIN (jamais favorable, jamais NaN).
    Date future (verified_at > computed_at) -> traitée comme invalide -> plancher F_MIN.
    """
    if verified_at is None or invalid:
        return F_MIN, None, True
    try:
        v = parse_date(verified_at)
        c = parse_date(computed_at)
    except (ValueError, TypeError):
        return F_MIN, None, True
    days = (c - v).days
    if days < 0:
        # date future par rapport à computed_at -> invalide
        return F_MIN, days, True
    tranche = days // F_STEP_DAYS
    F = max(F_MIN, 1.0 - F_STEP_PENALTY * tranche)
    return round(F, 4), days, False

def reputation_base(rating, review_count, identity_confirmed):
    R = (rating / 5) * 70
    V = min(20, 20 * math.log10(review_count + 1) / 3)
    I = 10 if identity_confirmed else 0
    return round(R, 2), round(V, 2), round(I, 2), round(R + V + I, 2)

def trust_score(rating=None, review_count=None, identity_confirmed=None,
                 reputation_confirmed=True, legal_status="non_audité",
                 verified_at=None, computed_at=None, date_invalid=False):
    if computed_at is None:
        raise ValueError("computed_at est obligatoire (aucune horloge implicite)")

    if not reputation_confirmed or rating is None:
        R = V = I = base_raw = None
    else:
        R, V, I, base_raw = reputation_base(rating, review_count, identity_confirmed)

    F, days_elapsed, date_flag_invalid = freshness_multiplier(verified_at, computed_at, date_invalid)

    base_effective = None if base_raw is None else round(base_raw * F, 2)

    if legal_status in BANDS:
        lo, hi = BANDS[legal_status]
        if base_effective is None:
            score = float(lo)
            floor_applied = True
        else:
            score = round(lo + (hi - lo) * (base_effective / 100), 2)
            floor_applied = False
        band = [lo, hi]
    elif legal_status == "aucun_signal_audité":
        if base_effective is None:
            score = None
            floor_applied = True
        else:
            score = base_effective
            floor_applied = False
        band = None
    elif legal_status == "non_audité":
        if base_effective is None:
            score = None
            floor_applied = True
        else:
            score = round(min(base_effective, NON_AUDITE_CAP), 2)
            floor_applied = False
        band = [0, NON_AUDITE_CAP]
    else:
        raise ValueError(f"legal_status inconnu: {legal_status}")

    return {
        "score": score,
        "band": band,
        "legal_status": legal_status,
        "components": {
            "reputation_base_raw": base_raw,
            "reputation_base_effective": base_effective,
            "rating_points": R,
            "volume_points": V,
            "identity_points": I,
            "freshness_multiplier": F,
            "days_elapsed": days_elapsed,
            "date_invalid_or_missing": date_flag_invalid,
        },
        "floor_applied_missing_data": floor_applied,
    }
