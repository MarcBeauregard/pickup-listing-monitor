# Vigie Pickup

Veille automatisée sans LLM et tableau mobile pour repérer les Ford F-150 EcoBoost SuperCrew qui respectent le budget familial.

Le dépôt contient deux parcours complémentaires :

- `monitor.py` vérifie les dix annonces historiques;
- `scan_deals.py` découvre de nouvelles annonces dans les pages de recherche, vérifie chaque fiche et alimente la webapp statique dans `docs/`.

Le moniteur initial produit :

- un rapport JSON structuré;
- un résumé Markdown lisible;
- une comparaison avec le prix de référence (`price_down`, `price_up`, `unchanged`, `unavailable`).

Les erreurs HTTP, les blocages anti-bot et les pages dont le prix est illisible restent explicitement séparés des annonces disparues.

## Exécution

```bash
python3 monitor.py
python3 scan_deals.py
```

Options utiles :

```bash
python3 monitor.py \
  --reference data/reference.json \
  --json reports/latest.json \
  --summary reports/latest.md \
  --timeout 20
```

## Tests

```bash
python3 -m unittest discover -s tests -v
cd control-worker && npm test
```

## Aperçu local

```bash
python3 tools/preview_server.py
```

Ouvrir ensuite `http://127.0.0.1:4173/?controlApi=http://127.0.0.1:4173` pour tester aussi Arrêter/Reprendre. Ce serveur est une démonstration locale; la passerelle de production authentifiée est dans `control-worker/`.

L’architecture, le compromis GitHub Pages et la mise en service après GO sont documentés dans [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Enrichissements sourcés

Les notes vendeur et consommations ne sont jamais collectées ou devinées par le scanner. Consultez [`docs/ENRICHMENT_SCHEMA.md`](docs/ENRICHMENT_SCHEMA.md) pour le contrat rétrocompatible, les preuves obligatoires et la correspondance mécanique exacte.
