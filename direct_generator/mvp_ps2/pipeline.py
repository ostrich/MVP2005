"""Stage orchestration and atomic artifact publication; no binary layout logic."""

from contextlib import contextmanager
from pathlib import Path
import json
import os
import tempfile
from .model import sha, normalize
from .encode import encode
from .verify import verify
from .card import package, select_save


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".mvp-", delete=False
        ) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, path)  # Refuses even an existing dangling symlink.
    finally:
        if tmp is not None:
            tmp.unlink()


@contextmanager
def new_directory(output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".mvp-ps2-") as temp:
        staged = Path(temp) / "result"
        staged.mkdir()
        yield staged
        if output.exists() or output.is_symlink():
            raise ValueError(f"Output appeared during build: {output}")
        staged.rename(output)


def encode_stage(model, template, name, output, allocation=None):
    data, plan = encode(model, template, name, allocation)
    report = verify(model, data, template)
    output.mkdir(parents=True, exist_ok=True)
    (output / "roster.sav").write_bytes(data)
    (output / "plan.json").write_bytes(json_bytes(plan))
    (output / "verification.json").write_bytes(json_bytes(report))
    return data, report


def package_stage(model, card, save, member, output):
    image, final_save, icon, report = package(model, card, save, member)
    output.mkdir(parents=True, exist_ok=True)
    (output / "roster.ps2").write_bytes(image)
    (output / "roster.sav").write_bytes(final_save)
    (output / "icon.sys").write_bytes(icon)
    (output / "verification.json").write_bytes(json_bytes(report))
    return report


def build(
    source,
    baseline,
    template_card,
    output,
    year,
    name,
    member=None,
    reference_cards=None,
    progress=print,
    prepared=None,
):
    with new_directory(output) as staged:
        if reference_cards is not None:
            from .references import check_references

            progress("Checking reference saves and stock PS2 roster DAT...")
            refs = check_references(reference_cards, baseline)
            (staged / "references.json").write_bytes(json_bytes(refs))
        progress("Normalizing CSV into logical players and teams...")
        model = normalize(source, baseline, year, prepared)
        (staged / "model.json").write_bytes(json_bytes(model))
        card = Path(template_card).read_bytes()
        member, template, _ = select_save(card, member)
        progress("Assigning slots, encoding save, and verifying decoded values...")
        data, save_report = encode_stage(model, template, name, staged / "encoding")
        progress("Packaging memory card, refreshing title/ECC, and re-verifying...")
        report = package_stage(model, card, data, member, staged / "card")
        (staged / "README.md").write_text(
            "# Generated MVP 2005 PS2 roster\n\n"
            "`card/roster.ps2` is the generated memory card. Add a copy as a memory card "
            "in PCSX2, boot MVP Baseball 2005 (USA), and load the roster named "
            + name
            + ". "
            "Do not overwrite your existing card.\n\n"
            "Binary and semantic checks passed. No PS2 runtime validation has been performed. "
            "The full roster contains 3000 modern players, 100 retained special players, "
            "and one Default record.\n\n"
            "`model.json` records normalized inputs and approximations; `encoding/` contains "
            "the pre-packaging save and slot plan; `card/roster.sav` includes the final icon checksum. "
            "Use the latter with the packaged card. `card/verification.json` records the final hashes.\n\n"
            "This changes roster data, not team branding, the 2005 calendar, historical archives "
            "on the game disc, or game rules. Generic animation fallbacks are listed in the model report.\n"
        )
        manifest = {
            p.relative_to(staged).as_posix(): sha(p.read_bytes())
            for p in sorted(staged.rglob("*"))
            if p.is_file()
        }
        (staged / "manifest.json").write_bytes(
            json_bytes(
                {
                    "schema": "mvp-ps2-build/v1",
                    "files": manifest,
                    "generator_source_sha256": source_hashes(),
                    "source_sha256": sha(Path(source).read_bytes()),
                    "template_card_sha256": sha(card),
                    "runtime_validated": False,
                    "result": report,
                }
            )
        )
    return report


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / name
        for name in (
            "ps2_generate.py",
            "generate_rosters.py",
            "mvp_rosters.py",
            "ps2_roster.py",
            "ps2_teams.py",
            "tools/ps2_card.py",
            "tools/ps2_image.py",
            "tools/ea_big.py",
            "tools/ps2_patch_card.py",
            "tools/verify_save_teams.py",
        )
    ]
    paths += sorted((root / "mvp_ps2").glob("*.py"))
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in paths}
