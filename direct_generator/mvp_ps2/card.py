"""Stage 5: save + template card -> independently checked memory-card image.

Only the roster file, its filename, and its icon title change. Directory/FAT
allocation and other saves are preserved. No emulator or original-card writes.
"""

import re
import struct
from pathlib import PurePosixPath
from tools.ps2_card import Card
from tools.ps2_patch_card import replace, page_ecc
from ps2_roster import Roster, ea_crc
from .model import sha
from .verify import verify


def select_save(card_bytes, member=None):
    files = {p.as_posix(): data for p, data, _ in Card(card_bytes).files()}
    matches = [
        p for p in files if p.endswith(".sav") and (member is None or p == member)
    ]
    if len(matches) != 1:
        raise ValueError("Select exactly one roster save using --member")
    member = matches[0]
    data = files[member]
    roster = Roster(data)
    if roster.platform != "ps2":
        raise ValueError("Card member is not a PS2 save")
    folder = str(PurePosixPath(member).parent)
    if data[168:200].split(b"\0")[0].decode("ascii") != folder:
        raise ValueError("Save header and memory-card folder disagree")
    for offset, name in ((8, "title.ico"), (12, "icon.sys")):
        content = files.get(folder + "/" + name)
        if content is None or struct.unpack_from("<I", data, offset)[0] != ea_crc(
            content
        ):
            raise ValueError(f"Template {name} missing or checksum mismatch")
    return member, data, files


def entry_page(card, target):
    """Locate the target's live directory entry by traversing directory chains."""
    visited = set()
    found = []

    def walk(first, count, prefix):
        if first in visited:
            raise ValueError("Directory cycle")
        visited.add(first)
        remaining = count
        for cluster in card.chain(first):
            for part in range(2):
                if not remaining:
                    return
                page = (cluster + card.alloc) * 2 + part
                raw = card.raw[page * card.stride : page * card.stride + 512]
                remaining -= 1
                mode = struct.unpack_from("<H", raw)[0]
                name = raw[64:].split(b"\0")[0].decode("ascii")
                if not mode & 0x8000 or name in (".", ".."):
                    continue
                path = prefix + "/" + name if prefix else name
                if path == target:
                    found.append(page)
                if mode & 0x20:
                    walk(
                        struct.unpack_from("<I", raw, 16)[0],
                        struct.unpack_from("<I", raw, 4)[0],
                        path,
                    )
        if remaining:
            raise ValueError("Truncated directory")

    root = card.cluster(card.root + card.alloc)
    walk(card.root, struct.unpack_from("<I", root, 4)[0], "")
    if len(found) != 1:
        raise ValueError("Could not uniquely locate save directory entry")
    return found[0]


def rename(image, member, name):
    card = Card(image)
    page = entry_page(card, member)
    offset = page * card.stride
    old = image[offset : offset + 512]
    if card.stride == 528 and image[offset + 512 : offset + 524] != page_ecc(old):
        raise ValueError("Directory page ECC invalid")
    raw = name.encode("ascii")
    if not raw or len(raw) > 447 or any(c in name for c in "/\\\0"):
        raise ValueError("Invalid card filename")
    new = old[:64] + raw + bytes(448 - len(raw))
    out = bytearray(image)
    out[offset : offset + 512] = new
    if card.stride == 528:
        out[offset + 512 : offset + 524] = page_ecc(new)
    return bytes(out)


def package(model, template_card, save, member=None):
    member, template, files = select_save(template_card, member)
    verify(model, save, template)
    name = save[40:72].decode("utf-16le").split("\0")[0]
    if not re.fullmatch(r"[A-Za-z0-9]{1,15}", name):
        raise ValueError("Card save name must be 1–15 ASCII letters/digits")
    folder = str(PurePosixPath(member).parent)
    new_member = folder + "/" + name + ".sav"
    if new_member != member and new_member in files:
        raise ValueError("New save filename collides with an existing file")
    icon = bytearray(files[folder + "/icon.sys"])
    if len(icon) != 964 or icon[:4] != b"PS2D":
        raise ValueError("Unsupported icon.sys format")
    # PS2 browser title uses full-width Shift-JIS; preserve lighting and filenames.
    title = "MVP 2005 " + name
    title = "".join(
        "\u3000" if c == " " else chr(ord(c) + 0xFEE0) for c in title
    ).encode("shift_jis")
    if len(title) > 66:
        raise ValueError("Icon title exceeds field capacity")
    icon[192:260] = title + bytes(68 - len(title))
    icon = bytes(icon)
    packaged = bytearray(save)
    struct.pack_into("<I", packaged, 12, ea_crc(icon))
    packaged = bytes(packaged)
    image = replace(template_card, member, packaged)
    image = replace(image, folder + "/icon.sys", icon)
    if new_member != member:
        image = rename(image, member, name + ".sav")
    expected = dict(files)
    del expected[member]
    expected[new_member] = packaged
    expected[folder + "/icon.sys"] = icon
    actual = {p.as_posix(): b for p, b, _ in Card(image).files()}
    if actual != expected:
        raise ValueError("Packaged card filesystem differs from expected files")
    # Repeat header/icon checks through the independent card reader.
    select_save(image, new_member)
    report = verify(
        model, actual[new_member], template, icon_sys=actual[folder + "/icon.sys"]
    )
    card = Card(image)
    pages = []
    for offset in range(0, len(image), card.stride):
        if (
            image[offset : offset + card.stride]
            == template_card[offset : offset + card.stride]
        ):
            continue
        pages.append(offset // card.stride)
        if card.stride == 528 and image[offset + 512 : offset + 524] != page_ecc(
            image[offset : offset + 512]
        ):
            raise ValueError("Packaged card page ECC mismatch")
    report.update(
        card_sha256=sha(image),
        template_card_sha256=sha(template_card),
        member=new_member,
        changed_pages=len(pages),
        changed_page_ecc="passed" if card.stride == 528 else "not applicable",
        other_files_preserved=True,
        icon_title=title.decode("shift_jis"),
    )
    return image, packaged, icon, report
