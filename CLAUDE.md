# CLAUDE.md — test-workflow

Pipeline de tri d'un export Google Photos (Takeout). Voir `README.md` pour
l'usage. Ce fichier donne le contexte aux sessions Claude Code.

## Commandes

```bash
pip install -r requirements.txt && apt-get install -y libimage-exiftool-perl
python3 tests/make_fixtures.py                                   # jeu d'essai
python3 run_pipeline.py --source tests/fixtures/Takeout --out out  # pipeline complet
python3 run_pipeline.py --source ... --out out --export           # après validation
```

Test de non-régression : le pipeline sur les fixtures doit donner
17 médias, 1 drop (doublon exact), 4 review (2 quasi-doublons, 1 screenshot,
1 live_companion), 12 keep, 5 événements, 1 exception à l'export.

## Architecture

- `triage/db.py` — manifeste SQLite (`out/manifest.db`), mémoire persistante :
  toutes les étapes lisent/écrivent là, le pipeline est reprenable.
- `triage/inventory.py` — scan + appariement JSON Takeout. La fonction
  `match_sidecar` concentre les cas tordus de nommage : ne pas la simplifier
  sans faire tourner les fixtures.
- `triage/dedupe.py` — SHA-256 (exact) puis phash par journée (quasi-doublons).
- `triage/classify.py` — screenshots, compagnons Live Photos, événements
  (rupture temporelle > 8 h).
- `triage/export.py` — copies propres + fusion JSON→EXIF (exiftool).
  Ne modifie JAMAIS les originaux. Toute photo sans date fiable va dans
  `out/exceptions.txt`, jamais exportée silencieusement.
- `triage/report.py` — rapport HTML autonome (miniatures base64).

## Invariants à respecter

1. **Jamais de suppression automatique** : le pipeline propose (`drop`/`review`),
   l'humain dispose via le rapport. Seuls les doublons exacts sont `drop`.
2. **Jamais d'upload sans EXIF vérifié** : Google Photos date à l'upload toute
   photo sans `DateTimeOriginal` — c'est la chronologie de l'utilisateur qui
   est en jeu.
3. **Les photos ne vont jamais dans git** : seuls le code et le manifeste de
   test. `out/`, `data/`, `tests/fixtures/` sont gitignorés.
4. Réglage Google Photos "Qualité d'origine" obligatoire avant tout ré-upload
   (sinon double compression).

## Contexte projet

Données réelles : archives Takeout déposées dans le Google Drive de
l'utilisateur (connecteur Drive disponible en session cloud), à télécharger
et dézipper dans `data/` (gitignoré, l'espace disque VM est limité — traiter
zip par zip). La suppression dans Google Photos et le ré-upload (rclone ou
app de bureau) sont des étapes manuelles/externes documentées dans README.md.
