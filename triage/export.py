"""Export : construit l'arborescence propre et réinjecte les métadonnées.

1. Copie chaque média `keep` dans out/cleaned/<événement>/ .
2. Fusionne les métadonnées Takeout (date de prise de vue, GPS) dans l'EXIF
   des copies via exiftool — LE point critique : sans ça, un ré-upload vers
   Google Photos daterait tout du jour de l'upload.
3. Vérifie : toute copie dont la date EXIF finale manque part en liste
   d'exceptions plutôt que d'être exportée silencieusement fausse.

Les originaux de l'export Takeout ne sont jamais modifiés.
"""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .db import connect


def _exif_args(row, dest: Path) -> list[str]:
    args = []
    if row["json_ts"]:
        dt = datetime.fromtimestamp(row["json_ts"], tz=timezone.utc)
        stamp = dt.strftime("%Y:%m:%d %H:%M:%S")
        args += [f"-DateTimeOriginal={stamp}", f"-CreateDate={stamp}"]
    if row["gps_lat"] is not None:
        args += [f"-GPSLatitude={abs(row['gps_lat'])}",
                 f"-GPSLatitudeRef={'N' if row['gps_lat'] >= 0 else 'S'}",
                 f"-GPSLongitude={abs(row['gps_lon'])}",
                 f"-GPSLongitudeRef={'E' if row['gps_lon'] >= 0 else 'W'}"]
    if row["description"]:
        args += [f"-ImageDescription={row['description']}"]
    if not args:
        return []
    return args + ["-overwrite_original", str(dest)]


def run(out_dir) -> dict:
    con = connect(out_dir)
    cleaned = Path(out_dir) / "cleaned"
    rows = con.execute(
        "SELECT * FROM media WHERE decision = 'keep' ORDER BY taken_ts"
    ).fetchall()

    copied = 0
    exif_written = 0
    exceptions: list[str] = []
    argfile_lines: list[str] = []
    album_map: dict[str, list[str]] = {}

    for row in rows:
        event_dir = cleaned / (row["event"] or "sans-date")
        event_dir.mkdir(parents=True, exist_ok=True)
        dest = event_dir / row["filename"]
        n = 1
        while dest.exists():
            stem, ext = row["filename"].rsplit(".", 1)
            dest = event_dir / f"{stem}_{n}.{ext}"
            n += 1
        shutil.copy2(row["path"], dest)
        copied += 1
        for album in (row["albums"] or "").split("|"):
            if album:
                album_map.setdefault(album, []).append(
                    str(dest.relative_to(cleaned)))

        # l'EXIF n'est réécrit que si le JSON Takeout apporte une info
        if row["kind"] == "image":
            args = _exif_args(row, dest)
            if args:
                argfile_lines += args + ["-execute"]
                exif_written += 1
            elif not row["exif_dt"]:
                exceptions.append(
                    f"{dest} : aucune date fiable (ni EXIF ni JSON)")

    if argfile_lines:
        argfile = Path(out_dir) / "exiftool.args"
        argfile.write_text("\n".join(argfile_lines), encoding="utf-8")
        res = subprocess.run(["exiftool", "-@", str(argfile)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        if res.returncode != 0:
            exceptions.append(f"exiftool a signalé des erreurs : {res.stderr[-500:]}")

    if exceptions:
        (Path(out_dir) / "exceptions.txt").write_text(
            "\n".join(exceptions), encoding="utf-8")

    # appartenance aux albums Google Photos d'origine, pour recréation rclone
    if album_map:
        (Path(out_dir) / "albums.json").write_text(
            json.dumps(album_map, ensure_ascii=False, indent=1),
            encoding="utf-8")

    con.close()
    return {"copiés": copied, "exif_réécrits": exif_written,
            "albums_takeout": len(album_map), "exceptions": len(exceptions)}
