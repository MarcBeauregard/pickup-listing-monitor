# Matrice — vignette Google de confiance vendeur

| État | Vignette fermée | Panneau ouvert | Éléments interdits |
|---|---|---|---|
| Complet | `Confiance vendeur`, note Google, étoiles et nombre d’avis; risque rouge/jaune visible | Réputation sourcée, date, composantes disponibles, signal juridique et preuves | Score de confiance à la place de la note Google; rangée vide |
| Partiel | `Information insuffisante` pour Google; risque juridique visible s’il est prouvé | Seulement les sections réellement disponibles, par exemple le signal juridique | Note ou volume deviné; section Réputation Google vide |
| Aucune donnée | `Confiance vendeur` et `Information insuffisante` | Uniquement `Information insuffisante` | Tableau, titre, séparateur, source ou date vide |

Le contrôle reste un `<details>/<summary>` natif : clic, Entrée et Espace ouvrent ou ferment le panneau. La pertinence de l’annonce demeure un indicateur indépendant.

## Couverture de l’instantané validé

- 13 fiches ont une note Google complète et affichent la note ainsi que le nombre d’avis dans la vignette.
- 18 fiches ont un signal juridique exploitable sans note Google complète; elles affichent `Information insuffisante` pour Google et conservent le risque prouvé.
- 96 fiches n’ont aucun détail vendeur exploitable et rendent uniquement `Information insuffisante` dans le panneau.

## Vérification

- 5/5 tests DOM Node : états complet, partiel, explication sans signal juridique, aucune donnée et balayage des 127 fiches.
- 61/61 tests Python, incluant le contrat DOM.
- 59/59 tests de formule de confiance.
- 9/9 tests du Worker, sans modification de son code ni de son déploiement.
- Analyse syntaxique JavaScript et contrôle du diff : verts.
