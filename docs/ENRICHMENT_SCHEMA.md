# Contrat d’enrichissement des annonces

Le collecteur d’annonces ne consulte ni Google Business Profile ni une source de consommation. Les valeurs validées sont fournies séparément dans `data/enrichments.json` et associées à l’URL canonique exacte de l’annonce.

```json
{
  "schema_version": 1,
  "listings": [
    {
      "url": "https://vendeur.example/annonce-123",
      "seller_reputation": {
        "status": "confirmed",
        "name": "Nom normalisé du commerce",
        "rating": 4.7,
        "review_count": 321,
        "source_url": "https://www.google.com/maps/...",
        "verified_at": "2026-08-05"
      },
      "fuel_economy": {
        "status": "confirmed",
        "city_l_per_100km": 12.8,
        "highway_l_per_100km": 10.0,
        "source_url": "https://source-officielle.example/...",
        "verified_at": "2026-08-05",
        "match": {
          "year": 2022,
          "engine": "2.7L EcoBoost",
          "transmission": "automatic",
          "drivetrain": "4WD"
        }
      }
    }
  ]
}
```

Une réputation n’est publiée que si les cinq champs de preuve sont présents. Une consommation n’est publiée que si les quatre caractéristiques mécaniques correspondent exactement aux données extraites de l’annonce. Toute donnée absente, incomplète ou ambiguë devient explicitement `{"status": "unconfirmed"}` dans la sortie; aucune valeur de remplacement n’est déduite silencieusement.

Un objet non confirmé peut conserver `name` et `reason` pour expliquer l’ambiguïté à l’écran. Il ne conserve jamais une note, un nombre d’avis ou une consommation qui n’a pas franchi la validation.

Les nouveaux sites de marché se configurent dans `data/sources.json` avec `listing_domain`, `base_url` et `listing_path_pattern`. Les URLs sont canonisées sans paramètres de suivi et dédupliquées entre les sources avant leur lecture.

## Risque juridique vendeur

Les signaux validés sont conservés séparément dans `data/seller_legal_signals.json`. Une alerte rouge ou jaune exige une URL d’annonce exacte, une entité ou un permis concordant et `branch_matched: true`. Une homonymie avec une entité différente utilise `status: "unattributed"`, `match_status: "different_entity"` et ne peut jamais devenir une alerte attribuée. Toute annonce absente de cette table affiche « aucun signal confirmé », jamais un statut vert.

Chaque signal conserve sa nature exacte, son type et sa date, l’entité, le permis ou NEQ, la succursale, la source HTTPS, la date de vérification et la base de concordance.
