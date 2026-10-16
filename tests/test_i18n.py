import json
import re
import unittest
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "frontend" / "static" / "i18n"
load = lambda n: json.loads((D / f"{n}.json").read_text(encoding="utf-8"))
ph = lambda s: sorted(re.findall(r"\{(\w+)\}", s))


class I18nTests(unittest.TestCase):
    def test_amharic_is_complete(self):
        en, am = load("en"), load("am")
        self.assertEqual(sorted(set(en) - set(am)), [])
        self.assertEqual(sorted(set(am) - set(en)), [])

    def test_draft_locales_only_use_known_keys(self):
        en = load("en")
        for code in ("om", "ti"):
            self.assertEqual(sorted(set(load(code)) - set(en)), [], code)

    def test_placeholders_match_and_nothing_empty(self):
        en = load("en")
        for code in ("am", "om", "ti"):
            for k, v in load(code).items():
                self.assertTrue(v.strip(), (code, k))
                self.assertEqual(ph(v), ph(en[k]), (code, k))

    def test_index_lists_every_file_and_marks_drafts(self):
        idx = {e["code"]: e for e in json.loads((D / "index.json").read_text(encoding="utf-8"))}
        self.assertEqual(set(idx), {"en", "am", "om", "ti"})
        self.assertTrue(idx["om"]["draft"] and idx["ti"]["draft"])
        self.assertFalse(idx["am"]["draft"])

    def test_amharic_actually_contains_ethiopic_script(self):
        am = load("am")
        ethiopic = sum(1 for v in am.values() if re.search(r"[\u1200-\u137F]", v))
        self.assertGreaterEqual(ethiopic, len(am) * 0.95)


if __name__ == "__main__":
    unittest.main()
