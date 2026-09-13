"""Stage 3: encode a logical roster into a validated PS2 save template."""

import copy
import struct
from ps2_roster import ATTR, BATTING, PITCHING
from ps2_teams import VARIANTS, POSITIONS, ROLE_CAPACITIES, serialize_team
from .layout import Layout, put_fields, pack_map
from .plan import make_plan


def team_record(logical, template):
    r = copy.deepcopy(template)
    players = logical["players"]
    ids = [p["id"] for p in players]
    r["player_ids"] = ids
    r["fixed_player_ids"] = ids + ["00000000"] * (25 - len(ids))
    r["metadata"] = 0
    for variant in VARIANTS:
        positions = {p: 255 for p in POSITIONS}
        orders = [0xFFFFFFFF] * 9
        for slot, entry in enumerate(players):
            role = entry["lineups"][variant]["position"]
            order = entry["lineups"][variant]["order"]
            position = "P" if role == "SP1" else role
            if position in positions:
                positions[position] = slot
            if order != -1:
                if position not in POSITIONS:
                    raise ValueError("Batting player lacks a field position")
                orders[order - 1] = POSITIONS.index(position)
        lineup = r["lineups"][variant]
        lineup["position_slots"] = positions
        lineup["batting_positions"] = orders
    for role, capacity in ROLE_CAPACITIES.items():
        slots = [
            i
            for i, p in enumerate(players)
            if p["lineups"]["rh_al"]["position"].startswith(role)
        ]
        if role == "SP":
            slots.sort(
                key=lambda i: int(players[i]["lineups"]["rh_al"]["position"][2:])
            )
        if len(slots) > capacity:
            raise ValueError("Too many pitchers in role")
        r["pitching_roles"][role].update(
            fixed=slots + [255] * (capacity - len(slots)), slots=slots, metadata=0
        )
    return r


def encode(model, template, save_name, plan=None):
    layout = Layout(template)
    roster = layout.roster
    expected_plan = make_plan(model, layout)
    if plan is not None and plan != expected_plan:
        raise ValueError("Allocation plan does not match model and template")
    plan = expected_plan
    player_map = {int(k, 16): v for k, v in plan["player_slots"].items()}
    pitch_map = {int(k, 16): v for k, v in plan["pitcher_slots"].items()}
    default = 0xF58F3C1B
    default_slot = roster.index[default]
    default_pitch = roster.pitch_index.get(default)
    if default_pitch is None:
        raise ValueError("Template lacks Default pitching record")
    out = bytearray(template)
    inactive = set(plan["inactive_ids"])
    for key, slot in player_map.items():
        rid = f"{key:08x}"
        p = model["players"].get(rid)
        if p and p["preserve_template"]:
            for arr in layout.player_arrays:
                arr.write(out, slot, arr.record(template, roster.index[key]))
            continue
        # New identities must not inherit old players' statistics or injuries.
        for arr in layout.player_arrays[3:]:
            arr.write(out, slot, bytes(arr.size))
        raw = layout.player_arrays[0].record(template, default_slot)
        if rid in inactive:
            raw = put_fields(raw, ATTR, {"hidden": 1, "audioid": 0})
            raw = raw[:31] + bytes(28) + raw[59:]
            layout.player_arrays[0].write(out, slot, raw)
            for arr in layout.player_arrays[1:3]:
                arr.write(out, slot, arr.record(template, default_slot))
            continue
        raw = put_fields(raw, ATTR, p["attributes"])
        first = p["first"].encode("cp1252")
        last = p["last"].encode("cp1252")
        raw = (
            raw[:31]
            + first
            + bytes(12 - len(first))
            + last
            + bytes(16 - len(last))
            + raw[59:]
        )
        layout.player_arrays[0].write(out, slot, raw)
        for arr, group in zip(layout.player_arrays[1:3], ("vs_lhp", "vs_rhp")):
            arr.write(
                out,
                slot,
                put_fields(arr.record(template, default_slot), BATTING, p[group]),
            )
    # Unused pitching slots must not retain records belonging to displaced IDs.
    for arr in layout.pitch_arrays:
        out[arr.offset : arr.offset + arr.size * arr.capacity] = bytes(
            arr.size * arr.capacity
        )
    for key, slot in pitch_map.items():
        p = model["players"][f"{key:08x}"]
        if p["preserve_template"]:
            for arr in layout.pitch_arrays:
                arr.write(out, slot, arr.record(template, roster.pitch_index[key]))
        else:
            arr = layout.pitch_arrays[0]
            raw = put_fields(
                arr.record(template, default_pitch), PITCHING, p["pitching"]
            )
            arr.write(out, slot, raw)
    out[layout.player_map : layout.player_map + 3250 * 12] = pack_map(player_map, 3250)
    struct.pack_into("<II", out, roster.pitch_header, 1800, len(pitch_map))
    out[layout.pitch_map : layout.pitch_map + 1800 * 12] = pack_map(pitch_map, 1800)
    records = [team_record(model["teams"][t["id"]], t) for t in layout.teams.records]
    team_bytes = b"".join(serialize_team(t, player_map) for t in records)
    result = layout.reframe(out, team_bytes, save_name)
    return result, plan
