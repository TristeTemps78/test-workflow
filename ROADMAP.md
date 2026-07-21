# Roadmap — Photo Triage

Suivi du projet de session en session. À tenir à jour : cocher ce qui est
fait, dater les entrées du journal, garder « En cours » minimal (1-2 sujets).
Les invariants de `CLAUDE.md` priment sur tout ce qui est listé ici.

## Fait

- [x] Pipeline complet : inventory → dedupe → classify → report, export
      EXIF (exiftool), rapport HTML interactif, `--apply decisions.json`.
- [x] Visages : détection + clustering local (dlib), albums par personne
      (`--people`, noms via `out/people_names.json`).
- [x] Classification par contenu : screenshots, reçues messagerie,
      documents, mèmes (OCR tesseract fra+eng ciblé), qualité flou/sombre.
- [x] Albums Takeout préservés (garde-fou : jamais de drop sur une photo
      d'album) + `out/albums.json`.
- [x] Exécution locale Windows (2026-07-14) : UTF-8 forcé sur les
      subprocess (bug cp1252 → EXIF perdus), pillow-heif optionnel
      (pas de wheel win_arm64), police portable dans les fixtures.
      Validé sur les fixtures ET sur un vrai Takeout (331 photos).

## En cours

- [ ] **Visages en local (Windows ARM64)** : compilation de dlib depuis les
      sources avec VS Community 2026 (MSVC 14.51 arm64) + CMake embarqué.
      Puis `face_recognition` + `face_recognition_models`, et validation du
      test de non-régression faces : 5 visages, 1 personne, photo WhatsApp
      enrichie de « contient person-01 ».

## À faire (par priorité)

1. [ ] **Albums par événement (opt-in, jamais automatique)** : dans le
       rapport, case « créer un album » par événement ; l'export ajoute les
       événements cochés à `out/albums.json` à côté des albums Takeout.
       Décision humaine, cohérent avec l'invariant n° 1.
2. [ ] **Rapport scalable (bloquant avant le vrai Takeout complet)** : le
       rapport actuel embarque toutes les miniatures en base64 dans un seul
       HTML — intenable à 10 000+ photos. Pagination par événement,
       filtres (catégorie/décision/année), miniatures dans un dossier
       `out/thumbs/` chargées à la demande plutôt qu'inlinées.
3. [ ] **Nommage des événements par lieu (100 % local)** : géocodage
       inverse hors-ligne (dataset embarqué type `reverse_geocoder`) sur
       les GPS déjà extraits → « Août 2009 — Rome » au lieu de dates
       brutes. Aucune coordonnée envoyée à un service externe (invariant
       faces étendu : rien ne sort de la machine).
4. [ ] **« Meilleures photos » par événement** : proposer (jamais imposer)
       un best-of par événement en combinant les scores existants
       (netteté, exposition) + présence de visages → album « favoris » à
       valider dans le rapport. Réutilise sharpness/brightness/faces déjà
       en base.
5. [ ] **Quasi-doublons trans-journées** : la rafale à cheval sur minuit et
       le doublon retouché ré-uploadé des années après échappent au phash
       « par journée ». Second passage phash global (seuil plus strict)
       sur les seuls `keep`.

## Hors pipeline (manuel, documenté dans README)

- Purge guidée dans Google Photos d'après le rapport.
- Ré-upload `out/cleaned/` via rclone ou app de bureau — réglage
  « Qualité d'origine » obligatoire (invariant n° 4).

## Journal

- **2026-07-14** — Premier run local complet (Windows 11 ARM64, Python
  3.14). Installés : exiftool + tesseract (winget, fra dans
  `%LOCALAPPDATA%\tessdata` via `TESSDATA_PREFIX`). Bug cp1252 corrigé
  (PR #1). Test de non-régression conforme ; run réel : 331 photos,
  314 dates EXIF, 9 groupes de rafales, 15 review, 81 événements.
  Étape faces : dlib en cours de compilation (VS 2026 détecté).
