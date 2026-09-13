"""Stage 1: CSV and stock DATs -> platform-neutral logical roster JSON.

Uses the same selection, ratings and lineup policy as the PC converter. This
module knows no save offsets, checksums, memory-card pages or physical slots.
"""

from pathlib import Path
import hashlib
import json
from mvp_rosters import build_database, identity, player_id
from ps2_roster import ATTR, BATTING, PITCHING

SCHEMA = "mvp-ps2-model/v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def packed_values(row, prefix, fields):
    values = {}
    for key, value in row.items():
        if not key.startswith(prefix):
            continue
        name = key[len(prefix) :]
        if name not in fields:
            raise ValueError(f"Unmapped source field: {key}")
        values[name] = 0 if value == "-" else int(value)
    return values


def normalize(source, baseline, year, prepared=None):
    tables, report, assignments, selected, keep = build_database(source, baseline, year, prepared)
    modern = {player_id(r) for r in selected}
    players = {}
    name_changes = []
    for key, row in tables["attrib"].rows.items():
        rid = f"{int(key, 16):08x}"
        if key not in modern:
            players[rid] = {"preserve_template": True}
            continue
        names = {}
        for source_name, dest, limit in (
            ("first_name", "first", 11),
            ("last_name", "last", 15),
        ):
            original = row[source_name]
            raw = original.encode("cp1252")
            if b"\0" in raw:
                raise ValueError("NUL in player name")
            names[dest] = raw[:limit].decode("cp1252")
            if len(raw) > limit:
                name_changes.append(
                    {
                        "id": rid,
                        "field": dest,
                        "source": original,
                        "encoded": names[dest],
                    }
                )
        values = packed_values(row, "playerattrib_", ATTR)
        values.update(
            personality=0,
            offercount=0,
            playedtoday=0,
            energylevel=100,
            injurytype=0,
            injuryduration=0,
            tooinjured=0,
            promisedrole=0,
            contractvalueadj=0,
            contractyearadj=0,
            contractroleadj=0,
        )
        player = {
            "preserve_template": False,
            **names,
            "attributes": values,
            "vs_lhp": packed_values(tables["lhattrib"].rows[key], "lrattrib_", BATTING),
            "vs_rhp": packed_values(tables["rhattrib"].rows[key], "lrattrib_", BATTING),
        }
        if key in tables["pitcher"].rows:
            player["pitching"] = packed_values(
                tables["pitcher"].rows[key], "pitchattrib_", PITCHING
            )
            player["pitching"]["current_stamina_nl"] = player["pitching"]["stamina"]
        players[rid] = player
    teams = {}
    for key, row in tables["team"].rows.items():
        teams[f"{int(key, 16):08x}"] = {"code": row["unique_team"], "players": []}
    for row in tables["roster"].rows.values():
        entry = {"id": f"{int(row['roster_playerid'], 16):08x}", "lineups": {}}
        for variant in ("rh_al", "rh_nl", "lh_al", "lh_nl"):
            side, rules = variant.split("_")
            prefix = f"{side}_roster_{rules}_"
            entry["lineups"][variant] = {
                "position": row[prefix + "position"],
                "order": int(row[prefix + "battingorder"]),
            }
        teams[f"{int(row['roster_teamid'], 16):08x}"]["players"].append(entry)
    report["name_truncations"] = name_changes
    result = {
        "schema": SCHEMA,
        "source_year": year,
        "report": report,
        "players": players,
        "teams": teams,
        "identity_map": {identity(r): f"{int(player_id(r), 16):08x}" for r in selected},
        "policies": {
            "modern_stats": "zero all current, previous, minor and career arrays",
            "retained_players": "preserve template records",
            "unused_slots": "hide and reset to default, omit from active rosters",
            "unknown_bits": "preserve Default record bits for modern players",
            "appearance": "generic faces; generic animation variants use reported fallbacks",
        },
    }
    validate_model(result)
    return result


