# AGENTS.md — essence-turf

## GITHUB OWNERSHIP

```
GITHUB OWNERSHIP
- Canonical GitHub owner: BCNabilM.
- BCNabil is not an authorized repository owner.
- All new remotes, repository URLs, PR targets, workflows, badges, deployment
  scripts and documentation must use BCNabilM.
- Legacy BCNabil repository URLs must be migrated when encountered.
- BCNabil may remain only as a personal authentication or historical commit identity.
```

**Migration vérifiée le 2026-07-26** : `BCNabil` = 0 repository · `BCNabilM` = 41 repositories · statut COMPLETE.

Le remote de ce dépôt a été migré ce jour :
```
avant : ancien propriétaire `BCNabil` (compte personnel)
après : https://github.com/BCNabilM/essence-turf.git
```

### Formes autorisées
```
https://github.com/BCNabilM/<repository>
git@github.com:BCNabilM/<repository>.git
```

Les anciennes adresses de l'ancien propriétaire redirigent encore, mais **une redirection n'est pas
une configuration conforme** : toute occurrence rencontrée doit être migrée.

### Ce qui NE doit PAS être réécrit
Identité personnelle ≠ propriétaire de repository. On conserve tels quels : les noms d'auteur de
commits, l'adresse `137716711+BCNabil@users.noreply.github.com`, l'utilisateur authentifié `gh`,
et les **journaux/rapports datés** dont l'intégrité historique fait foi (réécrire un rapport daté
falsifierait un constat passé).

### Vérification
```bash
git remote -v
rg -n --hidden --glob '!.git/**' "github[.]com[:/]${LEGACY}/" .   # LEGACY=BCNabil
```
Résultat conforme : remote sous `BCNabilM`, accès distant fonctionnel, aucune URL `BCNabil/` active.
