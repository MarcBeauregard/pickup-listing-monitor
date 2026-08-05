import sys, os, json, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from trust_score import trust_score, freshness_multiplier, F_MIN, NON_AUDITE_CAP, BANDS

TODAY = "2026-08-05"
results = []
failures = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status, detail))
    if not cond:
        failures.append(name)

# ---------------------------------------------------------------
# 1) Points de fraîcheur demandés: 0, 30, 90, 181, 365 jours
# ---------------------------------------------------------------
freshness_points = {}
for days in [0, 30, 90, 181, 365]:
    verified = f"{2026-0}-01-01"  # placeholder, on calcule via un vrai delta ci-dessous
import datetime
base_date = datetime.date(2026, 8, 5)
for days in [0, 30, 90, 181, 365]:
    v = (base_date - datetime.timedelta(days=days)).isoformat()
    F, d, invalid = freshness_multiplier(v, TODAY)
    freshness_points[days] = F
    check(f"freshness[{days}j] jours calculés = {days}", d == days, f"obtenu {d}")
    check(f"freshness[{days}j] pas invalide", invalid is False)

check("F(0j) == 1.0", freshness_points[0] == 1.0, freshness_points)
check("F(30j) == 1.0 (avant 1re tranche de 90j)", freshness_points[30] == 1.0, freshness_points)
check("F(90j) == 0.95 (exactement au seuil, 1 tranche entamée)", freshness_points[90] == 0.95, freshness_points)
check("F(181j) == 0.90 (2 tranches)", freshness_points[181] == 0.90, freshness_points)
check("F(365j) == 0.80 (4 tranches)", freshness_points[365] == 0.80, freshness_points)

# ---------------------------------------------------------------
# 2) Valeurs exactement aux seuils (89 vs 90, 179 vs 180, 269 vs 270)
# ---------------------------------------------------------------
for lo, hi in [(89, 90), (179, 180), (269, 270), (359, 360)]:
    v_lo = (base_date - datetime.timedelta(days=lo)).isoformat()
    v_hi = (base_date - datetime.timedelta(days=hi)).isoformat()
    F_lo, _, _ = freshness_multiplier(v_lo, TODAY)
    F_hi, _, _ = freshness_multiplier(v_hi, TODAY)
    check(f"seuil {lo}j -> {hi}j: F strictement décroissant au passage de tranche",
          F_hi < F_lo, f"F({lo}j)={F_lo}, F({hi}j)={F_hi}")

# ---------------------------------------------------------------
# 3) Monotonie sur un balayage large (0 a 3000 jours, pas de 1)
# ---------------------------------------------------------------
prev = None
monotonic = True
for days in range(0, 3001):
    v = (base_date - datetime.timedelta(days=days)).isoformat()
    F, _, _ = freshness_multiplier(v, TODAY)
    if prev is not None and F > prev:
        monotonic = False
        break
    prev = F
check("monotonie stricte (non-croissante) de F sur 0-3000 jours", monotonic)

# ---------------------------------------------------------------
# 4) Plancher F_MIN jamais franchi, meme tres loin dans le temps
# ---------------------------------------------------------------
v_far = (base_date - datetime.timedelta(days=100000)).isoformat()
F_far, d_far, invalid_far = freshness_multiplier(v_far, TODAY)
check("F ne descend jamais sous F_MIN meme a 100000 jours", F_far == F_MIN, F_far)
check("date tres ancienne n'est pas marquee invalide (juste tres decayee)", invalid_far is False)

# ---------------------------------------------------------------
# 5) Date manquante -> plancher F_MIN, pas de NaN, pas de valeur favorable
# ---------------------------------------------------------------
F_missing, d_missing, invalid_missing = freshness_multiplier(None, TODAY)
check("date manquante -> F == F_MIN (plancher, pas favorable)", F_missing == F_MIN, F_missing)
check("date manquante -> pas de NaN", not (isinstance(F_missing, float) and math.isnan(F_missing)))
check("date manquante -> flag invalide=True", invalid_missing is True)

