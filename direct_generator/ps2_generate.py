#!/usr/bin/env python3
"""Build MVP 2005 PS2 rosters in separable normalize / encode / package stages."""

import argparse
import re
import json
from mvp_ps2.layout import Layout
from mvp_ps2.plan import make_plan
from pathlib import Path
from mvp_ps2 import model
from mvp_ps2.pipeline import (
    build,
    encode_stage,
    package_stage,
    new_directory,
    write_new,
    json_bytes,
)
from mvp_ps2.verify import verify
from mvp_ps2.references import check_references
from tools.ps2_image import database_input


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("normalize", "build"):
        q = sub.add_parser(command)
        q.add_argument("--source", type=Path, required=True)
        inputs = q.add_mutually_exclusive_group(required=True)
        inputs.add_argument(
            "--baseline",
            type=Path,
            help="Extracted stock PS2 DAT directory",
        )
        inputs.add_argument("--ps2-image", type=Path, help="MVP Baseball 2005 (USA) plain ISO")
        q.add_argument("--source-year", type=int)
        q.add_argument("--output", type=Path, required=True)
        if command == "build":
            q.add_argument("--template-card", type=Path, required=True)
            q.add_argument("--member")
            q.add_argument("--save-name")
            q.add_argument(
                "--reference-cards",
                type=Path,
                help="Optional directory of reference PS2 cards to check",
            )
    q = sub.add_parser("plan")
    q.add_argument("--model", type=Path, required=True)
    q.add_argument("--template-save", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    q = sub.add_parser("encode")
    q.add_argument("--plan", type=Path)
    q.add_argument("--model", type=Path, required=True)
    q.add_argument("--template-save", type=Path, required=True)
    q.add_argument("--save-name", required=True)
    q.add_argument("--output", type=Path, required=True)
    q = sub.add_parser("package")
    q.add_argument("--model", type=Path, required=True)
    q.add_argument("--template-card", type=Path, required=True)
    q.add_argument("--save", type=Path, required=True)
    q.add_argument("--member")
    q.add_argument("--output", type=Path, required=True)
    q = sub.add_parser("verify")
    q.add_argument("--model", type=Path, required=True)
    q.add_argument("--template-save", type=Path, required=True)
    q.add_argument("--save", type=Path, required=True)
    q.add_argument("--icon-sys", type=Path)
    q.add_argument("--output", type=Path, required=True)
    q = sub.add_parser("check-references")
    q.add_argument("--cards", type=Path, required=True)
    q.add_argument("--baseline", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command in ("normalize", "build"):
            with database_input(a.baseline, a.ps2_image) as baseline:
                date = re.search(r"(\d{4})-(\d{2})-(\d{2})", a.source.name)
                year = a.source_year or (int(date[1]) if date else None)
                if year is None:
                    p.error("Use --source-year when the CSV filename has no date")
                if a.command == "normalize":
                    write_new(
                        a.output, json_bytes(model.normalize(a.source, baseline, year))
                    )
                else:
                    name = a.save_name or ("".join(date.groups()) if date else None)
                    if name is None:
                        p.error("Use --save-name when the CSV filename has no date")
                    if not re.fullmatch(r"[A-Za-z0-9]{1,15}", name):
                        p.error("Save name must be 1–15 ASCII letters/digits")
                    report = build(
                        a.source,
                        baseline,
                        a.template_card,
                        a.output,
                        year,
                        name,
                        a.member,
                        a.reference_cards,
                    )
                    print(
                        f"Built {report['modern_players']} modern players; {report['checks_passed']} checks passed."
                    )
        elif a.command == "plan":
            write_new(
                a.output,
                json_bytes(
                    make_plan(model.load(a.model), Layout(a.template_save.read_bytes()))
                ),
            )
        elif a.command == "encode":
            with new_directory(a.output) as out:
                encode_stage(
                    model.load(a.model),
                    a.template_save.read_bytes(),
                    a.save_name,
                    out,
                    json.loads(a.plan.read_text()) if a.plan else None,
                )
        elif a.command == "package":
            with new_directory(a.output) as out:
                package_stage(
                    model.load(a.model),
                    a.template_card.read_bytes(),
                    a.save.read_bytes(),
                    a.member,
                    out,
                )
        elif a.command == "verify":
            report = verify(
                model.load(a.model),
                a.save.read_bytes(),
                a.template_save.read_bytes(),
                a.icon_sys.read_bytes() if a.icon_sys else None,
            )
            write_new(a.output, json_bytes(report))
        else:
            write_new(a.output, json_bytes(check_references(a.cards, a.baseline)))
        print(a.output)
    except (OSError, ValueError, KeyError, TypeError) as e:
        p.exit(1, f"Failed: {e}\n")


if __name__ == "__main__":
    main()
