"""Classification : screenshots, compagnons de Live Photos, événements.

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
from datetime import datetime, timezone

from .db import connect

SCREENSHOT_RE = re.compile(r"(?i)(screen[_ ]?shot|screenshot|capture)")
EVENT_GAP_SECONDS = 8 * 3600
LIVE_MAX_DURATION = 7   # secondes

# Qualité technique. Volontairement prudents : une photo "ratée" n'est
# JAMAIS supprimée d'office (les photos de soirée floues ont leur charme),
# c'est une proposition à valider dans le rapport, avec son contexte.
BLUR_THRESHOLD = 40     # variance du laplacien en dessous = probablement floue
DARK_THRESHOLD = 35     # luminosité moyenne (0-255)
BRIGHT_THRESHOLD = 225


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
            "photos_ratées": low_quality, "protégées_par_album": protected,
            "événements": events}
