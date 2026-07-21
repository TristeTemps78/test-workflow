# CLAUDE.md — test-workflow

Pipeline de tri d'un export Google Photos (Takeout). Voir `README.md` pour
l'usage. Ce fichier donne le contexte aux sessions Claude Code.
L'avancement et les priorités sont dans `ROADMAP.md` — le consulter en
début de session et le mettre à jour (cases + journal) en fin de tâche.

## Commandes

```bash
pip install -r requirements.txt
apt-get install -y libimage-exiftool-perl tesseract-ocr tesseract-ocr-fra
python3 tests/make_fixtures.py                                   # jeu d'essai
python3 run_pipeline.py --source tests/fixtures/Takeout --out out  # pipeline complet
python3 run_pipeline.py --source ... --out out --export           # après validation
```

Test de non-régression : le pipeline sur les fixtures doit donner
28 médias, 3 drop (1 doublon exact + 2 copies de dossier d'album),
9 review (2 quasi-doublons, 1 screenshot, 1 live_companion, 2 photos
ratées flou/sombre, 1 reçue WhatsApp, 1 document, 1 mème), 16 keep,
6 événements ; étape faces : 5 visages, 1 personne, et la photo WhatsApp
doit être enrichie de « contient person-01 » ; export : 1 exception,
1 album Takeout dans albums.json ("Vacances Rome", 2 photos).
Les portraits de test viennent du sdist PyPI de face_recognition
(voir tests/make_fixtures.py) — réseau : seul PyPI est accessible
depuis la VM, GitHub est limité à ce repo.

## Architecture

- `triage/db.py` — manifeste SQLite (`out/manifest.db`), mémoire persistante :
  toutes les étapes lisent/écrivent là, le pipeline est reprenable.
- `triage/inventory.py` — scan + appariement JSON Takeout. La fonction
  `match_sidecar` concentre les cas tordus de nommage : ne pas la simplifier
  sans faire tourner les fixtures.
- `triage/dedupe.py` — SHA-256 (exact) puis phash par journée (quasi-doublons).
- `triage/classify.py` — screenshots, compagnons Live Photos, contenu
  (reçues messagerie par nom de fichier WA/FB, documents et mèmes par OCR
  tesseract fra+eng), qualité (flou/exposition), événements (rupture
  temporelle > 8 h). L'OCR est ciblé (screenshots, images sans EXIF
  appareil, photos très claires) pour rester rapide sur de gros volumes.
- `triage/export.py` — copies propres + fusion JSON→EXIF (exiftool).
  Ne modifie JAMAIS les originaux. Toute photo sans date fiable va dans
  `out/exceptions.txt`, jamais exportée silencieusement.
- `triage/report.py` — rapport HTML autonome (miniatures base64).
- `triage/faces.py` — visages : détection + empreintes (face_recognition),
  clustering chinese-whispers (dlib), albums par personne. 100 % local,
  aucune photo n'est envoyée à un service externe — invariant à conserver.
  Nommage des personnes : `out/people_names.json`.

## Invariants à respecter

1. **Jamais de suppression automatique** : le pipeline propose (`drop`/`review`),
   l'humain dispose via le rapport (cases à cocher → decisions.json →
   `--apply`). Seuls les doublons exacts sont `drop`.
1bis. **Garde-fou albums** : une photo appartenant à un album (info fusionnée
   depuis les dossiers d'albums Takeout) n'est jamais proposée à la
   suppression — sa disparition casserait l'album, potentiellement partagé.
   La qualité technique (netteté/luminosité) ne produit que des `review` :
   une photo floue de soirée peut avoir du charme, seul l'humain en juge.
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
