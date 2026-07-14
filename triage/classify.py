"""Classification : screenshots, compagnons de Live Photos, contenu
(documents, mèmes, photos reçues via messagerie), qualité, événements.

- Screenshot : nom de fichier explicite, ou PNG sans EXIF appareil photo
  -> proposition `review` (suppression suggérée, à valider).
- Compagnon Live Photo : vidéo courte portant le même nom qu'une photo du
  même dossier (Takeout sépare les Live Photos iPhone en HEIC/JPG + MP4).
  On propose de ne garder que la photo pour ne pas polluer la galerie.
- Événements : les médias gardés sont regroupés par proximité temporelle
  (rupture > 8 h = nouvel événement). Chaque événement devient un dossier
  (= un album si ré-upload par API).
"""

import re
import subprocess
from datetime import datetime, timezone

from .db import connect

SCREENSHOT_RE = re.compile(r"(?i)(screen[_ ]?shot|screenshot|capture)")

# Fichiers arrivés par messagerie / réseaux sociaux, pas pris par l'utilisateur.
# IMG-20240101-WA0007.jpg = WhatsApp ; FB_IMG_, received_, Snapchat-...
RECEIVED_RE = re.compile(
    r"(?i)^(IMG|VID)-\d{8}-WA\d+|^FB_IMG_|^received_|^Snapchat-|^unnamed(\(\d+\))?\.")

# OCR : au-delà de ce nombre de mots, une image est probablement un document.
DOC_MIN_WORDS = 40
# Entre MEME_MIN et DOC_MIN mots sur une image sans EXIF appareil : mème probable.
MEME_MIN_WORDS = 4
EVENT_GAP_SECONDS = 8 * 3600
LIVE_MAX_DURATION = 7   # secondes

# Qualité technique. Volontairement prudents : une photo "ratée" n'est
# JAMAIS supprimée d'office (les photos de soirée floues ont leur charme),
# c'est une proposition à valider dans le rapport, avec son contexte.
BLUR_THRESHOLD = 40     # variance du laplacien en dessous = probablement floue
DARK_THRESHOLD = 35     # luminosité moyenne (0-255)
BRIGHT_THRESHOLD = 225


