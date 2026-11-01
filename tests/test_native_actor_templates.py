"""Ordered actor syntax, opaque scripts, parent diagnostics and byte integrity."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from RePoE import native_actor_templates as actor


BASE = "Metadata/Monsters/Monster.ot"
CHILD = "Metadata/Monsters/Example/Example.ot"


def raw(text):
    return b"\xff\xfe" + text.encode("utf-16le")


def template(parent="nothing", body="Stats {}"):
    return raw(f'version 3\r\nextends "{parent}"\r\n{body}\r\n')


class ActorTemplateTests(unittest.TestCase):
    def setUp(self):
        cache = actor.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix="actor-template-test-", dir=cache)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.raw = self.root / "raw"
        self.lock = self.root / "lock.json"
        self.source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": "0.5.5.5",
            "realm": "international",
            "acquisition": {
                "status": "unreviewed-acquisition-draft",
                "evidence": [{"kind": "synthetic", "sha256": "a" * 64}],
            },
            "roots": [CHILD],
            "resources": {},
        }
        self.put(BASE, template())
        self.put(CHILD, template("Metadata/Monsters/Monster"))

    def put(self, name, data):
        path = self.raw / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.source["resources"][name] = {"bytes": len(data), "sha256": actor.envelope._sha(data)}
        self.pin()

    def pin(self):
        data = actor.envelope._json({"schema_version": 1, "sources": {"test": self.source}})
        self.lock.write_bytes(data)
        self.digest = actor.envelope._sha(data)

    def create(self, leaf="candidate"):
        return actor.create_candidate(
            source_lock=self.lock,
            source="test",
            raw=self.raw,
            out=self.root / leaf,
            expected_source_lock_sha256=self.digest,
        )

    def test_order_duplicates_special_keys_scripts_and_exact_spans(self):
        body = (
            "Stats\r\n{\r\n set_base_damage_taken_+% = -50\r\n x = 0\r\n x = -7 // literal\r\n}\r\n"
            "Future\r\n{\r\n Nested {}\r\n on_event =\r\n {\r\n"
            "  Call(\"} // still quoted\", '{'); // } comment\r\n"
            "  if ( x ) { More(); }\r\n }\r\n}\r\n"
            "client\n{\n Functions\n {\n  f = { Call(); }\n }\n}"
        )
        self.put(CHILD, template("Metadata/Monsters/Monster", body))
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            first = self.create()
            self.assertEqual(first, self.create("replay"))
        doc = json.loads((self.root / "candidate/templates.json").read_bytes())
        file = doc["files"][CHILD]
        self.assertEqual([f["key"] for f in file["fields"]], ["set_base_damage_taken_+%", "x", "x", "on_event", "f"])
        self.assertEqual([f["rhs_literal"] for f in file["fields"][:3]], ["-50", "0", "-7 // literal"])
        self.assertEqual(first["summary"]["opaque_rhs_fields"], 2)
        self.assertEqual(doc["roots"][CHILD]["chain_child_to_parent"], [CHILD, BASE])
        self.assertIsNone(doc["interpretation"]["merge_law"])
        self.assertFalse(first["production_ready"])
        for name, syntax in doc["files"].items():
            data = (self.raw / name).read_bytes()
            self.assertEqual(
                b"\xff\xfe" + "".join(line["raw_text"] for line in syntax["lines"]).encode("utf-16le"), data
            )
            for entry in syntax["lines"] + syntax["fields"] + syntax["directives"]:
                start, end = entry["byte_span"]
                self.assertEqual(data[start:end].decode("utf-16le"), entry["raw_text"])
            for block in syntax["blocks"]:
                start, end = block["byte_span"]
                self.assertEqual(actor.envelope._sha(data[start:end]), block["raw_slice_sha256"])
        self.assertIn('Call("} // still quoted",', file["fields"][3]["rhs_literal"])
        self.assertEqual(file["fields"][-1]["scope"], ["client", "Functions"])

    def test_missing_cycle_depth_and_unreachable_are_separate_from_syntax(self):
        self.put(CHILD, template("Metadata/Monsters/Absent"))
        self.source["roots"].append(BASE)
        self.pin()
        self.create()
        doc = json.loads((self.root / "candidate/templates.json").read_bytes())
        self.assertEqual(
            doc["roots"][CHILD]["diagnostic"], {"code": "missing-resource", "resource": "Metadata/Monsters/Absent.ot"}
        )
        self.put(CHILD, template("Metadata/Monsters/Example/Example"))
        self.create("cycle")
        doc = json.loads((self.root / "cycle/templates.json").read_bytes())
        self.assertEqual(doc["roots"][CHILD]["diagnostic"]["code"], "cycle")
        files = {str(i): {"extends": {"target": str(i + 1)}} for i in range(17)}
        chains, _ = actor.parent_chains(["0"], files)
        self.assertEqual(chains["0"]["diagnostic"], {"code": "depth-limit", "resource": "16"})
        self.source["roots"] = [CHILD]
        self.pin()
        with self.assertRaisesRegex(ValueError, "outside bounded"):
            self.create("unreachable")

    def test_malformed_or_unrepresented_syntax_fails_without_filtering(self):
        for text in [
            'version 3\nextends "nothing"\nFuture()\n',
            'version 3\nextends "nothing"\n"unknown literal"\n',
            'version 3\nextends "nothing"\nUnknown "extra"\n{\n}\n',
            'version 3\nextends "nothing"\nStats\n{\nx = { Call(); } "extra"\n}\n',
            'version 3\nextends "nothing"\nStats\n{\n} "extra"\n',
            'version 3\nextends "nothing"\nStats\n{\nx = { Call();\n}\n',
            'version 3\nextends "nothing"\nStats\n{\nx = "unterminated\n}\n',
            'version 3\nextends "nothing"\nStats\n{\nx = { Call(); } trailing\n}\n',
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                actor.parse_template(BASE, raw(text))
        for data in [b"no BOM", b"\xff\xfe\x00", template() + raw("}")[2:]]:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                actor.parse_template(BASE, data)

    def test_pins_paths_and_publication_guards(self):
        self.digest = "b" * 64
        with self.assertRaisesRegex(ValueError, "external expected"):
            self.create()
        self.pin()
        (self.raw / BASE).write_bytes(template(body="Changed {}"))
        with patch.object(actor, "parse_template", side_effect=AssertionError("must verify all pins first")):
            with self.assertRaisesRegex(ValueError, "fingerprint|byte limit"):
                self.create()
        self.put(BASE, template())
        self.create()
        with self.assertRaises(FileExistsError):
            self.create()
        for name in [
            "Metadata/../escape.ot",
            "Metadata/Monsters/Example.it",
            "Metadata/Monsters/Bad.OT",
            "Metadata/Monsters/Bad.ot.ot",
        ]:
            with self.assertRaises(ValueError):
                actor.resource_path(name)
        with self.assertRaisesRegex(ValueError, "beneath"):
            actor.create_candidate(
                source_lock=self.lock,
                source="test",
                raw=self.raw,
                out=actor.ROOT / "forbidden",
                expected_source_lock_sha256=self.digest,
            )
        path = self.raw / BASE
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.create("symlink")

    def test_block_comments_reject_outside_strings_and_known_line_comments(self):
        for body in [
            "Stats\n{\nx = 1 /* misleading comment */\n}",
            "Stats\n{\nx = /* unknown syntax */\n}",
            "Events\n{\nx = { Call(); /* unsupported */ More(); }\n}",
            "Events\n{\nx = {\n /* multiline\n comment */\n Call();\n}\n}",
        ]:
            with self.subTest(body=body):
                self.put(CHILD, template("Metadata/Monsters/Monster", body))
                with self.assertRaisesRegex(ValueError, "Unsupported C-style"):
                    self.create()
                self.assertFalse((self.root / "candidate").exists())
        body = (
            "Stats\n{\nx = \"/* quoted */\"\ny = '/* single quoted */'\n"
            "z = 1 // /* known line comment */\n# /* known whole-line comment */\n}\n"
            'Events\n{\nx = { Call("/* quoted event */"); // /* line comment */\n}\n}'
        )
        parsed = actor.parse_template(CHILD, template("Metadata/Monsters/Monster", body))
        self.assertEqual(
            [field["rhs_literal"] for field in parsed["fields"][:3]],
            ['"/* quoted */"', "'/* single quoted */'", "1 // /* known line comment */"],
        )
        self.assertEqual(parsed["fields"][-1]["rhs_kind"], "opaque-braced")

    def test_input_changes_during_parse_reject_before_publication(self):
        original = actor.parse_template

        def mutate(name, data):
            result = original(name, data)
            (self.raw / name).write_bytes(template(body="Changed {}"))
            return result

        with patch.object(actor, "parse_template", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "fingerprint|changed during"):
                self.create()
        self.assertFalse((self.root / "candidate").exists())

    def test_otc_parent_suffix_is_only_a_literal_path_convention(self):
        parsed = actor.parse_template("Metadata/Monsters/Test.otc", template("Metadata/Monsters/Parent"))
        self.assertEqual(parsed["extends"]["target"], "Metadata/Monsters/Parent.otc")


if __name__ == "__main__":
    unittest.main()
