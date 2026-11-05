"""Portable lexical metadata contracts; no client files or inheritance semantics."""

import unittest

from RePoE.native.metadata import parse_metadata, resource_path, validate_closure


def raw(text):
    return b"\xff\xfe" + text.encode("utf-16-le")


def parse(name, text):
    return parse_metadata(name, raw(text))


class NativeMetadataTests(unittest.TestCase):
    def test_exact_utf16_line_and_value_spans(self):
        data = raw('version 3\r\nextends "nothing"\r\nStats\r\n{\r\n  life = 12 // 保留\r\n  label = "💎 { }"\r\n}\r\n')
        doc = parse_metadata("Metadata/Character.ot", data)
        offset = 2
        for record in doc["records"]:
            self.assertEqual(record["byte_start"], offset)
            decoded = data[offset : record["byte_end"]].decode("utf-16-le")
            self.assertEqual(decoded.rstrip("\r\n"), record["literal"])
            offset = record["byte_end"]
        self.assertEqual(offset, len(data))
        for item in doc["assignments"]:
            self.assertEqual(
                data[item["value_byte_start"] : item["value_byte_end"]].decode("utf-16-le"), item["value_raw"]
            )
        self.assertEqual([a["value_raw"] for a in doc["assignments"]], ["12", '"💎 { }"'])
        self.assertTrue(all(a["plain_stats_scope"] for a in doc["assignments"]))

    def test_repeated_blocks_keys_and_conditional_scopes_do_not_merge(self):
        doc = parse(
            "Metadata/Character.ot",
            'extends "nothing"\nStats\n{\n x = 1\n x = -2\n Client\n {\n x = 3\n }\n}\nStats\n{\n x = 4\n}\n',
        )
        items = doc["assignments"]
        self.assertEqual([a["value_raw"] for a in items], ["1", "-2", "3", "4"])
        self.assertEqual([a["plain_stats_scope"] for a in items], [True, True, False, True])
        self.assertNotEqual(items[0]["scope"][0]["id"], items[3]["scope"][0]["id"])
        self.assertEqual([b["name_raw"] for b in items[2]["scope"]], ["Stats", "Client"])

    def test_comments_strings_and_opaque_inline_statements_stay_lexical(self):
        doc = parse(
            "Metadata/Character.ot",
            'extends "nothing"\nStats\n{\n text = "https://example/{value}" // } {\n}\nUnknown if_flag { x = 99 }\n',
        )
        self.assertEqual(doc["assignments"][0]["value_raw"], '"https://example/{value}"')
        self.assertEqual(len(doc["assignments"]), 1)
        self.assertTrue(any(x["code"] == "opaque_block_name" for x in doc["diagnostics"]))
        self.assertEqual(doc["records"][-1]["literal"], "Unknown if_flag { x = 99 }")

    def test_numeric_assignment_tokens_are_not_interpreted(self):
        doc = parse(
            "Metadata/Character.ot",
            'extends "nothing"\nStats\n{\n a = +001\n b = -1.25e-3\n c = 0xFF\n d = opaque_token\n}\n',
        )
        self.assertEqual([a["value_raw"] for a in doc["assignments"]], ["+001", "-1.25e-3", "0xFF", "opaque_token"])
        self.assertEqual(doc["merge_policy"], "none; ordered lexical records only")

    def test_ao_chain_never_invents_ot_inheritance(self):
        files = {
            "Metadata/Actor.ao": parse("Metadata/Actor.ao", 'extends "Metadata/Character"\n'),
            "Metadata/Character.ao": parse("Metadata/Character.ao", 'extends "nothing"\n'),
            "Metadata/Character.ot": parse(
                "Metadata/Character.ot", 'extends "nothing"\nStats\n{\n critical_bonus = 100\n}\n'
            ),
        }
        self.assertEqual(files["Metadata/Actor.ao"]["extends"][0]["target"], "Metadata/Character.ao")
        self.assertEqual(
            validate_closure(files, ["Metadata/Actor.ao", "Metadata/Character.ot"]),
            {"Metadata/Actor.ao": 1, "Metadata/Character.ot": 0},
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_closure(files, ["Metadata/Actor.ao"])

    def test_missing_cyclic_and_overdeep_parent_chains_reject(self):
        files = {"Metadata/A.ao": parse("Metadata/A.ao", 'extends "Metadata/B"\n')}
        with self.assertRaisesRegex(ValueError, "Missing"):
            validate_closure(files, ["Metadata/A.ao"])
        files["Metadata/B.ao"] = parse("Metadata/B.ao", 'extends "Metadata/A"\n')
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            validate_closure(files, ["Metadata/A.ao"])
        for edges in [16, 17]:
            files = {
                f"Metadata/F{i}.ao": parse(
                    f"Metadata/F{i}.ao", f'extends "Metadata/F{i + 1}"\n' if i < edges else 'extends "nothing"\n'
                )
                for i in range(edges + 1)
            }
            if edges == 16:
                self.assertEqual(validate_closure(files, ["Metadata/F0.ao"])["Metadata/F0.ao"], 16)
            else:
                with self.assertRaisesRegex(ValueError, "depth"):
                    validate_closure(files, ["Metadata/F0.ao"])

    def test_resource_and_lexical_failures_are_not_silently_repaired(self):
        for path in [
            "Metadata/../x.ot",
            "Metadata//x.ot",
            "Metadata/x.txt",
            "Metadata/x\\y.ao",
            "Metadata/x:1.ot",
            "/Metadata/x.ot",
        ]:
            with self.assertRaises(ValueError):
                resource_path(path)
        for text in [
            "Stats\n{\n}",
            'extends "nothing"\nextends "nothing"',
            "extends nothing",
            'extends "nothing"\n}',
            'extends "nothing"\nStats\n{',
            'extends "nothing"\ntext = "unterminated',
            'extends "nothing"\n/* { */',
        ]:
            with self.assertRaises(ValueError, msg=text):
                parse("Metadata/Test.ot", text)
        for data in [b"", b"extends", b"\xff\xfe\x00"]:
            with self.assertRaises(ValueError):
                parse_metadata("Metadata/Test.ot", data)

    def test_block_depth_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "depth"):
            parse("Metadata/Test.ot", 'extends "nothing"\n' + "Nested\n{\n" * 33 + "}\n" * 33)
