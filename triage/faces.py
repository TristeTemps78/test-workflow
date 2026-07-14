"""Personnes : détection de visages, clustering, albums par personne.

Tout est local (dlib/face_recognition) : aucune photo ne quitte la machine.

- détection + empreinte faciale (vecteur 128-d) pour chaque photo gardée ;
- clustering "chinese whispers" : les visages similaires forment une personne
  (person-01, person-02, ... classées par nombre de photos) ;
- le rapport montre les visages de chaque groupe ; l'utilisateur nomme les
  personnes dans out/people_names.json ({"person-01": "Maman"}) ;
- export_albums copie chaque photo dans out/albums_people/<nom>/ pour chaque
  personne présente (une photo de groupe apparaît dans plusieurs albums).

Reprise : les photos déjà scannées (table face_scan) ne sont pas retraitées.
"""

import json
import shutil
from pathlib import Path

import dlib
import face_recognition
import numpy as np
from PIL import Image

from .db import connect

try:  # pas de wheel win_arm64 : sans pillow-heif, les HEIC ne sont pas lus
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

CLUSTER_THRESHOLD = 0.5   # distance max entre deux visages d'une même personne
MAX_PIXELS = 1600         # les grandes photos sont réduites avant détection

FACES_SCHEMA = """
CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    top INTEGER, right INTEGER, bottom INTEGER, left INTEGER,
    encoding BLOB NOT NULL,
    cluster TEXT
);
CREATE TABLE IF NOT EXISTS face_scan (path TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS idx_faces_path ON faces (path);
"""


def _load_rgb(path: str) -> tuple[np.ndarray, float]:
    """Image RGB réduite si besoin ; retourne (tableau, facteur d'échelle)."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        scale = 1.0
        longest = max(im.size)
        if longest > MAX_PIXELS:
            scale = MAX_PIXELS / longest
            im = im.resize((round(im.width * scale), round(im.height * scale)))
        return np.asarray(im), scale


def run(out_dir) -> dict:
    con = connect(out_dir)
    con.executescript(FACES_SCHEMA)

    # Les photos reçues (review) sont scannées aussi : le croisement
    # visages connus/inconnus fait partie de la proposition.
    rows = con.execute(
        """SELECT path FROM media
           WHERE kind = 'image'
             AND (decision = 'keep' OR category = 'received')
             AND category NOT IN ('screenshot')
             AND path NOT IN (SELECT path FROM face_scan)"""
    ).fetchall()

    scanned = found = 0
    for row in rows:
        try:
            img, scale = _load_rgb(row["path"])
            locs = face_recognition.face_locations(img)
            encs = face_recognition.face_encodings(img, locs)
        except Exception:
            locs, encs, scale = [], [], 1.0
        for (top, right, bottom, left), enc in zip(locs, encs):
            con.execute(
                """INSERT INTO faces (path, top, right, bottom, left, encoding)
                   VALUES (?,?,?,?,?,?)""",
                (row["path"], int(top / scale), int(right / scale),
                 int(bottom / scale), int(left / scale),
                 np.asarray(enc, dtype=np.float64).tobytes()))
            found += 1
        con.execute("INSERT INTO face_scan (path) VALUES (?)", (row["path"],))
        scanned += 1
    con.commit()

    # --- clustering global (recalculé à chaque passage : peu coûteux) ---
    faces = con.execute("SELECT id, encoding FROM faces").fetchall()
    clusters = 0
    if faces:
        vectors = [dlib.vector(np.frombuffer(f["encoding"]).tolist())
                   for f in faces]
        labels = dlib.chinese_whispers_clustering(vectors, CLUSTER_THRESHOLD)
        counts: dict[int, int] = {}
        for lab in labels:
            counts[lab] = counts.get(lab, 0) + 1
        # person-01 = personne la plus photographiée ; visages isolés ignorés
        order = [lab for lab, c in
                 sorted(counts.items(), key=lambda kv: -kv[1]) if c >= 2]
        names = {lab: f"person-{i + 1:02d}" for i, lab in enumerate(order)}
        for face, lab in zip(faces, labels):
            con.execute("UPDATE faces SET cluster = ? WHERE id = ?",
                        (names.get(lab), face["id"]))
        clusters = len(names)

    # Croisement avec les photos reçues par messagerie : des visages qui ne
    # correspondent à aucune personne récurrente de la photothèque renforcent
    # la proposition (famille éloignée / inconnus) ; l'inverse la nuance.
    for im in con.execute(
            "SELECT * FROM media WHERE category = 'received'").fetchall():
        face_clusters = [r["cluster"] for r in con.execute(
            "SELECT cluster FROM faces WHERE path = ?", (im["path"],))]
        if not face_clusters:
            continue
        known = sorted({c for c in face_clusters if c})
        note = (f"contient {', '.join(known)} — à vérifier avant suppression"
                if known else
                "visages inconnus (aucune personne récurrente de ta photothèque)")
        if note not in (im["reason"] or ""):
            con.execute("UPDATE media SET reason = ? WHERE path = ?",
                        (f"{im['reason']} ; {note}", im["path"]))
    con.commit()
    con.close()
    return {"photos_scannées": scanned, "visages": found,
            "personnes": clusters}


def export_albums(out_dir) -> dict:
    """Copie chaque photo dans l'album de chaque personne reconnue dessus.

    Les noms viennent de out/people_names.json s'il existe ; une personne
    absente de ce fichier garde son identifiant person-XX. Valeur "" ou null
    = personne ignorée (pas d'album).
    """
    out = Path(out_dir)
    con = connect(out_dir)
    names = {}
    names_file = out / "people_names.json"
    if names_file.exists():
        names = json.loads(names_file.read_text(encoding="utf-8"))

    albums = out / "albums_people"
    copied = 0
    rows = con.execute(
        """SELECT DISTINCT f.cluster, m.path, m.filename FROM faces f
           JOIN media m ON m.path = f.path
           WHERE f.cluster IS NOT NULL AND m.decision = 'keep'"""
    ).fetchall()
    for row in rows:
        label = names.get(row["cluster"], row["cluster"])
        if not label:
            continue
        dest_dir = albums / label
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / row["filename"]
        if not dest.exists():
            shutil.copy2(row["path"], dest)
            copied += 1
    con.close()
    return {"albums": len({r["cluster"] for r in rows}), "copies": copied}
