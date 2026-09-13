"""Stage 2: assign logical IDs to physical template slots, without writing bytes."""

import json
from .model import validate_model, sha


def allocate(existing, wanted, capacity):
    """Preserve wanted IDs' existing slots; assign new IDs lowest free slots."""
    mapping = {key: existing[key] for key in wanted if key in existing}
    used = set(mapping.values())
    available = iter(i for i in range(capacity) if i not in used)
    for key in sorted(wanted - mapping.keys()):
        try:
            mapping[key] = next(available)
        except StopIteration:
            raise ValueError("Insufficient physical slots") from None
    return mapping


def make_plan(model, layout):
    validate_model(model)
    roster = layout.roster
    wanted = {int(k, 16) for k in model["players"]}
    preserved = {
        int(k, 16) for k, p in model["players"].items() if p["preserve_template"]
    }
    if preserved - roster.index.keys():
        raise ValueError("Template lacks retained special/default IDs")
    if set(model["teams"]) != {t["id"] for t in layout.teams.records}:
        raise ValueError("Template and model have different team IDs")
    player_map = allocate(roster.index, wanted, 3250)
    used = set(player_map.values())
    # Keep the registry full while retaining every key not displaced by an active ID.
    inactive_keys = sorted(roster.index.keys() - wanted)
    free_slots = [i for i in range(3250) if i not in used]
    # Favor keeping inactive IDs in their old slots where possible.
    inactive = {
        k: roster.index[k] for k in inactive_keys if roster.index[k] in free_slots
    }
    remaining = iter(sorted(set(free_slots) - set(inactive.values())))
    for key in inactive_keys:
        if len(inactive) == len(free_slots):
            break
        if key not in inactive:
            inactive[key] = next(remaining)
    if len(inactive) != len(free_slots):
        raise ValueError("Insufficient inactive registry keys")
    player_map.update(inactive)
    pitch_ids = {
        int(k, 16)
        for k, p in model["players"].items()
        if "pitching" in p
        or (p["preserve_template"] and int(k, 16) in roster.pitch_index)
    }
    pitch_map = allocate(roster.pitch_index, pitch_ids, 1800)
    return {
        "schema": "mvp-ps2-plan/v1",
        "template_sha256": sha(roster.data),
        "model_sha256": sha(
            json.dumps(model, sort_keys=True, separators=(",", ":")).encode()
        ),
        "player_slots": {f"{k:08x}": v for k, v in sorted(player_map.items())},
        "pitcher_slots": {f"{k:08x}": v for k, v in sorted(pitch_map.items())},
        "inactive_ids": [f"{k:08x}" for k in sorted(inactive)],
        "preserved_ids": [f"{k:08x}" for k in sorted(preserved)],
        "counts": {
            "modern_players": 3000,
            "retained_players": len(preserved),
            "player_slots": 3250,
            "inactive_slots": len(inactive),
            "pitching_records": len(pitch_map),
        },
    }
