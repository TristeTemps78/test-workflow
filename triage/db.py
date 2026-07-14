"""Manifeste SQLite : la mémoire persistante du pipeline.

Chaque fichier média de l'export Takeout a une ligne ici. Toutes les étapes
(inventaire, doublons, classification, export) lisent et écrivent ce manifeste,
ce qui rend le pipeline interruptible et reprenable — indispensable quand on
traite des milliers de photos sur plusieurs sessions.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    path        TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    dirname     TEXT NOT NULL,
    ext         TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- image | video | other
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    sha256      TEXT,
    phash       TEXT,
    width       INTEGER,
    height      INTEGER,
    exif_dt     TEXT,                     -- date EXIF d'origine si présente
    camera      TEXT,
    duration    REAL,                     -- vidéos uniquement (secondes)
    sharpness   REAL,                     -- variance du laplacien (flou si bas)
    brightness  REAL,                     -- luminosité moyenne 0-255
    source_album TEXT,                    -- dossier d'album Takeout d'origine
    albums      TEXT,                     -- appartenance aux albums (séparateur |)
    json_path   TEXT,                     -- sidecar Takeout apparié
    json_ts     INTEGER,                  -- photoTakenTime.timestamp
    gps_lat     REAL,
    gps_lon     REAL,
    description TEXT,
    taken_ts    INTEGER,                  -- meilleure date connue (epoch)
    category    TEXT DEFAULT 'photo',     -- photo | screenshot | live_companion | video
    dup_group   INTEGER,
    near_group  INTEGER,
    event       TEXT,
    decision    TEXT DEFAULT 'keep',      -- keep | drop | review
    reason      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sha ON media (sha256);
CREATE INDEX IF NOT EXISTS idx_decision ON media (decision);
"""


# Colonnes ajoutées après coup : migration douce des manifestes existants.
MIGRATIONS = [
    "ALTER TABLE media ADD COLUMN sharpness REAL",
    "ALTER TABLE media ADD COLUMN brightness REAL",
    "ALTER TABLE media ADD COLUMN source_album TEXT",
    "ALTER TABLE media ADD COLUMN albums TEXT",
]


def connect(out_dir: str | Path) -> sqlite3.Connection:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out / "manifest.db")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for migration in MIGRATIONS:
        try:
            con.execute(migration)
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    return con
