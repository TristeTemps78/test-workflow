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

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

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
                              "biden.jpg", "obama_partial_face.jpg"}]
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

    # --- Screenshot avec du texte (extrait OCR affiché dans le rapport) ---
    from PIL import ImageFont
    shot = Image.new("RGB", (1080, 2400), (245, 245, 250))
    sdraw = ImageDraw.Draw(shot)
    sdraw.rectangle([0, 0, 1080, 120], fill=(60, 60, 70))
    try:
        sfont = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        sdraw.text((60, 300), "Paul : tu as vu le message du proprio ?",
                   fill=(30, 30, 30), font=sfont)
        sdraw.text((60, 380), "Moi : oui mdr il a repondu a la mauvaise",
                   fill=(30, 30, 30), font=sfont)
        sdraw.text((60, 460), "personne, je suis mort de rire",
                   fill=(30, 30, 30), font=sfont)
    except OSError:
        pass
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
    faces = {p.stem: p for p in fetch_face_photos()}
    for i, (stem, src) in enumerate(sorted(faces.items())):
        if stem == "obama_partial_face":
            continue  # réservé à la photo "reçue via WhatsApp" ci-dessous
        name = f"IMG_26{i:02d}_{stem}.jpg"
        shutil.copy(src, d24 / name)
        sidecar(d24 / (name + ".json"), t2 + 86400 + i * 300, *paris)

    # --- Reçue via WhatsApp (nom WA + personne connue dessus) ---
    if "obama_partial_face" in faces:
        shutil.copy(faces["obama_partial_face"], d24 / "IMG-20240320-WA0007.jpg")
        sidecar(d24 / "IMG-20240320-WA0007.jpg.json", t2 + 87000)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    # --- Document photographié : page blanche pleine de texte ---
    try:
        from PIL import ImageFont
        doc = Image.new("RGB", (900, 1100), (250, 250, 246))
        draw = ImageDraw.Draw(doc)
        font = ImageFont.truetype(font_path, 26)
        lines = ["ATTESTATION DE LOCATION", "",
                 "Je soussigné Jean Dupont, propriétaire du logement",
                 "situé 12 rue des Lilas, atteste que Monsieur Martin",
                 "occupe ce logement depuis le premier janvier deux",
                 "mille vingt-trois en qualité de locataire principal.",
                 "Le loyer mensuel est de sept cents euros charges",
                 "comprises, payable le cinq de chaque mois.",
                 "Fait pour servir et valoir ce que de droit.",
                 "Signature du propriétaire : Jean Dupont"]
        for i, line in enumerate(lines):
            draw.text((60, 60 + i * 48), line, fill=(20, 20, 20), font=font)
        doc.save(d24 / "IMG_2800_document.jpg", quality=92)
        sidecar(d24 / "IMG_2800_document.jpg.json", t2 + 88000)

        # --- Mème : photo + texte incrusté, pas de données d'appareil ---
        meme = photo(40, size=(800, 600))
        mdraw = ImageDraw.Draw(meme)
        mfont = ImageFont.truetype(font_path, 48)
        mdraw.text((40, 20), "QUAND LE CODE MARCHE", fill="white", font=mfont,
                   stroke_width=3, stroke_fill="black")
        mdraw.text((100, 520), "DU PREMIER COUP", fill="white", font=mfont,
                   stroke_width=3, stroke_fill="black")
        # nom neutre : teste la détection par contenu (texte incrusté sans
        # EXIF appareil), pas la détection par nom de fichier
        meme.save(d24 / "meme_chat_lundi.jpg", quality=88)
        sidecar(d24 / "meme_chat_lundi.jpg.json", t2 + 89000)
    except OSError:
        print("(police DejaVu absente : fixtures document/mème sautées)")

    # --- Dossier d'album Takeout : copie de IMG_2301 + quasi-doublon 2303 ---
    alb = root / "Takeout" / "Google Photos" / "Vacances Rome"
    alb.mkdir(parents=True, exist_ok=True)
    (alb / "metadata.json").write_text(
        json.dumps({"title": "Vacances Rome"}), encoding="utf-8")
    shutil.copy(d23 / "IMG_2301.jpg", alb / "IMG_2301.jpg")
    sidecar(alb / "IMG_2301.jpg.json", t0, *rome)
    shutil.copy(d23 / "IMG_2303.jpg", alb / "IMG_2303.jpg")
    sidecar(alb / "IMG_2303.jpg.json", t0 + 62, *rome)

    # --- Photos "ratées" : une floue, une très sombre ---
    photo(30).filter(ImageFilter.GaussianBlur(8)).save(
        d24 / "IMG_2700_floue.jpg", quality=90)
    sidecar(d24 / "IMG_2700_floue.jpg.json", t2 + 90000, *paris)
    ImageEnhance.Brightness(photo(31)).enhance(0.08).save(
        d24 / "IMG_2701_sombre.jpg", quality=90)
    sidecar(d24 / "IMG_2701_sombre.jpg.json", t2 + 90060, *paris)

    n = sum(1 for _ in root.rglob("*") if _.is_file())
    print(f"Fixtures générées dans {root} ({n} fichiers)")


if __name__ == "__main__":
    main()
