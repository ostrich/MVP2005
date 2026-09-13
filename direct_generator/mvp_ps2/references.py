"""Reference-save checks independent of generated output."""

from pathlib import Path
import struct
from tools.ps2_card import Card
from tools.verify_save_teams import compare
from mvp_rosters import Table
from ps2_roster import ea_crc, ATTR, BATTING, PITCHING, decode
from ps2_teams import serialize_team
from .layout import Layout, put_fields, pack_map
from .model import sha


def check_references(cards_dir, stock_database):
    records = []
    nerf_comparison = None
    for path in sorted(Path(cards_dir).rglob("*.ps2")):
        files = {p.as_posix(): b for p, b, _ in Card(path.read_bytes()).files()}
        for name, data in files.items():
            if not name.endswith(".sav"):
                continue
            layout = Layout(data)
            r = layout.roster
            parent = name.rsplit("/", 1)[0]
            for off, icon in ((8, "title.ico"), (12, "icon.sys")):
                if struct.unpack_from("<I", data, off)[0] != ea_crc(
                    files[parent + "/" + icon]
                ):
                    raise ValueError("Reference icon checksum mismatch")
            teams = b"".join(serialize_team(t, r.index) for t in layout.teams.records)
            if teams != data[layout.teams.start : layout.teams.end]:
                raise ValueError("Reference team round trip failed")
            if (
                pack_map(r.index, 3250)
                != data[layout.player_map : layout.player_map + 3250 * 12]
            ):
                raise ValueError("Reference player map round trip failed")
            if (
                pack_map(r.pitch_index, 1800)
                != data[layout.pitch_map : layout.pitch_map + 1800 * 12]
            ):
                raise ValueError("Reference pitcher map round trip failed")
            for arr, fields in zip(
                layout.player_arrays[:3] + layout.pitch_arrays[:1],
                (ATTR, BATTING, BATTING, PITCHING),
            ):
                for slot in range(arr.capacity):
                    raw = arr.record(data, slot)
                    if put_fields(raw, fields, decode(raw, fields)) != raw:
                        raise ValueError("Reference packed-field round trip failed")
            save_name = data[40:72].decode("utf-16le").split("\0")[0]
            if layout.reframe(data, teams, save_name) != data:
                raise ValueError("Reference container round trip failed")
            if Path(name).name == "Nerf.sav":
                nerf_comparison = compare(
                    data, Table.read(Path(stock_database) / "roster.dat")
                )
                if nerf_comparison["differences"]:
                    raise ValueError("Stock PS2 team semantic comparison failed")
            records.append(
                {
                    "card": path.name,
                    "member": name,
                    "sha256": sha(data),
                    "roundtrip": "byte-exact",
                    "teams": 126,
                    "used_bytes": layout.used_end,
                }
            )
    if not records:
        raise ValueError("No reference saves found")
    if nerf_comparison is None:
        raise ValueError("Nerf reference required for independent stock DAT comparison")
    return {
        "schema": "mvp-ps2-reference-report/v1",
        "saves": records,
        "stock_team_comparisons": nerf_comparison["comparisons"],
        "stock_team_differences": 0,
        "runtime_validated": False,
    }
