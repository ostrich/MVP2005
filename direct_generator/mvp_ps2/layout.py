"""Validated save sections, slot maps, packed fields, and container framing.

The container remains the template's fixed size. Only verified trailing fill may
be consumed when variable team records grow; no payload is silently truncated.
"""

from dataclasses import dataclass
import struct
from ps2_roster import Roster, ea_crc

PLAYER_SIZES = (60, 16, 16, 4, 12, 12, 4, 12, 12, 4, 4, 4, 4, 4, 16)
PLAYER_LABELS = (
    "attributes",
    "vs_lhp",
    "vs_rhp",
    "batting_current",
    "batting_lh_current",
    "batting_rh_current",
    "batting_previous",
    "batting_lh_previous",
    "batting_rh_previous",
    "fielding_current",
    "fielding_previous",
    "fielding_minor_1",
    "fielding_minor_2",
    "fielding_minor_3",
    "career",
)
PITCH_SIZES = (20, 12, 12, 12, 12, 12, 12, 12)
FOOTER = bytes.fromhex("0df0efbe")


def put_fields(raw, fields, values):
    n = int.from_bytes(raw, "little")
    for name, value in values.items():
        if name not in fields:
            raise ValueError(f"Unknown packed field: {name}")
        bit, width = fields[name]
        if not isinstance(value, int) or not 0 <= value < 1 << width:
            raise ValueError(f"{name}: {value!r} exceeds unsigned {width}-bit field")
        if bit + width > len(raw) * 8:
            raise ValueError("Field outside record")
        mask = ((1 << width) - 1) << bit
        n = (n & ~mask) | (value << bit)
    return n.to_bytes(len(raw), "little")


def pack_map(mapping, capacity):
    if len(mapping) > capacity or len(set(mapping.values())) != len(mapping):
        raise ValueError("Invalid map size or duplicate slots")
    if any(
        not 0 <= k <= 0xFFFFFFFF or not 0 <= v < capacity for k, v in mapping.items()
    ):
        raise ValueError("Invalid map key or slot")
    return b"".join(
        struct.pack("<III", key, slot, slot)
        for key, slot in sorted(mapping.items(), key=lambda item: item[0] ^ 0x80000000)
    ) + bytes((capacity - len(mapping)) * 12)


@dataclass(frozen=True)
class Array:
    offset: int
    size: int
    capacity: int
    label: str

    def record(self, data, slot):
        if not 0 <= slot < self.capacity:
            raise ValueError("Slot outside array")
        at = self.offset + self.size * slot
        return data[at : at + self.size]

    def write(self, data, slot, raw):
        if not 0 <= slot < self.capacity or len(raw) != self.size:
            raise ValueError("Invalid array write")
        at = self.offset + self.size * slot
        data[at : at + self.size] = raw


class Layout:
    def __init__(self, data):
        self.roster = Roster(data)
        if self.roster.platform != "ps2":
            raise ValueError("PS2 save template required")
        self.teams = self.roster.teams()
        for mapping in (self.roster.index, self.roster.pitch_index):
            if list(mapping) != sorted(mapping, key=lambda k: k ^ 0x80000000):
                raise ValueError(
                    "Registry keys must be sorted as signed 32-bit integers"
                )
        self.player_map = self.roster.attrib - 4 - 3250 * 12
        if struct.unpack_from("<II", data, self.player_map - 8) != (3250, 3250):
            raise ValueError("Unsupported player map header")
        self.player_arrays = []
        at = self.roster.attrib - 4
        for i, (size, label) in enumerate(zip(PLAYER_SIZES, PLAYER_LABELS)):
            marker = 0xF58F3C1B if i < 9 else (0x083CD1DA if i < 14 else 0x9FF4798E)
            if struct.unpack_from("<I", data, at)[0] != marker:
                raise ValueError(f"Bad {label} marker")
            self.player_arrays.append(Array(at + 4, size, 3250, label))
            at += 4 + size * 3250
        if at != self.roster.pitch_header:
            raise ValueError("Player array boundary mismatch")
        self.pitch_map = at + 8
        self.pitch_arrays = []
        at = self.roster.pitch - 4
        for i, size in enumerate(PITCH_SIZES):
            if i and struct.unpack_from("<I", data, at)[0] != 0xF58F3C1B:
                raise ValueError("Bad pitching statistics marker")
            self.pitch_arrays.append(Array(at + 4, size, 1800, f"pitching_{i}"))
            at += 4 + size * 1800
        self.post_arrays = at
        self.footer = at + 700
        if data[self.footer : self.footer + 4] != FOOTER:
            raise ValueError("Unsupported trailing save structure")
        if struct.unpack_from("<I", data, self.footer + 4)[0] != self.footer + 4 - 200:
            raise ValueError("Footer serialized length mismatch")
        self.used_end = self.footer + 8
        fill = data[self.used_end :]
        if any(
            v != (0x55 if i % 2 == 0 else 0xBB)
            for i, v in enumerate(fill, self.used_end)
        ):
            # All known files use this absolute-offset debug-fill pattern.
            raise ValueError("Unrecognized trailing padding; cannot resize safely")

    def reframe(self, edited, team_bytes, save_name):
        if len(edited) != len(self.roster.data):
            raise ValueError("Unexpected template length change")
        start, end = self.teams.start, self.teams.end
        delta = len(team_bytes) - (end - start)
        used = bytearray(edited[:start] + team_bytes + edited[end : self.used_end])
        if len(used) > len(edited):
            raise ValueError(
                f"Roster exceeds save capacity by {len(used) - len(edited)} bytes"
            )
        struct.pack_into(
            "<I", used, self.footer + delta + 4, self.footer + delta + 4 - 200
        )
        name = save_name.encode("utf-16le")
        if not save_name or len(name) > 30 or "\0" in save_name:
            raise ValueError("Save name must fit 15 UTF-16 units")
        used[40:72] = name + bytes(32 - len(name))
        used.extend(0x55 if i % 2 == 0 else 0xBB for i in range(len(used), len(edited)))
        struct.pack_into("<I", used, 0, ea_crc(used[16:200]))
        struct.pack_into("<I", used, 4, ea_crc(used[200:]))
        result = bytes(used)
        Layout(result)
        return result
