"""cp04: BUILDFLOW_SKILL_SRC en wat er gebeurt als de skillbron ontbreekt."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.check_site import ROOT
from tests import check_facts


class Skillbron(unittest.TestCase):
    def test_variabele_bepaalt_de_map(self):
        map_ = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, map_)
        for naam in ("SKILL.md", "README.md"):
            with open(os.path.join(map_, naam), "w", encoding="utf-8") as f:
                f.write("---\nname: buildflow\n---\n")
        with mock.patch.dict(os.environ, {"BUILDFLOW_SKILL_SRC": map_}):
            self.assertEqual(os.path.realpath(check_facts.skill_bron()), os.path.realpath(map_))

    def test_standaard_naast_de_repo(self):
        env = {k: v for k, v in os.environ.items() if k != "BUILDFLOW_SKILL_SRC"}
        with mock.patch.dict(os.environ, env, clear=True):
            verwacht = os.path.join(os.path.dirname(ROOT), "skill-buildflow", "skills", "buildflow")
            self.assertEqual(os.path.normpath(check_facts.skill_bron()), os.path.normpath(verwacht))

    def test_ontbrekende_bron_faalt_duidelijk(self):
        weg = os.path.join(tempfile.gettempdir(), "bestaat-niet-buildflow-cp04")
        env = dict(os.environ, BUILDFLOW_SKILL_SRC=weg)
        uit = subprocess.run([sys.executable, "-m", "unittest", "tests.test_cp04_feiten"],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        tekst = uit.stdout + uit.stderr
        self.assertNotEqual(uit.returncode, 0, tekst)
        self.assertIn(weg, tekst)
        self.assertIn("BUILDFLOW_SKILL_SRC", tekst)
        self.assertIn("README.md", tekst, "melding verwijst niet naar de README")
        self.assertIn("../skill-buildflow/skills/buildflow", tekst, "standaardpad ontbreekt")
        self.assertNotIn("skipped", tekst.lower())


if __name__ == "__main__":
    unittest.main()
