"""Doublons : exacts (SHA-256) puis quasi-doublons (hash perceptuel).

- Doublon exact : contenu identique octet par octet -> proposition `drop`.
- Quasi-doublon : rafales, retouches légères, recompressions. Détecté par
  distance de Hamming entre hashes perceptuels, uniquement entre photos
  prises le même jour (évite les faux positifs entre années différentes).
  -> proposition `review` : c'est toi qui choisis dans le rapport.

Dans chaque groupe on garde la meilleure copie : plus grande résolution,
puis plus gros fichier, et jamais une version "-edited" si l'original est là.
"""

from datetime import datetime, timezone

import imagehash

from .db import connect

NEAR_DISTANCE = 5  # distance de Hamming max pour un quasi-doublon


def _quality_key(row) -> tuple:
    edited = "-edited" in row["filename"].lower()
    pixels = (row["width"] or 0) * (row["height"] or 0)
    return (not edited, pixels, row["size"])


def run(out_dir) -> dict:
    con = connect(out_dir)

    # --- doublons exacts ---
    exact_groups = 0
    dropped = 0
    dupes = con.execute(
        """SELECT sha256 FROM media WHERE decision = 'keep'
           GROUP BY sha256 HAVING COUNT(*) > 1"""
    ).fetchall()
    for g, row in enumerate(dupes, start=1):
        members = con.execute(
            "SELECT * FROM media WHERE sha256 = ? AND decision = 'keep'",
            (row["sha256"],)).fetchall()
        keeper = max(members, key=_quality_key)
        for m in members:
            con.execute("UPDATE media SET dup_group = ? WHERE path = ?",
                        (g, m["path"]))
            if m["path"] != keeper["path"]:
                con.execute(
                    """UPDATE media SET decision = 'drop',
                       reason = ? WHERE path = ?""",
                    (f"doublon exact de {keeper['filename']}", m["path"]))
                dropped += 1
        exact_groups += 1

    # --- quasi-doublons, par journée ---
    rows = con.execute(
        """SELECT path, filename, phash, taken_ts, width, height, size
           FROM media WHERE decision = 'keep' AND phash IS NOT NULL
           ORDER BY taken_ts"""
    ).fetchall()
    by_day: dict[str, list] = {}
    for r in rows:
        day = datetime.fromtimestamp(r["taken_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(r)

    near_groups = 0
    flagged = 0
    group_id = 0
    for members in by_day.values():
        hashes = {m["path"]: imagehash.hex_to_hash(m["phash"]) for m in members}
        parent = {m["path"]: m["path"] for m in members}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if hashes[a["path"]] - hashes[b["path"]] <= NEAR_DISTANCE:
                    parent[find(a["path"])] = find(b["path"])

        clusters: dict[str, list] = {}
        for m in members:
            clusters.setdefault(find(m["path"]), []).append(m)
        for cluster in clusters.values():
            if len(cluster) < 2:
                continue
            group_id += 1
            near_groups += 1
            keeper = max(cluster, key=_quality_key)
            for m in cluster:
                con.execute("UPDATE media SET near_group = ? WHERE path = ?",
                            (group_id, m["path"]))
                if m["path"] != keeper["path"]:
                    con.execute(
                        """UPDATE media SET decision = 'review',
                           reason = ? WHERE path = ?""",
                        (f"quasi-doublon de {keeper['filename']} (rafale/retouche)",
                         m["path"]))
                    flagged += 1

    con.commit()
    con.close()
    return {"groupes_exacts": exact_groups, "drop_exacts": dropped,
            "groupes_proches": near_groups, "à_valider": flagged}
