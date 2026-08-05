# Pickup Listing Monitor

Script Python sans dépendance externe qui charge les dix annonces de référence, extrait leur prix et leur statut, puis produit :

- un rapport JSON structuré;
- un résumé Markdown lisible;
- une comparaison avec le prix de référence (`price_down`, `price_up`, `unchanged`, `unavailable`).

Les erreurs HTTP, les blocages anti-bot et les pages dont le prix est illisible restent explicitement séparés des annonces disparues.

## Exécution

```bash
python3 monitor.py
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
```
