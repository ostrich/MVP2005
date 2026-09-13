import copy
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from mvp_ps2.layout import Layout, pack_map
from mvp_ps2.model import normalize, load, sha
from mvp_ps2.encode import encode
from mvp_ps2.plan import make_plan
from mvp_ps2.verify import verify
from mvp_ps2.card import package, select_save
from mvp_ps2.pipeline import build, write_new
from ps2_roster import Roster, ea_crc

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
SOURCE = REPOSITORY / "data/MVProsters/MVProsters_2026-09-05.csv"
BASELINE = Path(os.environ.get("MVP2005_PS2_DATABASE", ROOT / "work/ps2-database"))
CARD = REPOSITORY / "memcards/misc/MVP05Rosters-Nerf.ps2"


class PrimitiveTests(unittest.TestCase):
    def test_registry_order_is_signed_not_unsigned(self):
        keys = [
            k
            for k, _, _ in struct.iter_unpack(
                "<III", pack_map({0: 0, 0x7FFFFFFF: 1, 0x80000000: 2, 0xFFFFFFFF: 3}, 4)
            )
        ]
        self.assertEqual(keys, [0x80000000, 0xFFFFFFFF, 0, 0x7FFFFFFF])

    def test_artifact_writer_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "file"
            write_new(path, b"first")
            with self.assertRaises(FileExistsError):
                write_new(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")
            self.assertEqual(list(Path(d).glob(".mvp-*")), [])


@unittest.skipUnless(
    SOURCE.exists() and BASELINE.exists() and CARD.exists(),
    "Local CSV, extracted PS2 DATs, and template card required",
)
class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = CARD.read_bytes()
        cls.member, cls.template, cls.files = select_save(cls.card)
        cls.model = normalize(SOURCE, BASELINE, 2026)
        cls.save, cls.plan = encode(cls.model, cls.template, "20260905")
        cls.layout = Layout(cls.save)

    def test_saved_allocation_plan_binds_to_input(self):
        plan = make_plan(self.model, Layout(self.template))
        save, encoded_plan = encode(self.model, self.template, "20260905", plan)
        self.assertEqual(save, self.save)
        self.assertEqual(encoded_plan, plan)
        bad = copy.deepcopy(plan)
        bad["model_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Allocation plan"):
            encode(self.model, self.template, "20260905", bad)

    def test_full_roster_and_all_semantics(self):
        report = verify(self.model, self.save, self.template)
        self.assertEqual(report["modern_players"], 3000)
        self.assertEqual(report["retained_players"], 101)
        self.assertEqual(report["inactive_slots"], 149)
        self.assertEqual(report["pitching_records"], 1542)
        self.assertEqual(report["padding_bytes"], 135)
        self.assertFalse(report["runtime_validated"])
        self.assertEqual(len(self.save), 937160)
        # Freshly decoded key order must be signed-sorted for the game's lookup.
        keys = list(Roster(self.save).index)
        self.assertEqual(keys, sorted(keys, key=lambda k: k ^ 0x80000000))

    def test_packaged_card_title_checksums_and_original_preservation(self):
        image, save, icon, report = package(self.model, self.card, self.save)
        self.assertEqual(len(image), 8650752)
        member, inner, files = select_save(image)
        self.assertTrue(member.endswith("/20260905.sav"))
        self.assertEqual(inner, save)
        title = icon[192:260].split(b"\0")[0].decode("shift_jis")
        self.assertEqual(title, "ＭＶＰ　２００５　２０２６０９０５")
        self.assertEqual(struct.unpack_from("<I", save, 12)[0], ea_crc(icon))
        for key, value in self.files.items():
            if key not in (self.member, self.member.rsplit("/", 1)[0] + "/icon.sys"):
                self.assertEqual(files[key], value)
        self.assertEqual(CARD.read_bytes(), self.card)
        self.assertEqual(report["changed_page_ecc"], "passed")

    def test_future_save_name_works_without_new_template(self):
        save, _ = encode(self.model, self.template, "20301231")
        image, _, icon, report = package(self.model, self.card, save)
        member, inner, _ = select_save(image)
        self.assertTrue(member.endswith("/20301231.sav"))
        self.assertEqual(inner[40:72].decode("utf-16le").rstrip("\0"), "20301231")
        self.assertTrue(
            icon[192:260]
            .split(b"\0")[0]
            .decode("shift_jis")
            .endswith("２０３０１２３１")
        )

    def test_semantic_corruption_rejected_even_with_valid_crc(self):
        rid = next(
            k for k, p in self.model["players"].items() if not p["preserve_template"]
        )
        value = self.model["players"][rid]["attributes"]["jerseynum"]
        corrupted = Roster(self.save).patch(
            rid, "attributes.jerseynum", (value + 1) % 100
        )
        with self.assertRaisesRegex(ValueError, "jerseynum"):
            verify(self.model, corrupted, self.template)

    def test_stale_statistics_rejected(self):
        rid = next(
            k for k, p in self.model["players"].items() if not p["preserve_template"]
        )
        b = bytearray(self.save)
        arr = self.layout.player_arrays[-1]
        b[arr.offset + self.layout.roster.index[int(rid, 16)] * arr.size] = 1
        struct.pack_into("<I", b, 4, ea_crc(b[200:]))
        with self.assertRaisesRegex(ValueError, "nonzero career"):
            verify(self.model, bytes(b), self.template)

    def test_map_reordering_and_footer_corruption_rejected(self):
        for kind in ("map", "footer"):
            b = bytearray(self.save)
            if kind == "map":
                at = self.layout.player_map
                b[at : at + 12], b[at + 12 : at + 24] = (
                    b[at + 12 : at + 24],
                    b[at : at + 12],
                )
            else:
                b[self.layout.footer + 4] ^= 1
            struct.pack_into("<I", b, 4, ea_crc(b[200:]))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                Layout(bytes(b))

    def test_insufficient_padding_never_truncates_payload(self):
        l = Layout(self.template)
        teams = self.template[l.teams.start : l.teams.end] + bytes(1000)
        with self.assertRaisesRegex(ValueError, "exceeds save capacity"):
            l.reframe(self.template, teams, "20260905")

    def test_incomplete_model_or_role_overflow_rejected(self):
        bad = copy.deepcopy(self.model)
        rid = next(k for k, p in bad["players"].items() if not p["preserve_template"])
        del bad["players"][rid]["attributes"]["height"]
        with self.assertRaisesRegex(ValueError, "Incomplete attributes"):
            encode(bad, self.template, "20260905")
        bad = copy.deepcopy(self.model)
        team = next(t for t in bad["teams"].values() if t["code"] == "Ana")
        pen = [
            p
            for p in team["players"]
            if p["lineups"]["rh_al"]["position"] in ("LR", "MR", "SU")
        ]
        for p in pen:
            for entry in p["lineups"].values():
                entry["position"] = "LR"
        with self.assertRaisesRegex(ValueError, "Bullpen exceeds"):
            encode(bad, self.template, "20260905")

    def test_combined_build_matches_split_stages_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "package"
            build(
                SOURCE, BASELINE, CARD, out, 2026, "20260905", progress=lambda _: None
            )
            reloaded = load(out / "model.json")
            encoded, _ = encode(reloaded, self.template, "20260905")
            self.assertEqual(encoded, (out / "encoding/roster.sav").read_bytes())
            image, save, _, _ = package(reloaded, self.card, encoded)
            self.assertEqual(image, (out / "card/roster.ps2").read_bytes())
            self.assertEqual(save, (out / "card/roster.sav").read_bytes())
            manifest = json.loads((out / "manifest.json").read_text())
            for path, digest in manifest["files"].items():
                self.assertEqual(sha((out / path).read_bytes()), digest)
            with self.assertRaisesRegex(ValueError, "Output exists"):
                build(
                    SOURCE,
                    BASELINE,
                    CARD,
                    out,
                    2026,
                    "20260905",
                    progress=lambda _: None,
                )


if __name__ == "__main__":
    unittest.main()