# ---------------------------------------------------------------
# 6) Date future -> traitee comme invalide -> plancher F_MIN
# ---------------------------------------------------------------
v_future = "2027-01-01"  # posterieure a computed_at 2026-08-05
F_future, d_future, invalid_future = freshness_multiplier(v_future, TODAY)
check("date future -> F == F_MIN", F_future == F_MIN, F_future)
check("date future -> flag invalide=True", invalid_future is True)

# ---------------------------------------------------------------
# 7) Date malformee (chaine invalide) -> plancher F_MIN, pas d'exception
# ---------------------------------------------------------------
try:
    F_bad, d_bad, invalid_bad = freshness_multiplier("pas-une-date", TODAY)
    no_exception = True
except Exception as e:
    F_bad, invalid_bad, no_exception = None, None, False
check("date malformee ne leve pas d'exception", no_exception)
if no_exception:
    check("date malformee -> F == F_MIN", F_bad == F_MIN, F_bad)
    check("date malformee -> flag invalide=True", invalid_bad is True)

# ---------------------------------------------------------------
# 8) Un rouge reste plafonne a 20, jaune a 50, homonymie a 70,
#    non-audite a 80 -- MEME avec note parfaite et fraicheur max
# ---------------------------------------------------------------
sweep_ratings = [1.0, 3.0, 4.5, 5.0]
sweep_reviews = [0, 1, 23, 400, 5000, 1_000_000]
sweep_days = [0, 30, 90, 181, 365, 900, 3650, 100000]

worst_case = {"rouge": 0, "jaune": 0, "vigilance_homonymie": 0, "non_audité": 0, "aucun_signal_audité": 0}
for legal in ["rouge", "jaune", "vigilance_homonymie", "non_audité", "aucun_signal_audité"]:
    max_score_seen = -1
    for rating in sweep_ratings:
        for rc in sweep_reviews:
            for days in sweep_days:
                v = (base_date - datetime.timedelta(days=days)).isoformat()
                r = trust_score(rating=rating, review_count=rc, identity_confirmed=True,
                                 reputation_confirmed=True, legal_status=legal,
                                 verified_at=v, computed_at=TODAY)
                s = r["score"]
                if s is not None and s > max_score_seen:
                    max_score_seen = s
    worst_case[legal] = max_score_seen

check("rouge: score maximal observe <= 20 sur tout le balayage", worst_case["rouge"] <= 20, worst_case["rouge"])
check("jaune: score maximal observe <= 50 sur tout le balayage", worst_case["jaune"] <= 50, worst_case["jaune"])
check("vigilance_homonymie: score maximal observe <= 70 sur tout le balayage", worst_case["vigilance_homonymie"] <= 70, worst_case["vigilance_homonymie"])
check("non_audité: score maximal observe <= 80 sur tout le balayage", worst_case["non_audité"] <= 80, worst_case["non_audité"])
check("aucun_signal_audité: score maximal observe <= 100 (pas de plafond additionnel)", worst_case["aucun_signal_audité"] <= 100, worst_case["aucun_signal_audité"])

# ---------------------------------------------------------------
# 9) Invariant explicite: meilleure note Google ne fait JAMAIS
#    depasser la borne haute de la bande juridique
# ---------------------------------------------------------------
for legal, (lo, hi) in list(BANDS.items()) + [("non_audité", (0, NON_AUDITE_CAP))]:
    r_low = trust_score(rating=1.0, review_count=1, identity_confirmed=False,
                         legal_status=legal, verified_at=TODAY, computed_at=TODAY)
    r_high = trust_score(rating=5.0, review_count=1_000_000, identity_confirmed=True,
                          legal_status=legal, verified_at=TODAY, computed_at=TODAY)
    check(f"{legal}: note haute >= note basse (monotone en reputation)",
          r_high["score"] >= r_low["score"], (r_low["score"], r_high["score"]))
    check(f"{legal}: meme la meilleure note ne depasse pas la borne haute {hi}",
          r_high["score"] <= hi, r_high["score"])

