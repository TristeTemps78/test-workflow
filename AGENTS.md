# AGENTS.md — test-workflow

> **Ce fichier est un pointeur.** Source de vérité = `CLAUDE.md` (contexte, commandes, test de
> non-régression, architecture). Ne pas la dupliquer ici.

Pipeline de tri d'un export Google Photos (Takeout) : inventaire → dédup → classification →
faces → export. Manifeste SQLite reprenable (`out/manifest.db`).

## Par où commencer
1. **`CLAUDE.md`** — commandes, architecture, **test de non-régression** (chiffres attendus sur fixtures).
2. **`ROADMAP.md`** — **avancement et priorités** (à consulter au boot, cocher/journaliser en fin de tâche).
3. `README.md` — usage.

## Protocole multi-agents (obligatoire)
- **Réservation via `ROADMAP.md`** (pas de TASKS.md concurrent) : marquer la tâche en cours
  `🔒 @<agent>` **et committer avant d'écrire**. Voir `../WORKFLOW.md`.
- Ne jamais forcer un verrou ; concurrence → `git worktree` + branche `agent/<agent>/<tâche>`.

## Commandes
```
pip install -r requirements.txt
python tests/make_fixtures.py
python run_pipeline.py --source tests/fixtures/Takeout --out out    # doit donner le compte de non-régression (voir CLAUDE.md)
```

## Contraintes dures
- Ne pas simplifier `triage/inventory.py::match_sidecar` sans faire tourner les fixtures.
- Respecter le compte de non-régression documenté dans `CLAUDE.md`.

## Fin de session
Cocher/mettre à jour `ROADMAP.md` (cases + journal), committer, pousser.
