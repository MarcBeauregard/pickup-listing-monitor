# Architecture de la veille automatisée

## Flux de données

```text
AutoHebdo (pages de recherche + fiches)
          │
          ▼
scan_deals.py — Python standard, aucun LLM
          │
          ├── docs/data/deals.json
          └── docs/data/history.json
                     │
                     ▼
             GitHub Pages (lecture seule)
```

Le workflow `.github/workflows/pickup-watch.yml` s’exécute toutes les six heures et sur demande. Il restaure l’historique depuis le cache GitHub Actions, lance le scan, construit un artefact Pages puis le publie. Aucun appel à un modèle, aucune clé d’IA et aucun coût en jetons.

## Pourquoi une passerelle est nécessaire

GitHub Pages est un hébergement statique. Il ne peut pas désactiver un workflow GitHub sans posséder un identifiant capable d’écrire dans le dépôt; placer cet identifiant dans JavaScript l’exposerait à tout visiteur.

La solution minimale est `control-worker/`, un Cloudflare Worker :

1. Cloudflare Access authentifie Marc et sa conjointe.
2. Le Worker revérifie cryptographiquement le JWT Access et l’adresse courriel autorisée.
3. Un jeton GitHub finement limité reste uniquement dans les secrets du Worker.
4. `Arrêter` appelle l’API GitHub `disable` du workflow : le prochain déclenchement planifié ne part pas.
5. `Reprendre` appelle `enable`, puis `workflow_dispatch` pour produire immédiatement des données fraîches.

La page ne connaît que l’URL publique du Worker. CORS est limité à l’origine GitHub Pages configurée. Références API :

- https://docs.github.com/en/rest/actions/workflows#disable-a-workflow
- https://docs.github.com/en/rest/actions/workflows#enable-a-workflow
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/

## Mise en service — seulement après GO

1. Miroiter le dépôt Buzz vers un dépôt GitHub privé ou public selon le choix du propriétaire.
2. Configurer GitHub Pages avec **GitHub Actions** comme source.
3. Créer un jeton GitHub à portée minimale pour ce seul dépôt et le stocker via `wrangler secret put GITHUB_TOKEN`.
4. Copier `control-worker/wrangler.toml.example` vers `wrangler.toml` et remplir les valeurs publiques.
5. Déployer le Worker, puis créer une application Cloudflare Access devant son domaine avec une politique limitée aux deux courriels autorisés.
6. Renseigner l’URL du Worker dans `docs/config.js`.
7. Ouvrir directement l’URL du Worker une première fois dans chaque navigateur afin de terminer la connexion Access, puis revenir au tableau.
8. Fusionner la PR uniquement après validation finale.

## Limites assumées

- La découverte dépend de la structure HTML d’AutoHebdo; une rupture produit un état `partial`, jamais un faux « aucun deal » silencieux.
- Le cache GitHub Actions conserve l’historique minimal entre les runs sans écrire de commits automatisés signés au nom d’un humain. GitHub peut purger un cache inactif; le tableau conserve au moins le dernier instantané livré.
- Avant déploiement, les boutons restent désactivés et annoncent clairement que la passerelle attend le GO.

