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
4. Un Durable Object unique sérialise les commandes et conserve l’heure du dernier dispatch. Il relit d’abord l’état GitHub : une reprise ne déclenche un scan que sur la transition réelle `paused → running`; répétitions et requêtes concurrentes restent sans effet.
5. `Arrêter` appelle l’API GitHub `disable` du workflow : le prochain déclenchement planifié ne part pas. Un run déjà commencé peut se terminer et la page l’annonce explicitement.
6. `Reprendre` appelle `enable`, puis un seul `workflow_dispatch` pour produire immédiatement des données fraîches. Un délai persistant de cinq minutes empêche une alternance Arrêter/Reprendre de lancer des runs en boucle; la reprise réactive alors la planification sans dispatch immédiat et retourne `dispatch: cooldown`, `next_dispatch_at` et `Retry-After`. Si le dispatch échoue après l’activation, la réponse conserve l’état réel `running` et la page affiche que le prochain scan planifié demeure actif.

La page ne connaît que l’URL publique du Worker. CORS est limité à l’origine GitHub Pages configurée. Références API :

- https://docs.github.com/en/rest/actions/workflows#disable-a-workflow
- https://docs.github.com/en/rest/actions/workflows#enable-a-workflow
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/

## Mise en service — seulement après GO

1. Miroiter le dépôt Buzz vers un dépôt GitHub privé ou public selon le choix du propriétaire.
2. Configurer GitHub Pages avec **GitHub Actions** comme source.
3. Créer un jeton finement limité ou une GitHub App installée sur **ce seul dépôt**, avec uniquement `Actions: write`; ne donner ni `Contents: write`, ni `Administration`, ni portée organisationnelle. Le stocker via `wrangler secret put GITHUB_TOKEN`.
4. Copier `control-worker/wrangler.toml.example` vers `wrangler.toml` et remplir les valeurs publiques.
5. Déployer le Worker, puis créer une application Cloudflare Access devant son domaine avec une politique limitée aux deux courriels autorisés. Configurer un bypass Access limité aux requêtes `OPTIONS` afin que le prévol CORS sans cookie atteigne le Worker; les `GET` et `POST` restent protégés par Access.
6. Renseigner l’URL du Worker dans `docs/config.js`.
7. Ouvrir directement l’URL du Worker une première fois dans chaque navigateur afin de terminer la connexion Access, puis revenir au tableau.
8. Fusionner la PR uniquement après validation finale.

## Contrat CORS et Access

- Le Worker répond au prévol `OPTIONS` sans exiger de JWT, mais seulement si `Origin` égale exactement `APP_ORIGIN`.
- Tout `POST` venant d’une autre origine reçoit `403` avant l’authentification et sans en-tête CORS permissif.
- Les réponses de contrôle portent `Cache-Control: no-store`.
- Le bypass Cloudflare ne doit viser que `OPTIONS`; il ne faut jamais exempter `/api/control` ou l’ensemble de l’application Access.

Validation locale du prévol, avant tout déploiement :

```bash
curl -i -X OPTIONS "$CONTROL_URL/api/control" \
  -H "Origin: https://OWNER.github.io" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```

Le résultat attendu est `204`, avec `Access-Control-Allow-Origin` égal à l’origine Pages. Une origine différente doit recevoir `403`.

## Limites assumées

- La découverte dépend de la structure HTML d’AutoHebdo; une rupture produit un état `partial`, jamais un faux « aucun deal » silencieux.
- Le cache GitHub Actions conserve l’historique minimal entre les runs sans écrire de commits automatisés signés au nom d’un humain. GitHub peut purger un cache inactif; le tableau conserve au moins le dernier instantané livré.
- Avant déploiement, les boutons restent désactivés et annoncent clairement que la passerelle attend le GO.