def _ocr(path: str) -> str:
    """Texte lu dans l'image (français + anglais), '' si rien/échec."""
    try:
        res = subprocess.run(
            ["tesseract", path, "stdout", "-l", "fra+eng", "--psm", "3"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        return " ".join(res.stdout.split())
    except Exception:
        return ""


def _word_count(text: str) -> int:
    return sum(1 for w in text.split() if len(w) >= 3 and any(c.isalpha() for c in w))


def run(out_dir) -> dict:
    con = connect(out_dir)

    # --- compagnons de Live Photos ---
    live = 0
    videos = con.execute(
        "SELECT * FROM media WHERE kind = 'video' AND decision = 'keep'"
    ).fetchall()
    for v in videos:
        stem = v["filename"].rsplit(".", 1)[0].lower()
        twin = con.execute(
            """SELECT 1 FROM media WHERE kind = 'image' AND dirname = ?
               AND LOWER(filename) LIKE ? LIMIT 1""",
            (v["dirname"], f"{stem}.%")).fetchone()
        short = v["duration"] is None or v["duration"] <= LIVE_MAX_DURATION
        if twin and short:
            con.execute(
                """UPDATE media SET category = 'live_companion',
                   decision = 'review',
                   reason = 'mini-vidéo issue d''une Live Photo (photo conservée à côté)'
                   WHERE path = ?""", (v["path"],))
            live += 1

    # --- screenshots ---
    shots = 0
    images = con.execute(
        "SELECT * FROM media WHERE kind = 'image' AND decision = 'keep'"
    ).fetchall()
    for im in images:
        by_name = bool(SCREENSHOT_RE.search(im["filename"]))
        by_shape = im["ext"] == ".png" and not im["camera"]
        if by_name or by_shape:
            con.execute(
                """UPDATE media SET category = 'screenshot',
                   decision = 'review', reason = ?
                   WHERE path = ?""",
                ("capture d'écran (nom de fichier)" if by_name
                 else "capture d'écran probable (PNG sans appareil photo)",
                 im["path"]))
            shots += 1

    # --- contenu : reçues via messagerie, documents, mèmes ---
    # OCR ciblé pour rester rapide : screenshots (extrait affiché dans le
    # rapport), images sans EXIF appareil (candidates mème/document) et
    # photos d'appareil très claires (candidates document papier).
    received = docs = memes = 0
    for im in con.execute(
            """SELECT * FROM media WHERE kind = 'image'
               AND decision IN ('keep', 'review')""").fetchall():
        if RECEIVED_RE.match(im["filename"]) and im["decision"] == "keep":
            con.execute(
                """UPDATE media SET category = 'received', decision = 'review',
                   reason = ? WHERE path = ?""",
                ("reçue via messagerie (WhatsApp/réseaux sociaux), "
                 "pas prise par toi", im["path"]))
            received += 1
            continue

        is_screenshot = im["category"] == "screenshot"
        no_camera = not im["camera"]
        bright_camera = (im["camera"] and im["brightness"]
                         and im["brightness"] > 170)
        if not (is_screenshot or no_camera or bright_camera):
            continue
        text = im["ocr_text"] if im["ocr_text"] is not None else _ocr(im["path"])
        con.execute("UPDATE media SET ocr_text = ? WHERE path = ?",
                    (text, im["path"]))
        if is_screenshot or im["decision"] != "keep":
            continue
        words = _word_count(text)
        if words >= DOC_MIN_WORDS:
            con.execute(
                """UPDATE media SET category = 'document', decision = 'review',
                   reason = ? WHERE path = ?""",
                (f"document ({words} mots lus)", im["path"]))
            docs += 1
        elif no_camera and words >= MEME_MIN_WORDS:
            con.execute(
                """UPDATE media SET category = 'meme', decision = 'review',
                   reason = ? WHERE path = ?""",
                (f"mème probable (texte incrusté, aucune donnée d'appareil photo)",
                 im["path"]))
            memes += 1

    # --- photos ratées (flou / exposition) : proposition, jamais d'office ---
    low_quality = 0
    for im in con.execute(
            """SELECT * FROM media WHERE kind = 'image' AND decision = 'keep'
               AND category = 'photo'""").fetchall():
        problems = []
        if im["sharpness"] is not None and im["sharpness"] < BLUR_THRESHOLD:
            problems.append("floue")
        if im["brightness"] is not None:
            if im["brightness"] < DARK_THRESHOLD:
                problems.append("très sombre")
            elif im["brightness"] > BRIGHT_THRESHOLD:
                problems.append("surexposée")
        if problems:
            con.execute(
                """UPDATE media SET category = 'low_quality',
                   decision = 'review', reason = ? WHERE path = ?""",
                ("photo probablement ratée : " + ", ".join(problems),
                 im["path"]))
            low_quality += 1

    # --- garde-fou albums : une photo d'un album n'est jamais proposée
    #     à la suppression (sa disparition casserait l'album, partagé ou non).
    #     Exception : les copies de dossier d'album dont l'original est gardé.
    protected = 0
    for im in con.execute(
            """SELECT * FROM media WHERE decision = 'review'
               AND albums IS NOT NULL AND albums != ''""").fetchall():
        con.execute(
            """UPDATE media SET decision = 'keep', reason = ? WHERE path = ?""",
            (f"protégée : présente dans l'album « {im['albums']} » "
             f"(proposition initiale : {im['reason']})", im["path"]))
        protected += 1

    # --- événements ---
    rows = con.execute(
        "SELECT path, taken_ts FROM media WHERE decision = 'keep' ORDER BY taken_ts"
    ).fetchall()
    events = 0
    current: list = []

    def flush(batch):
        nonlocal events
        if not batch:
            return
        events += 1
        first = datetime.fromtimestamp(batch[0]["taken_ts"], tz=timezone.utc)
        last = datetime.fromtimestamp(batch[-1]["taken_ts"], tz=timezone.utc)
        label = first.strftime("%Y-%m-%d")
        if last.date() != first.date():
            label += last.strftime("..%d") if last.month == first.month \
                else last.strftime("..%m-%d")
        for r in batch:
            con.execute("UPDATE media SET event = ? WHERE path = ?",
                        (label, r["path"]))

    for r in rows:
        if current and r["taken_ts"] - current[-1]["taken_ts"] > EVENT_GAP_SECONDS:
            flush(current)
            current = []
        current.append(r)
    flush(current)

    con.commit()
    con.close()
    return {"live_companions": live, "screenshots": shots,
            "reçues_messagerie": received, "documents": docs, "mèmes": memes,
            "photos_ratées": low_quality, "protégées_par_album": protected,
            "événements": events}
