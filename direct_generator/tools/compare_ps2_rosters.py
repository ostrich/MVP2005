#!/usr/bin/env python3
"""Compare two MVP 2005 PS2 roster saves by decoded identity and semantics.

This is intended for comparing a smaller GUI-created reference roster with a
directly generated full roster. Player IDs and physical slots are deliberately
ignored: uniquely named modern players are paired only when stable identity
anchors agree, then known player fields and team usage are compared.
"""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ps2_roster import Roster

# Initial exploratory field set shared by the two workflows. This includes some
# fields that need later attribution (notably top-prospect policy and unresolved
# generic animation mappings), so its subtotal must not be described as accuracy.
CANDIDATE_COMPARISON_FIELDS = {
    "attributes": {"birthday", "jerseynum", "primary_position", "secondary_position",
                   "bats", "throws", "bunting", "speed", "throwstrength", "throwaccuracy",
                   "fielding", "range", "durability", "platediscipline",
                   "stealing_aggressive", "baserunning", "starpower", "topprospect",
                   "battingstance"},
    "vs_lhp": {"contact", "power", "chasefb", "chaseslowbreak", "chasehardbreak",
               "takefb", "takeslowbreak", "takehardbreak", "missfb", "missslowbreak",
               "misshardbreak", "hit_ul", "hit_cl", "hit_ll", "hit_um", "hit_cm",
               "hit_lm", "hit_ur", "hit_cr", "hit_lr"},
    "vs_rhp": {"contact", "power", "chasefb", "chaseslowbreak", "chasehardbreak",
               "takefb", "takeslowbreak", "takehardbreak", "missfb", "missslowbreak",
               "misshardbreak", "hit_ul", "hit_cl", "hit_ll", "hit_um", "hit_cm",
               "hit_lm", "hit_ur", "hit_cr", "hit_lr"},
    "pitching": {"stamina", "pickoff", "fastball_control", "fastball_velocity",
                 "pitcher_delivery", "pitch2_type", "pitch2_movement", "pitch2_control",
                 "pitch2_velocity", "pitch3_type", "pitch3_movement", "pitch3_control",
                 "pitch3_velocity", "pitch4_type", "pitch4_movement", "pitch4_control",
                 "pitch4_velocity", "pitch5_type", "pitch5_movement", "pitch5_control",
                 "pitch5_velocity"},
}


def name_key(player):
    return player["first"].casefold(), player["last"].casefold()


def identity_anchor(player):
    attributes = player["attributes"]
    return tuple(attributes[field] for field in
                 ("birthday", "primary_position", "bats", "throws"))


def unique_by_name(players):
    grouped = defaultdict(list)
    for player in players:
        if player["first"] or player["last"]:
            grouped[name_key(player)].append(player)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}, {
        key: len(values) for key, values in grouped.items() if len(values) > 1
    }


def team_player_names(roster, unique_players):
    by_id = {player["id"]: name_key(player) for player in unique_players.values()}
    result = {}
    for team in roster.teams().records:
        result[team["unique_team"]] = {
            "record": team,
            "players": [by_id.get(player_id) for player_id in team["player_ids"]],
        }
    return result, by_id


def lineup_state(team, by_id, identity):
    record = team["record"]
    member_ids = record["player_ids"]
    states = {}
    for variant, lineup in record["lineups"].items():
        positions = []
        for position, slot in lineup["position_slots"].items():
            if slot < len(member_ids) and by_id.get(member_ids[slot]) == identity:
                positions.append(position)
        order = None
        for at, player_id in enumerate(lineup["batting_player_ids"], 1):
            if by_id.get(player_id) == identity:
                order = at
                break
        states[variant] = {"positions": sorted(positions), "batting_order": order}
    return states


def role_state(team, by_id, identity):
    record = team["record"]
    member_ids = record["player_ids"]
    roles = []
    for role, group in record["pitching_roles"].items():
        for slot in group["slots"]:
            if slot < len(member_ids) and by_id.get(member_ids[slot]) == identity:
                roles.append(role)
    return sorted(roles)


