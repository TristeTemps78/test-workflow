"""Rapport HTML : ce que le pipeline propose, miniatures à l'appui.

Autonome (CSS inline, miniatures en base64) : lisible sur téléphone,
publiable en Artifact. C'est le point de contrôle humain du pipeline —
rien n'est exclu de l'export sans passer par ce rapport.
"""

import base64
import html
import io
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from pillow_heif import register_heif_opener

from .db import connect

register_heif_opener()

THUMB = 140

VIDEO_PLACEHOLDER = (
    "data:image/svg+xml;base64," + base64.b64encode(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="140" height="100">'
        b'<rect width="140" height="100" fill="#555"/>'
        b'<polygon points="55,30 55,70 95,50" fill="#eee"/></svg>'
    ).decode())

CSS = """
body { font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 70rem;
       background: #fff; color: #1a1a1a; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
table { border-collapse: collapse; margin: .5rem 0; }
td, th { border: 1px solid #ccc; padding: .3rem .7rem; text-align: left; }
.group { display: flex; flex-wrap: wrap; gap: .6rem; margin: .8rem 0;
         padding: .6rem; border: 1px solid #ddd; border-radius: 8px; }
figure { margin: 0; width: 150px; font-size: .72rem; }
figure img { max-width: 140px; border-radius: 4px; display: block; }
figcaption { word-break: break-all; margin-top: .2rem; }
.keep { outline: 3px solid #2e7d32; } .tag { font-weight: 600; }
.keep-tag { color: #2e7d32; } .drop-tag { color: #c62828; }
.muted { color: #666; }
.badge { background: #fff3cd; color: #7a5c00; border-radius: 4px;
         padding: 0 .3rem; font-weight: 600; }
#exportbar { position: sticky; bottom: 0; background: inherit;
             padding: .6rem 0; border-top: 1px solid #ccc; }
button { padding: .4rem .9rem; border-radius: 6px; border: 1px solid #888;
         cursor: pointer; }
@media (prefers-color-scheme: dark) {
  body { background: #16161a; color: #eee; }
  td, th { border-color: #444; } .group { border-color: #3a3a3a; }
}
"""


def _thumb(row) -> str:
    if row["kind"] != "image":
        return VIDEO_PLACEHOLDER
    try:
        with Image.open(row["path"]) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB, THUMB))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=60)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return VIDEO_PLACEHOLDER


def _figure(row, keeper: bool) -> str:
    tag = ('<span class="tag keep-tag">GARDÉE</span>' if keeper
           else '<span class="tag drop-tag">' +
                ("SUPPRIMER" if row["decision"] == "drop" else "À VALIDER") +
                "</span>")
    date = datetime.fromtimestamp(row["taken_ts"], tz=timezone.utc).strftime("%d/%m/%Y")
    extras = []
    if row["albums"]:
        extras.append(f'<span class="badge">📁 {html.escape(row["albums"])}</span>')
    if row["reason"]:
        extras.append(f'<span class="muted">{html.escape(row["reason"])}</span>')
    checkbox = ""
    if row["decision"] == "review":
        checkbox = (f'<label><input type="checkbox" class="decision" checked '
                    f'data-path="{html.escape(row["path"], quote=True)}"> '
                    f"supprimer</label>")
    return (f'<figure><img class="{"keep" if keeper else ""}" src="{_thumb(row)}">'
            f"<figcaption>{tag} {html.escape(row['filename'])}"
            f'<br><span class="muted">{date} · {row["size"] // 1024} Ko</span>'
            f"{'<br>' + '<br>'.join(extras) if extras else ''}"
            f"{'<br>' + checkbox if checkbox else ''}"
            f"</figcaption></figure>")


def _groups_section(con, column: str, title: str, blurb: str) -> str:
    parts = [f"<h2>{title}</h2><p class='muted'>{blurb}</p>"]
    ids = [r[0] for r in con.execute(
        f"SELECT DISTINCT {column} FROM media WHERE {column} IS NOT NULL")]
    if not ids:
        parts.append("<p>Aucun.</p>")
    for gid in ids:
        rows = con.execute(f"SELECT * FROM media WHERE {column} = ?", (gid,)).fetchall()
        figs = "".join(_figure(r, r["decision"] == "keep") for r in rows)
        parts.append(f'<div class="group">{figs}</div>')
    return "\n".join(parts)