# ---------------------------------------------------------------
# 10) Invariant explicite: donnee manquante -> plancher prevu, jamais NaN,
#     jamais une valeur par defaut favorable (ex: pas de score = borne haute)
# ---------------------------------------------------------------
for legal, (lo, hi) in list(BANDS.items()):
    r_missing = trust_score(rating=None, review_count=None, identity_confirmed=None,
                             reputation_confirmed=False, legal_status=legal,
                             verified_at=None, computed_at=TODAY)
    check(f"{legal}: reputation manquante -> score == plancher {lo}",
          r_missing["score"] == lo, r_missing["score"])
    check(f"{legal}: reputation manquante -> pas de NaN",
          not (isinstance(r_missing["score"], float) and math.isnan(r_missing["score"])))

for legal in ["non_audité", "aucun_signal_audité"]:
    r_missing = trust_score(rating=None, review_count=None, identity_confirmed=None,
                             reputation_confirmed=False, legal_status=legal,
                             verified_at=None, computed_at=TODAY)
    check(f"{legal}: reputation manquante -> score == None (donnees insuffisantes), jamais une valeur favorable",
          r_missing["score"] is None, r_missing["score"])

# ---------------------------------------------------------------
# 11) Les 8 exemples historiques restent inchanges a date egale
#     (verified_at == computed_at == 2026-08-05 -> F == 1.0 -> aucun impact)
# ---------------------------------------------------------------
historical = [
    ("HGrégoire Carignan", dict(rating=4.1, review_count=1311, identity_confirmed=True, legal_status="rouge"), 17.48),
    ("Automobile En Direct Laval", dict(rating=4.1, review_count=2012, identity_confirmed=True, legal_status="rouge"), 17.48),
    ("Centre Liquidation BD", dict(rating=None, review_count=None, identity_confirmed=None, reputation_confirmed=False, legal_status="rouge"), 0.0),
    ("Honda St-Basile", dict(rating=4.5, review_count=2326, identity_confirmed=True, legal_status="jaune"), 47.97),
    ("Auto Durocher (Mirabel)", dict(rating=None, review_count=None, identity_confirmed=None, reputation_confirmed=False, legal_status="vigilance_homonymie"), 51.0),
    ("AutoFlash", dict(rating=4.7, review_count=2753, identity_confirmed=True, legal_status="non_audité"), 80.0),
    ("Auto Svetna", dict(rating=5.0, review_count=23, identity_confirmed=True, legal_status="non_audité"), 80.0),
    ("Autos Occasion LD", dict(rating=None, review_count=None, identity_confirmed=None, reputation_confirmed=False, legal_status="non_audité"), None),
]
regenerated = []
for name, kwargs, expected in historical:
    r = trust_score(verified_at=TODAY, computed_at=TODAY, **kwargs)
    check(f"historique '{name}': score inchange = {expected}", r["score"] == expected, r["score"])
    regenerated.append({"seller_name": name, "trust_score": r})

with open(os.path.join(os.path.dirname(__file__), '..', 'data', 'trust_score_examples.json'), 'w') as f:
    json.dump(regenerated, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------
print(f"\n{'='*70}\nRESULTATS: {len(results)} tests, {len(failures)} echecs\n{'='*70}")
for name, status, detail in results:
    marker = "OK " if status == "PASS" else "!! "
    print(f"{marker}{status:5s} | {name}" + (f"  (detail: {detail})" if status=='FAIL' else ""))

print(f"\nFraicheur calculee: {freshness_points}")
print(f"Pire cas par bande (doit respecter les plafonds): {worst_case}")

if failures:
    print(f"\nECHECS ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    if __name__ == "__main__":
        sys.exit(1)
    raise AssertionError(f"{len(failures)} preuves du score ont échoué")

print("\nTOUS LES TESTS PASSENT.")
if __name__ == "__main__":
    sys.exit(0)
