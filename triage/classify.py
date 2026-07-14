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
LIVE_MAX_DURATION = 7  # secondes


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
    return {"live_companions": live, "screenshots": shots, "événements": events}