def compare(reference_path, generated_path, model_path, source_path=None):
    reference_data = reference_path.read_bytes()
    generated_data = generated_path.read_bytes()
    reference = Roster(reference_data)
    generated = Roster(generated_data)
    model = json.loads(model_path.read_text())

    reference_players, reference_ambiguous = unique_by_name(list(reference.players()))
    generated_players, generated_ambiguous = unique_by_name(list(generated.players()))
    modern_by_name = defaultdict(list)
    for player in model["players"].values():
        if not player["preserve_template"]:
            modern_by_name[name_key(player)].append(player)
    modern_names = Counter({name: len(players) for name, players in modern_by_name.items()})
    source_names = Counter()
    if source_path:
        with source_path.open(newline="", encoding="utf-8-sig") as handle:
            source_names.update((row["First"].casefold(), row["Last"].casefold())
                                for row in csv.DictReader(handle))
    unique_model_names = {name for name, count in modern_names.items() if count == 1}
    source_duplicate_rejections = sorted(
        name for name in unique_model_names & reference_players.keys() & generated_players.keys()
        if source_names and source_names[name] != 1)
    eligible = unique_model_names - set(source_duplicate_rejections)
    name_candidates = sorted(eligible & reference_players.keys() & generated_players.keys())
    rejected_anchors = []
    matched = []
    for name in name_candidates:
        expected = identity_anchor(modern_by_name[name][0])
        reference_anchor = identity_anchor(reference_players[name])
        generated_anchor = identity_anchor(generated_players[name])
        # A few one-to-three-day birthday and handedness discrepancies are
        # artifacts of the original UI entry. Reject only anchors that strongly
        # indicate a different same-name player.
        severe_conflict = (reference_anchor[1] != expected[1]
                           or abs(reference_anchor[0] - expected[0]) > 366)
        if generated_anchor == expected and not severe_conflict:
            matched.append(name)
        else:
            rejected_anchors.append({"player": list(name), "expected": list(expected),
                                     "reference": list(reference_anchor),
                                     "generated": list(generated_anchor)})

    field_results = {}
    total_field_comparisons = total_field_matches = 0
    source_field_comparisons = source_field_matches = 0
    for group in ("attributes", "vs_lhp", "vs_rhp", "pitching"):
        fields = sorted({field for identity in matched
                         for field in reference_players[identity].get(group, {})
                         if field in generated_players[identity].get(group, {})})
        group_result = {}
        for field in fields:
            compared = matches = 0
            examples = []
            for identity in matched:
                left = reference_players[identity].get(group, {})
                right = generated_players[identity].get(group, {})
                if field not in left or field not in right:
                    continue
                compared += 1
                if left[field] == right[field]:
                    matches += 1
                elif len(examples) < 5:
                    examples.append({"player": list(identity),
                                     "reference": left[field], "generated": right[field]})
            group_result[field] = {"compared": compared, "matches": matches,
                                   "differences": compared - matches,
                                   "difference_examples": examples}
            total_field_comparisons += compared
            total_field_matches += matches
            if field in CANDIDATE_COMPARISON_FIELDS[group]:
                source_field_comparisons += compared
                source_field_matches += matches
        field_results[group] = group_result

    reference_teams, reference_ids = team_player_names(reference, reference_players)
    generated_teams, generated_ids = team_player_names(generated, generated_players)
    common_teams = sorted(reference_teams.keys() & generated_teams.keys())
    membership_compared = membership_matches = 0
    lineup_compared = lineup_matches = 0
    roles_compared = roles_matches = 0
    examples = {"membership": [], "lineups": [], "pitching_roles": []}
    team_set_matches = 0
    for identity in matched:
        left_team_set = sorted(code for code in common_teams
                               if identity in reference_teams[code]["players"])
        right_team_set = sorted(code for code in common_teams
                                if identity in generated_teams[code]["players"])
        if left_team_set == right_team_set:
            team_set_matches += 1
        for code in common_teams:
            left_has = identity in reference_teams[code]["players"]
            right_has = identity in generated_teams[code]["players"]
            if not (left_has or right_has):
                continue
            membership_compared += 1
            if left_has == right_has:
                membership_matches += 1
            elif len(examples["membership"]) < 10:
                examples["membership"].append({"player": list(identity), "team": code,
                                                "reference": left_has, "generated": right_has})
            if not (left_has and right_has):
                continue
            left_lineup = lineup_state(reference_teams[code], reference_ids, identity)
            right_lineup = lineup_state(generated_teams[code], generated_ids, identity)
            for variant in left_lineup:
                if (left_lineup[variant] == {"positions": [], "batting_order": None}
                        and right_lineup[variant] == {"positions": [], "batting_order": None}):
                    continue
                lineup_compared += 1
                if left_lineup[variant] == right_lineup[variant]:
                    lineup_matches += 1
                elif len(examples["lineups"]) < 10:
                    examples["lineups"].append({"player": list(identity), "team": code,
                                                 "variant": variant,
                                                 "reference": left_lineup[variant],
                                                 "generated": right_lineup[variant]})
            left_roles = role_state(reference_teams[code], reference_ids, identity)
            right_roles = role_state(generated_teams[code], generated_ids, identity)
            if left_roles or right_roles:
                roles_compared += 1
                if left_roles == right_roles:
                    roles_matches += 1
                elif len(examples["pitching_roles"]) < 10:
                    examples["pitching_roles"].append({"player": list(identity), "team": code,
                                                        "reference": left_roles,
                                                        "generated": right_roles})

    differing_bytes = sum(a != b for a, b in zip(reference_data, generated_data))
    differing_bytes += abs(len(reference_data) - len(generated_data))
    return {
        "schema": "mvp-ps2-roster-comparison/v1",
        "scope": "Unique modern players matched by case-insensitive name plus birthday, primary position, bats and throws; IDs and physical slots ignored.",
        "reference": {"path": str(reference_path), "sha256": hashlib.sha256(reference_data).hexdigest(),
                      "bytes": len(reference_data), "checksums": "passed"},
        "generated": {"path": str(generated_path), "sha256": hashlib.sha256(generated_data).hexdigest(),
                      "bytes": len(generated_data), "checksums": "passed"},
        "raw": {"differing_bytes": differing_bytes, "identical": reference_data == generated_data,
                "interpretation": "Expected to differ because player selection, IDs, slots, retained templates, and packaging differ."},
        "identity": {"modern_players_in_model": sum(modern_names.values()),
                     "unique_modern_names_in_model": len(unique_model_names),
                     "unique_modern_names_eligible": len(eligible),
                     "source_names_required_unique": bool(source_names),
                     "source_duplicate_rejections": len(source_duplicate_rejections),
                     "source_duplicate_rejection_examples": [list(name) for name in source_duplicate_rejections[:20]],
                     "name_only_candidates": len(name_candidates),
                     "matched_modern_players": len(matched),
                     "identity_anchor_rejections": len(rejected_anchors),
                     "identity_anchor_rejection_examples": rejected_anchors[:20],
                     "reference_ambiguous_names": len(reference_ambiguous),
                     "generated_ambiguous_names": len(generated_ambiguous)},
        "known_player_fields": {"comparisons": total_field_comparisons,
                                "matches": total_field_matches,
                                "differences": total_field_comparisons - total_field_matches,
                                "by_group_and_field": field_results},
        "preliminary_selected_player_fields": {
            "scope": "Exploratory source-related field set; includes the internal top-prospect policy field, so this is not an accuracy rate.",
            "comparisons": source_field_comparisons,
            "matches": source_field_matches,
            "differences": source_field_comparisons - source_field_matches,
        },
        "teams": {"common_team_codes": len(common_teams),
                  "player_team_sets": {"comparisons": len(matched), "matches": team_set_matches,
                                       "differences": len(matched) - team_set_matches},
                  "membership": {"comparisons": membership_compared, "matches": membership_matches,
                                 "differences": membership_compared - membership_matches},
                  "lineup_states": {"comparisons": lineup_compared, "matches": lineup_matches,
                                    "differences": lineup_compared - lineup_matches},
                  "pitching_roles": {"comparisons": roles_compared, "matches": roles_matches,
                                     "differences": roles_compared - roles_matches},
                  "difference_examples": examples},
        "limitations": [
            "Same-name duplicates and players whose identity anchors disagree are excluded rather than guessed.",
            "Only decoded fields are compared; opaque template bits are not interpreted.",
            "Differences can reflect original UI-entry choices or later generator policy, not binary corruption.",
            "The supplied roster intentionally contains fewer modern players than the generated roster."
        ]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("generated", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source", type=Path,
                        help="Original CSV; excludes names duplicated anywhere in the source")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = compare(args.reference, args.generated, args.model, args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        fields = report["known_player_fields"]
        teams = report["teams"]
        print(f"{report['identity']['matched_modern_players']} modern players matched; "
              f"{fields['matches']}/{fields['comparisons']} known fields agree; "
              f"{teams['membership']['matches']}/{teams['membership']['comparisons']} memberships agree")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, f"Failed: {error}\n")


if __name__ == "__main__":
    main()
