"""Inventaire : scanne l'export Takeout et remplit le manifeste.

Points délicats traités ici :
- appariement photo <-> JSON sidecar malgré les noms tordus de Takeout
  (".supplemental-metadata.json", suffixes "(1)", fichiers "-edited",
  noms tronqués) ;
- lecture EXIF en un seul appel exiftool récursif (rapide) ;
- hash SHA-256 (doublons exacts) et hash perceptuel (quasi-doublons) ;
- reprise : un fichier déjà inventorié (même taille/mtime) n'est pas retraité.
"""

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import imagehash
from PIL import Image
from pillow_heif import register_heif_opener

from .db import connect

register_heif_opener()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif",
              ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".m4v", ".3gp", ".mkv", ".mts",
              ".mp", ".mv", ".webm"}

# Takeout tronque le nom du média dans le nom du JSON au-delà de ~46 chars.
TRUNCATE_LEN = 46


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_stats(path: Path) -> tuple[str | None, float | None, float | None]:
    """(phash, netteté, luminosité). Netteté = variance du laplacien sur une
    version réduite (échelle comparable entre photos) ; luminosité 0-255."""
    try:
        import numpy as np
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            ph = str(imagehash.phash(rgb))
            gray = rgb.convert("L")
            gray.thumbnail((800, 800))
            g = np.asarray(gray, dtype=np.float32)
        if min(g.shape) < 3:
            return ph, None, float(g.mean())
        lap = (4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1]
               - g[1:-1, :-2] - g[1:-1, 2:])
        return ph, float(lap.var()), float(g.mean())
    except Exception:
        return None, None, None


def _album_title(directory: Path) -> str | None:
    """Nom d'album si le dossier est un album Takeout (et non 'Photos from YYYY')."""
    if re.fullmatch(r"Photos from \d{4}", directory.name):
        return None
    meta = directory / "metadata.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("title") \
            or directory.name
    except Exception:
        return directory.name


def _exiftool_scan(source: Path) -> dict[str, dict]:
    """Un seul appel exiftool récursif ; retourne {chemin: métadonnées}."""
    cmd = ["exiftool", "-j", "-n", "-fast2", "-r",
           "-DateTimeOriginal", "-CreateDate", "-Make", "-Model",
           "-ImageWidth", "-ImageHeight", "-Duration", "-MIMEType",
           str(source)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        entries = json.loads(res.stdout or "[]")
    except json.JSONDecodeError:
        entries = []
    return {str(Path(e["SourceFile"]).resolve()): e for e in entries}


def _parse_exif_dt(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.strptime(value[:19], "%Y:%m:%d %H:%M:%S").timestamp())
    except ValueError:
        return None


def match_sidecar(media_name: str, json_names: set[str]) -> str | None:
    """Retrouve le JSON Takeout d'un média parmi les JSON du même dossier."""
    candidates = [media_name]
    # IMG_001(1).jpg -> IMG_001.jpg(1).json
    m = re.match(r"^(.*)(\(\d+\))(\.[^.]+)$", media_name)
    if m:
        candidates.append(f"{m.group(1)}{m.group(3)}{m.group(2)}")
    # IMG_001-edited.jpg partage le JSON de IMG_001.jpg
    m = re.match(r"^(.*)-(?:edited|modifié)(\.[^.]+)$", media_name, re.I)
    if m:
        candidates.append(f"{m.group(1)}{m.group(2)}")

    for cand in candidates:
        for jname in (f"{cand}.json", f"{cand}.supplemental-metadata.json"):
            if jname in json_names:
                return jname
        # suffixes supplémentaires variables (ex. ".supplemental-metad.json")
        prefix = f"{cand}."
        for jname in json_names:
            if jname.startswith(prefix) and jname.endswith(".json"):
                return jname
        # nom tronqué dans le JSON
        if len(cand) > TRUNCATE_LEN:
            trunc = cand[:TRUNCATE_LEN]
            for jname in json_names:
                if jname.startswith(trunc) and jname.endswith(".json"):
                    return jname
    return None


def _parse_sidecar(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    ts = (data.get("photoTakenTime") or {}).get("timestamp")
    if ts:
        out["json_ts"] = int(ts)
    for key in ("geoDataExif", "geoData"):
        geo = data.get(key) or {}
        if geo.get("latitude") or geo.get("longitude"):
            out["gps_lat"] = geo["latitude"]
            out["gps_lon"] = geo["longitude"]
            break
    if data.get("description"):
        out["description"] = data["description"]
    return out


def run(source: str | Path, out_dir: str | Path) -> dict:
    source = Path(source).resolve()
    con = connect(out_dir)
    exif = _exiftool_scan(source)

    seen = skipped = 0
    for directory in sorted({p.parent for p in source.rglob("*") if p.is_file()}):
        album = _album_title(directory)
        json_names = {p.name for p in directory.iterdir()
                      if p.suffix.lower() == ".json"}
        for path in sorted(directory.iterdir()):
            ext = path.suffix.lower()
            if not path.is_file() or ext == ".json":
                continue
            kind = ("image" if ext in IMAGE_EXTS
                    else "video" if ext in VIDEO_EXTS else "other")
            if kind == "other":
                continue
            stat = path.stat()
            row = con.execute(
                "SELECT size, mtime FROM media WHERE path = ?", (str(path),)
            ).fetchone()
            if row and row["size"] == stat.st_size and row["mtime"] == stat.st_mtime:
                skipped += 1
                continue

            meta = exif.get(str(path.resolve()), {})
            sidecar = {}
            jname = match_sidecar(path.name, json_names)
            if jname:
                sidecar = _parse_sidecar(directory / jname)
                sidecar["json_path"] = str(directory / jname)

            exif_dt = meta.get("DateTimeOriginal") or meta.get("CreateDate")
            taken = (sidecar.get("json_ts") or _parse_exif_dt(exif_dt)
                     or int(stat.st_mtime))
            camera = " ".join(x for x in (meta.get("Make"), meta.get("Model")) if x) or None

            phash, sharp, bright = (_image_stats(path) if kind == "image"
                                    else (None, None, None))
            con.execute(
                """INSERT OR REPLACE INTO media
                   (path, filename, dirname, ext, kind, size, mtime, sha256,
                    phash, sharpness, brightness, source_album, albums,
                    width, height, exif_dt, camera, duration, json_path,
                    json_ts, gps_lat, gps_lon, description, taken_ts, category)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(path), path.name, str(directory), ext, kind,
                 stat.st_size, stat.st_mtime, _sha256(path),
                 phash, sharp, bright, album, album,
                 meta.get("ImageWidth"), meta.get("ImageHeight"),
                 exif_dt, camera, meta.get("Duration"),
                 sidecar.get("json_path"), sidecar.get("json_ts"),
                 sidecar.get("gps_lat"), sidecar.get("gps_lon"),
                 sidecar.get("description"), taken,
                 "video" if kind == "video" else "photo"))
            seen += 1
    con.commit()

    total = con.execute("SELECT COUNT(*) c FROM media").fetchone()["c"]
    no_json = con.execute(
        "SELECT COUNT(*) c FROM media WHERE json_path IS NULL").fetchone()["c"]
    con.close()
    return {"nouveaux": seen, "inchangés": skipped,
            "total": total, "sans_json": no_json}
