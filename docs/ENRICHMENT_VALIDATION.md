# Validation du lot certifié du 5 août 2026

Fichiers contrôlés exactement :

- `REPOS/pickup-listing-monitor/data/enrichments.json`, livré par Denise;
- `REPOS/pickup-listing-monitor/docs/ENRICHMENT_SCHEMA.md`, contrat de validation.

La copie intégrée est validée automatiquement par `tools/validate_enrichments.py` contre le snapshot des 20 annonces existantes dans `docs/data/deals.json`.

## Résultat

| Contrôle | Résultat |
| --- | --- |
| URL du snapshot | 20 |
| Clés d’enrichissement uniques | 20 |
| Doublons, URL orphelines, URL manquantes | 0 / 0 / 0 |
| Réputations confirmées | 13 |
| Consommations confirmées | 6 |
| Dates invalides ou futures | 0 |
| Sources non HTTPS | 0 |
| Valeurs présentes sous statut `unconfirmed` | 0 |
| Correspondances année + moteur avec le snapshot | 6 / 6 |

Chaque consommation confirmée possède aussi les quatre clés mécaniques requises : année, moteur, transmission et rouage. Le snapshot v1 ne conservait pas transmission et rouage; ces deux valeurs certifiées sont donc montrées dans l’artefact de prévisualisation, tandis que le pipeline v2 ne les publie lors d’un scan réel que si les quatre valeurs extraites concordent exactement.

Une annonce encode son moteur dans le titre sous la forme `2.7T`. Un test dédié prouve sa normalisation explicite en `2.7L EcoBoost`; aucune motorisation absente ou ambiguë n’est complétée.

## Reproduction

```bash
python3 tools/validate_enrichments.py
python3 tools/build_enriched_preview.py
python3 -m unittest discover -s tests
npm test --prefix control-worker
```

La prévisualisation isolée se charge avec `?preview=enriched`. Elle contient les 20 cartes, 13 réputations confirmées et 6 consommations confirmées, ainsi que des cas `non confirmé` pour les deux catégories. Le fichier de production `docs/data/deals.json` reste inchangé.
