#!/usr/bin/env python3
"""Génère un faux export Google Takeout avec tous les pièges connus :

- doublon exact, quasi-doublons (rafale), screenshot, Live Photo séparée
  (JPG + MP4), fichier "-edited", suffixe "(1)", JSON ".supplemental-metadata",
  nom de fichier long au JSON tronqué, photo sans JSON du tout ;
- trois événements répartis sur 2023 et 2024, avec GPS.

Usage : python3 tests/make_fixtures.py [dossier_cible=tests/fixtures]
"""

import json
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

random.seed(42)


def fetch_face_photos() -> list[Path]:
    """Photos de test avec de vrais visages, tirées du sdist PyPI de
    face_recognition (2 personnes). Retourne [] si le réseau ne permet pas."""
    try:
        tmp = Path(tempfile.mkdtemp())
        subprocess.run(
            ["pip3", "download", "--no-binary", ":all:", "--no-deps",
             "-q", "-d", str(tmp), "face_recognition"],
            check=True, capture_output=True, timeout=120)
        archive = next(tmp.glob("face_recognition-*.tar.gz"))
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        images = sorted(next(tmp.glob("*/tests/test_images")).glob("*.jpg"))
        return [p for p in images
                if p.name in {"obama.jpg", "obama2.jpg", "obama3.jpg",
                              "biden.jpg"}]
    except Exception as exc:
        print(f"(visages de test indisponibles : {exc})")
        return []


def photo(seed: int, size=(640, 480)) -> Image.Image:
    rng = random.Random(seed)
    im = Image.new("RGB", size,
                   (rng.randint(30, 220), rng.randint(30, 220), rng.randint(30, 220)))
    d = ImageDraw.Draw(im)
    for _ in range(25):
        x, y = rng.randint(0, size[0]), rng.randint(0, size[1])
        r = rng.randint(10, 90)
        d.ellipse([x, y, x + r, y + r],
                  fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    return im


def sidecar(path: Path, ts: int, lat=None, lon=None, name=None):
    data = {"title": name or path.name.replace(".json", ""),
            "photoTakenTime": {"timestamp": str(ts)},
            "geoData": {"latitude": lat or 0.0, "longitude": lon or 0.0}}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")
    d23 = root / "Takeout" / "Google Photos" / "Photos from 2023"
    d24 = root / "Takeout" / "Google Photos" / "Photos from 2024"
    for d in (d23, d24):
        d.mkdir(parents=True, exist_ok=True)

    rome = (41.9028, 12.4964)
    paris = (48.8566, 2.3522)

    # --- Événement A : Rome, juin 2023 ---
    t0 = 1686390000  # 2023-06-10 ~10h UTC
    base = photo(1)
    base.save(d23 / "IMG_2301.jpg", quality=90)
    sidecar(d23 / "IMG_2301.jpg.json", t0, *rome)

    # doublon exact de 2301
    base.save(d23 / "IMG_2304.jpg", quality=90)
    sidecar(d23 / "IMG_2304.jpg.json", t0 + 5, *rome)

    # rafale : 2302 et 2303 quasi identiques (JSON "supplemental-metadata")
    burst = photo(2)
    burst.save(d23 / "IMG_2302.jpg", quality=90)
    sidecar(d23 / "IMG_2302.jpg.supplemental-metadata.json", t0 + 60, *rome)
    ImageEnhance.Brightness(burst).enhance(1.06).save(d23 / "IMG_2303.jpg", quality=88)
    sidecar(d23 / "IMG_2303.jpg.json", t0 + 62, *rome)

    # original + version retouchée partageant le même JSON
    orig = photo(3)
    orig.save(d23 / "IMG_2308.jpg", quality=90)
    ImageEnhance.Contrast(orig).enhance(1.4).save(d23 / "IMG_2308-edited.jpg", quality=90)
    sidecar(d23 / "IMG_2308.jpg.json", t0 + 3600, *rome)

    # Live Photo séparée : photo + mini-vidéo du même nom
    photo(4).save(d23 / "IMG_2306.jpg", quality=90)
    (d23 / "IMG_2306.MP4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
    sidecar(d23 / "IMG_2306.jpg.json", t0 + 7200, *rome)

    # --- Screenshot (hors événement, le lendemain) ---
    shot = Image.new("RGB", (1080, 2400), (245, 245, 250))
    ImageDraw.Draw(shot).rectangle([0, 0, 1080, 120], fill=(60, 60, 70))
    shot.save(d23 / "Screenshot_20230611-101532.png")
    sidecar(d23 / "Screenshot_20230611-101532.png.json", t0 + 86400)

    # --- suffixe (1) : IMG_2307(1).jpg <-> IMG_2307.jpg(1).json ---
    photo(5).save(d23 / "IMG_2307(1).jpg", quality=90)
    sidecar(d23 / "IMG_2307.jpg(1).json", t0 + 90000, *rome)

    # --- nom long -> JSON tronqué à 46 caractères ---
    longname = "PXL_20230612_soiree_anniversaire_chez_marie_et_thomas.jpg"
    photo(6).save(d23 / longname, quality=90)
    sidecar(d23 / (longname[:46] + ".json"), t0 + 100000, *rome)

    # --- photo orpheline, sans JSON (test de repli) ---
    photo(7).save(d23 / "WhatsApp_Image_sans_json.jpg", quality=85)

    # --- Événement B : Paris, mars 2024 ---
    t1 = 1710500000
    for i, seed in enumerate((10, 11, 12)):
        name = f"IMG_24{i:02d}.jpg"
        photo(seed).save(d24 / name, quality=90)
        sidecar(d24 / (name + ".json"), t1 + i * 300, *paris)

    # --- Événement C : deux jours plus tard, sans GPS ---
    t2 = t1 + 2 * 86400
    for i, seed in enumerate((20, 21)):
        name = f"IMG_25{i:02d}.jpg"
        photo(seed).save(d24 / name, quality=90)
        sidecar(d24 / (name + ".json"), t2 + i * 600)

    # --- Portraits réels (2 personnes) pour le clustering de visages ---
    for i, src in enumerate(fetch_face_photos()):
        name = f"IMG_26{i:02d}_{src.stem}.jpg"
        shutil.copy(src, d24 / name)
        sidecar(d24 / (name + ".json"), t2 + 86400 + i * 300, *paris)

    n = sum(1 for _ in root.rglob("*") if _.is_file())
    print(f"Fixtures générées dans {root} ({n} fichiers)")


if __name__ == "__main__":
    main()
