# Photo Triage — pipeline de tri d'un export Google Photos (Takeout)

Trie un export Google Takeout : doublons exacts et quasi-doublons (rafales),
captures d'écran, mini-vidéos de Live Photos, regroupement en événements,
puis export d'une arborescence propre avec **dates et GPS réinjectés dans
l'EXIF** (sans quoi un ré-upload vers Google Photos détruirait la chronologie).

## Démarrage rapide

```bash
pip install -r requirements.txt          # + exiftool (apt install libimage-exiftool-perl)
python3 tests/make_fixtures.py           # jeu d'essai synthétique
python3 run_pipeline.py --source tests/fixtures/Takeout --out out
# ouvrir out/report.html, valider, puis :
python3 run_pipeline.py --source tests/fixtures/Takeout --out out --steps report --export
```

Avec un vrai export : dézipper les archives Takeout dans un dossier et le
passer en `--source`. Le manifeste (`out/manifest.db`) rend le pipeline
**reprenable** : relancer ne retraite que les nouveaux fichiers.

## Étapes

| Étape | Rôle |
|---|---|
| `inventory` | scan, appariement photo↔JSON Takeout (noms tronqués, `(1)`, `-edited`, `.supplemental-metadata`), dossiers d'albums, EXIF, SHA-256, hash perceptuel, scores netteté/luminosité |
| `dedupe` | doublons exacts → `drop` (copies de dossiers d'albums fusionnées, appartenance conservée) ; quasi-doublons du même jour → `review`, la plus nette gardée |
| `classify` | screenshots, compagnons de Live Photos, photos ratées (flou/exposition, `review` uniquement), garde-fou albums (jamais de suppression proposée sur une photo d'album), découpage en événements |
| `faces` | détection de visages + clustering local (dlib) → personnes `person-01`, `person-02`, … |
| `report` | rapport HTML interactif : cases à cocher sur chaque proposition, bouton d'export `decisions.json` |
| `--apply decisions.json` | applique les choix faits dans le rapport au manifeste |
| `--export` | copie les `keep` dans `out/cleaned/<événement>/` + fusion JSON→EXIF via exiftool ; `out/albums.json` (albums Takeout à recréer) ; cas douteux dans `out/exceptions.txt` |
| `--people` | albums par personne dans `out/albums_people/<nom>/` ; noms via `out/people_names.json` (`{"person-01": "Maman"}`, `""` = ignorer) |

## Décisions

`keep` (gardée), `drop` (doublon exact, suppression sûre), `review`
(proposition à valider dans le rapport). Les originaux Takeout ne sont
jamais modifiés ; seules les copies de `out/cleaned/` reçoivent l'EXIF corrigé.

## Après le tri (hors pipeline)

- **Purge guidée** : supprimer dans Google Photos les éléments du rapport
  (la photothèque d'origine reste intacte : Live Photos, visages, partages).
- **Albums** : ré-upload de `out/cleaned/` via `rclone` (API) — chaque dossier
  devient un album. Quota API ≈ lent sur gros volume.
- **Remplacement complet** : voir les mises en garde dans `CLAUDE.md`
  (Live Photos, partages, reconnaissance faciale, qualité d'origine).

[GPTH Neo](https://github.com/Xentraxx/GooglePhotosTakeoutHelper) peut servir
de pré-processeur (dates EXIF, doublons exacts, albums) ; ce pipeline apporte
en plus les quasi-doublons, la classification et le rapport de validation.