def validate_model(model):
    from ps2_teams import VARIANTS, ROLE_CAPACITIES

    if model.get("schema") != SCHEMA:
        raise ValueError("Unsupported model schema")
    players = model["players"]
    teams = model["teams"]
    modern = {k for k, p in players.items() if not p["preserve_template"]}
    if len(modern) != 3000 or len(players) > 3250 or len(teams) != 126:
        raise ValueError("Unsupported player/team population")
    if (
        len(model["identity_map"]) != 3000
        or set(model["identity_map"].values()) != modern
    ):
        raise ValueError("Identity map does not cover modern players uniquely")
    for key in (*players, *teams):
        if len(key) != 8 or f"{int(key, 16):08x}" != key:
            raise ValueError("Noncanonical ID")
    if "f58f3c1b" not in players or not players["f58f3c1b"]["preserve_template"]:
        raise ValueError("Default player must be preserved")
    from collections import Counter

    appearances = Counter()
    for tid, team in teams.items():
        entries = team["players"]
        ids = [p["id"] for p in entries]
        if len(ids) != 25 or len(set(ids)) != 25 or set(ids) - players.keys():
            raise ValueError(f"{tid}: invalid team membership")
        if team["code"] not in ("AL", "NL"):
            appearances.update(k for k in ids if k in modern)
        for variant in VARIANTS:
            lineup = [p["lineups"][variant] for p in entries]
            roles = Counter(p["position"] for p in lineup)
            if any(
                roles[p] != 1
                for p in (
                    "C",
                    "1B",
                    "2B",
                    "3B",
                    "SS",
                    "LF",
                    "CF",
                    "RF",
                    *(f"SP{i}" for i in range(1, 6)),
                    "CP",
                )
            ):
                raise ValueError(f"{tid}: incomplete lineup")
            if roles["DH"] != (1 if variant.endswith("al") else 0):
                raise ValueError("Invalid DH assignment")
            if any(roles[k] > cap for k, cap in ROLE_CAPACITIES.items() if k != "SP"):
                raise ValueError("Bullpen exceeds capacity")
            if sorted(p["order"] for p in lineup if p["order"] != -1) != list(
                range(1, 10)
            ):
                raise ValueError("Invalid batting order")
            if any(
                p["position"]
                not in (
                    "B",
                    "DH",
                    "C",
                    "1B",
                    "2B",
                    "3B",
                    "SS",
                    "LF",
                    "CF",
                    "RF",
                    "LR",
                    "MR",
                    "SU",
                    "CP",
                    *(f"SP{i}" for i in range(1, 6)),
                )
                for p in lineup
            ):
                raise ValueError("Unknown roster position")
        for entry in entries:
            role = entry["lineups"]["rh_al"]["position"]
            if role in (
                "LR",
                "MR",
                "SU",
                "CP",
                "SP1",
                "SP2",
                "SP3",
                "SP4",
                "SP5",
            ) and any(entry["lineups"][v]["position"] != role for v in VARIANTS):
                raise ValueError("Pitching roles must agree across all lineups")
            p = players[entry["id"]]
            if (
                role in ("LR", "MR", "SU", "CP", "SP1", "SP2", "SP3", "SP4", "SP5")
                and not p["preserve_template"]
                and "pitching" not in p
            ):
                raise ValueError("Pitching role assigned to a nonpitcher")
    if set(appearances) != modern or any(n != 1 for n in appearances.values()):
        raise ValueError("Modern player missing or duplicated outside All-Stars")
    for player in players.values():
        if player["preserve_template"]:
            continue
        for name, limit in (("first", 11), ("last", 15)):
            raw = player[name].encode("cp1252")
            if not raw or len(raw) > limit or b"\0" in raw:
                raise ValueError("Invalid encoded name")
        for group, fields in (
            ("attributes", ATTR),
            ("vs_lhp", BATTING),
            ("vs_rhp", BATTING),
            ("pitching", PITCHING),
        ):
            if group not in player:
                if group == "pitching":
                    continue
                raise ValueError(f"Missing {group}")
            if set(player[group]) != set(fields):
                raise ValueError(f"Incomplete {group} field set")
            for field, value in player[group].items():
                if field not in fields:
                    raise ValueError(f"Unknown field: {group}.{field}")
                if type(value) is not int or not 0 <= value < 1 << fields[field][1]:
                    raise ValueError(f"Invalid field value: {group}.{field}={value}")
    return model


def load(path):
    return validate_model(json.loads(Path(path).read_text()))
