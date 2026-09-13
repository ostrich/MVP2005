#!/usr/bin/env python3
"""Audit shared animation enums against original DATs and a UI-created save."""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mvp_rosters import DELIVERIES, STANCES, Table
from ps2_roster import Roster


def unique_by_name(rows, first, last):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row[first].casefold(), row[last].casefold())].append(row)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def observations(source, reference):
    with source.open(newline="", encoding="utf-8-sig") as handle:
        source_players = unique_by_name(list(csv.DictReader(handle)), "First", "Last")
    save_players = unique_by_name(list(Roster(reference.read_bytes()).players()), "first", "last")
    stances, deliveries = defaultdict(Counter), defaultdict(Counter)
    for name in source_players.keys() & save_players.keys():
        src, saved = source_players[name], save_players[name]
        stances[src["Batter Stance"]][saved["attributes"]["battingstance"]] += 1
        if "pitching" in saved and src["Pitcher Delivery"] != "NA":
            deliveries[src["Pitcher Delivery"]][saved["pitching"]["pitcher_delivery"]] += 1
    return stances, deliveries


def summarize(mapping, counts):
    result = {}
    failures = []
    for label, code in mapping.items():
        observed = counts.get(label, Counter())
        modal = observed.most_common(1)[0] if observed else None
        result[label] = {"mapped_code": code, "observations": dict(sorted(observed.items())),
                         "modal": list(modal) if modal else None}
        if modal and modal[0] != code:
            failures.append({"label": label, "mapped": code, "observed_modal": modal[0],
                             "modal_count": modal[1]})
    return result, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    pc = parser.add_mutually_exclusive_group(required=True)
    pc.add_argument("--pc-attrib", type=Path)
    pc.add_argument("--pc-install-zip", type=Path,
                    help="Original PC compressed.zip containing data\\database\\attrib.dat")
    parser.add_argument("--ps2-attrib", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference-save", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.pc_attrib:
        pc_raw = args.pc_attrib.read_bytes()
    else:
        with ZipFile(args.pc_install_zip) as archive:
            pc_raw = archive.read("data\\database\\attrib.dat")
    ps2_raw = args.ps2_attrib.read_bytes()
    if pc_raw != ps2_raw:
        parser.exit(1, "Original PC and PS2 attrib.dat files differ\n")
    stock = Table.read(args.ps2_attrib)
    larry = [row for row in stock.rows.values()
             if (row["first_name"], row["last_name"]) == ("Larry", "Walker")]
    if len(larry) != 1 or int(larry[0]["playerattrib_battingstance"]) != STANCES["Walker"]:
        parser.exit(1, "Walker mapping disagrees with Larry Walker's stock record\n")

    stance_counts, delivery_counts = observations(args.source, args.reference_save)
    stance_report, stance_failures = summarize(STANCES, stance_counts)
    delivery_report, delivery_failures = summarize(DELIVERIES, delivery_counts)
    report = {
        "schema": "mvp-animation-mapping-audit/v1",
        "original_dat": {"pc_ps2_identical": True,
                         "sha256": hashlib.sha256(pc_raw).hexdigest()},
        "stock_checks": {"Walker": {"player": "Larry Walker", "code": 31,
                                      "status": "passed"}},
        "stances": stance_report,
        "deliveries": delivery_report,
        "failures": stance_failures + delivery_failures,
        "unresolved_source_labels": {
            "stances": ["Generic 3", "Bent", "Closed", "Open"],
            "deliveries": [],
        },
        "interpretation": "Modal UI-save observations corroborate mappings but isolated deviations are retained as original-entry noise.",
    }
    if report["failures"]:
        parser.exit(1, json.dumps(report["failures"], indent=2) + "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Animation audit passed; {len(STANCES)} stances and {len(DELIVERIES)} deliveries mapped")


if __name__ == "__main__":
    main()
