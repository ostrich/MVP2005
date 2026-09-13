"""Stage 4: independently decode and compare a save with its logical input.

Does not call the writer or derive expected values by re-encoding. Full byte
preservation is additionally checked for retained players and opaque sections.
"""

from collections import Counter
import struct
from ps2_roster import ea_crc
from ps2_teams import VARIANTS, POSITIONS, ROLE_CAPACITIES
from .layout import Layout
from .model import validate_model, sha


def verify(model, data, template, icon_sys=None):
    validate_model(model)
    current = Layout(data)
    original = Layout(template)
    roster = current.roster
    source = original.roster
    actual = {p["id"]: p for p in roster.players()}
    modern = {k for k, p in model["players"].items() if not p["preserve_template"]}
    checks = 0

    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise ValueError(f"Verification failed: {message}")

    require(len(actual) == 3250, "player registry capacity")
    require(set(model["players"]) <= actual.keys(), "logical player IDs absent")
    expected_pitchers = {
        k
        for k, p in model["players"].items()
        if "pitching" in p
        or (p["preserve_template"] and int(k, 16) in source.pitch_index)
    }
    require(
        {f"{k:08x}" for k in roster.pitch_index} == expected_pitchers,
        "pitcher registry membership",
    )
    for key, expected in model["players"].items():
        decoded = actual[key]
        slot = roster.index[int(key, 16)]
        if expected["preserve_template"]:
            old = source.index[int(key, 16)]
            for before, after in zip(original.player_arrays, current.player_arrays):
                require(
                    before.record(template, old) == after.record(data, slot),
                    f"{key} retained {before.label}",
                )
            if int(key, 16) in source.pitch_index:
                for before, after in zip(original.pitch_arrays, current.pitch_arrays):
                    require(
                        before.record(template, source.pitch_index[int(key, 16)])
                        == after.record(data, roster.pitch_index[int(key, 16)]),
                        f"{key} retained pitching record",
                    )
            continue
        for name in ("first", "last"):
            require(decoded[name] == expected[name], f"{key} {name}")
        for group in ("attributes", "vs_lhp", "vs_rhp", "pitching"):
            if group not in expected:
                continue
            require(group in decoded, f"{key} {group} missing")
            for field, value in expected[group].items():
                require(decoded[group][field] == value, f"{key} {group}.{field}")
        for arr in current.player_arrays[3:]:
            require(not any(arr.record(data, slot)), f"{key} nonzero {arr.label}")
        if "pitching" in expected:
            pi = roster.pitch_index[int(key, 16)]
            for arr in current.pitch_arrays[1:]:
                require(
                    not any(arr.record(data, pi)), f"{key} nonzero pitching statistics"
                )
    inactive = set(actual) - model["players"].keys()
    for key in inactive:
        require(
            actual[key]["attributes"]["hidden"] == 1, f"{key} inactive player visible"
        )
        require(
            not actual[key]["first"] and not actual[key]["last"],
            f"{key} stale inactive name",
        )
        for arr in current.player_arrays[3:]:
            require(
                not any(arr.record(data, roster.index[int(key, 16)])),
                f"{key} stale inactive statistics",
            )
    unused_pitch_slots = set(range(1800)) - set(roster.pitch_index.values())
    for slot in unused_pitch_slots:
        for arr in current.pitch_arrays:
            require(
                not any(arr.record(data, slot)),
                f"unused pitching slot {slot} not clear",
            )
    appearances = Counter()
    team_checks = 0
    for team in current.teams.records:
        expected = model["teams"][team["id"]]
        entries = expected["players"]
        ids = [p["id"] for p in entries]
        require(team["player_ids"] == ids, f"{team['id']} player sequence")
        if expected["code"] not in ("AL", "NL"):
            appearances.update(k for k in ids if k in modern)
        for variant in VARIANTS:
            decoded = team["lineups"][variant]
            for position in POSITIONS:
                role = "SP1" if position == "P" else position
                wanted = next(
                    (
                        p["id"]
                        for p in entries
                        if p["lineups"][variant]["position"] == role
                    ),
                    None,
                )
                slot = decoded["position_slots"][position]
                got = ids[slot] if slot < len(ids) else None
                require(got == wanted, f"{team['id']} {variant} {position}")
                team_checks += 1
            batting = [
                next(p["id"] for p in entries if p["lineups"][variant]["order"] == n)
                for n in range(1, 10)
            ]
            require(
                decoded["batting_player_ids"] == batting,
                f"{team['id']} {variant} batting order",
            )
            team_checks += 9
        for role in ROLE_CAPACITIES:
            selected = [
                p
                for p in entries
                if (
                    p["lineups"]["rh_al"]["position"]
                    in ("SP1", "SP2", "SP3", "SP4", "SP5")
                    if role == "SP"
                    else p["lineups"]["rh_al"]["position"] == role
                )
            ]
            if role == "SP":
                selected.sort(key=lambda p: int(p["lineups"]["rh_al"]["position"][2:]))
            got = [ids[i] for i in team["pitching_roles"][role]["slots"]]
            require(
                got == [p["id"] for p in selected],
                f"{team['id']} {role} pitching assignment",
            )
            team_checks += 1
    require(
        set(appearances) == modern and all(n == 1 for n in appearances.values()),
        "modern roster appearances",
    )
    # Sections with no semantic writer must be byte-identical after relocation.
    require(
        data[200 : current.teams.start] == template[200 : original.teams.start],
        "organization/team description prefix",
    )
    require(
        data[current.teams.end : current.player_map - 8]
        == template[original.teams.end : original.player_map - 8],
        "intermediate team/manager state",
    )
    require(
        data[current.post_arrays : current.footer]
        == template[original.post_arrays : original.footer],
        "opaque trailing section",
    )
    for old, new in zip(
        original.player_arrays + original.pitch_arrays,
        current.player_arrays + current.pitch_arrays,
    ):
        require(
            data[new.offset - 4 : new.offset] == template[old.offset - 4 : old.offset],
            "array marker changed",
        )
    require(
        data[8:12] == template[8:12]
        and data[16:40] == template[16:40]
        and data[72:200] == template[72:200],
        "unrelated header fields",
    )
    expected_icon = (
        ea_crc(icon_sys)
        if icon_sys is not None
        else struct.unpack_from("<I", template, 12)[0]
    )
    require(
        struct.unpack_from("<I", data, 12)[0] == expected_icon,
        "icon.sys checksum metadata",
    )
    return {
        "schema": "mvp-ps2-verification/v1",
        "save_sha256": sha(data),
        "template_sha256": sha(template),
        "model_sha256": sha(
            __import__("json")
            .dumps(model, sort_keys=True, separators=(",", ":"))
            .encode()
        ),
        "checks_passed": checks,
        "team_semantic_comparisons": team_checks,
        "modern_players": len(modern),
        "retained_players": len(model["players"]) - len(modern),
        "inactive_slots": len(inactive),
        "pitching_records": len(expected_pitchers),
        "teams": 126,
        "players_per_team": 25,
        "used_bytes": current.used_end,
        "padding_bytes": len(data) - current.used_end,
        "runtime_validated": False,
    }
