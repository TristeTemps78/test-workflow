#!/usr/bin/env python3
"""Orchestrateur du pipeline de tri Google Photos.

Usage :
    python3 run_pipeline.py --source <dossier Takeout extrait> [--out out]
    python3 run_pipeline.py --source ... --steps inventory,dedupe
    python3 run_pipeline.py --source ... --export   # après validation du rapport

Étapes (dans l'ordre) : inventory, dedupe, classify, report.
L'export (arborescence propre + EXIF corrigé) ne se lance qu'explicitement,
une fois le rapport validé.
"""

import argparse
import json

from triage import classify, dedupe, export, inventory, report


def _faces(a):
    from triage import faces  # import paresseux : dlib est lourd
    return faces.run(a.out)


STEPS = {
    "inventory": lambda a: inventory.run(a.source, a.out),
    "dedupe": lambda a: dedupe.run(a.out),
    "classify": lambda a: classify.run(a.out),
    "faces": _faces,
    "report": lambda a: report.run(a.out),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help="dossier de l'export Takeout extrait")
    parser.add_argument("--out", default="out",
                        help="dossier de travail (manifeste, rapport, export)")
    parser.add_argument("--steps",
                        default="inventory,dedupe,classify,faces,report",
                        help="étapes à exécuter, séparées par des virgules")
    parser.add_argument("--export", action="store_true",
                        help="construit out/cleaned/ avec EXIF corrigé")
    parser.add_argument("--people", action="store_true",
                        help="construit out/albums_people/ (albums par personne)")
    args = parser.parse_args()

    for step in args.steps.split(","):
        step = step.strip()
        if step not in STEPS:
            parser.error(f"étape inconnue : {step}")
        print(f"--- {step}")
        print(json.dumps(STEPS[step](args), ensure_ascii=False, indent=2))

    if args.export:
        print("--- export")
        print(json.dumps(export.run(args.out), ensure_ascii=False, indent=2))

    if args.people:
        from triage import faces
        print("--- albums par personne")
        print(json.dumps(faces.export_albums(args.out),
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