def _face_crop(row) -> str | None:
    try:
        with Image.open(row["path"]) as im:
            im = im.convert("RGB")
            pad = (row["bottom"] - row["top"]) // 3
            box = (max(row["left"] - pad, 0), max(row["top"] - pad, 0),
                   min(row["right"] + pad, im.width),
                   min(row["bottom"] + pad, im.height))
            crop = im.crop(box)
            crop.thumbnail((100, 100))
            buf = io.BytesIO()
            crop.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _people_section(con) -> str:
    try:
        clusters = con.execute(
            """SELECT cluster, COUNT(DISTINCT path) photos FROM faces
               WHERE cluster IS NOT NULL GROUP BY cluster
               ORDER BY photos DESC""").fetchall()
    except Exception:  # étape faces jamais exécutée
        return ""
    parts = [f"<h2>Personnes détectées ({len(clusters)})</h2>",
             "<p class='muted'>Visages regroupés automatiquement (analyse "
             "100 % locale). Pour nommer : créer out/people_names.json, "
             'ex. {"person-01": "Maman"}, puis relancer avec --people.</p>']
    if not clusters:
        parts.append("<p>Aucune (étape `faces` non exécutée ou aucun visage "
                     "récurrent).</p>")
    for c in clusters:
        rows = con.execute(
            """SELECT f.*, m.filename FROM faces f
               JOIN media m ON m.path = f.path
               WHERE f.cluster = ? LIMIT 8""", (c["cluster"],)).fetchall()
        figs = []
        for r in rows:
            src = _face_crop(r)
            if src:
                figs.append(f'<figure><img src="{src}">'
                            f"<figcaption class='muted'>"
                            f"{html.escape(r['filename'])}</figcaption></figure>")
        parts.append(
            f'<div class="group"><figure><figcaption class="tag">'
            f'{html.escape(c["cluster"])}<br>{c["photos"]} photo(s)'
            f"</figcaption></figure>{''.join(figs)}</div>")
    return "\n".join(parts)


def _flat_section(con, category: str, title: str, blurb: str) -> str:
    rows = con.execute("SELECT * FROM media WHERE category = ?", (category,)).fetchall()
    parts = [f"<h2>{title} ({len(rows)})</h2><p class='muted'>{blurb}</p>"]
    if rows:
        figs = "".join(_figure(r, r["decision"] == "keep") for r in rows)
        parts.append(f'<div class="group">{figs}</div>')
    else:
        parts.append("<p>Aucun.</p>")
    return "\n".join(parts)


def run(out_dir) -> dict:
    con = connect(out_dir)
    stats = {row["decision"]: row["c"] for row in con.execute(
        "SELECT decision, COUNT(*) c FROM media GROUP BY decision")}
    total = sum(stats.values())

    events = con.execute(
        """SELECT event, COUNT(*) c, MIN(taken_ts) start FROM media
           WHERE decision = 'keep' AND event IS NOT NULL
           GROUP BY event ORDER BY start""").fetchall()
    event_rows = "".join(
        f"<tr><td>{html.escape(e['event'])}</td><td>{e['c']}</td></tr>"
        for e in events)

    body = f"""<title>Rapport de tri photos</title>
<style>{CSS}</style>
<h1>Rapport de tri — export Google Photos</h1>
<table>
<tr><th>Total analysé</th><td>{total}</td></tr>
<tr><th>À garder</th><td>{stats.get('keep', 0)}</td></tr>
<tr><th>Doublons exacts (suppression sûre)</th><td>{stats.get('drop', 0)}</td></tr>
<tr><th>À valider par toi</th><td>{stats.get('review', 0)}</td></tr>
</table>
{_groups_section(con, "dup_group", "Doublons exacts",
                 "Contenu identique octet par octet. La meilleure copie est gardée (cadre vert).")}
{_groups_section(con, "near_group", "Quasi-doublons (rafales, retouches)",
                 "Images visuellement quasi identiques prises le même jour. À toi de confirmer.")}
{_flat_section(con, "screenshot", "Captures d'écran",
               "Suppression suggérée — vérifie qu'aucune ne contient d'info à garder.")}
{_flat_section(con, "live_companion", "Mini-vidéos de Live Photos",
               "Takeout sépare les Live Photos en photo + vidéo de 2 s. "
               "La photo est conservée ; ces vidéos pollueraient la galerie.")}
{_flat_section(con, "low_quality", "Photos probablement ratées (flou, exposition)",
               "Détection purement technique — une photo d'ambiance floue peut "
               "valoir de l'or : décoche celles qui ont leur charme. Les photos "
               "appartenant à un album sont automatiquement protégées.")}
{_people_section(con)}
<h2>Événements proposés ({len(events)})</h2>
<p class="muted">Un événement = un dossier dans l'export propre (= un album si ré-upload par API).</p>
<table><tr><th>Événement</th><th>Photos</th></tr>{event_rows}</table>
<div id="exportbar">
<button onclick="exportDecisions()">Exporter mes choix (decisions.json)</button>
<button onclick="copyDecisions()">Copier dans le presse-papier</button>
<span id="status" class="muted"></span>
</div>
<script>
function collect() {{
  const d = {{}};
  document.querySelectorAll("input.decision").forEach(cb => {{
    d[cb.dataset.path] = cb.checked ? "drop" : "keep";
  }});
  return JSON.stringify(d, null, 1);
}}
function exportDecisions() {{
  const blob = new Blob([collect()], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "decisions.json";
  a.click();
}}
function copyDecisions() {{
  navigator.clipboard.writeText(collect()).then(() =>
    document.getElementById("status").textContent = " copié !");
}}
</script>
"""
    out = Path(out_dir) / "report.html"
    out.write_text(body, encoding="utf-8")
    con.close()
    return {"rapport": str(out), "total": total,
            "keep": stats.get("keep", 0), "drop": stats.get("drop", 0),
            "review": stats.get("review", 0)}
