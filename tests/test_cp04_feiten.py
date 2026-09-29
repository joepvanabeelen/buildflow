"""cp04: de installatie-instructies op de pagina kloppen met de skill zelf.

De skillbron staat in BUILDFLOW_SKILL_SRC, standaard ../skill-buildflow/skills/buildflow
naast deze repo. Ontbreekt die, dan falen deze tests met een duidelijke melding.
"""
import os
import re
import unittest

from tests.check_site import INDEX, Pagina, lees
from tests import check_facts


class Feiten(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bron = check_facts.skill_bron()
        if not os.path.isdir(cls.bron):
            raise AssertionError(check_facts.melding_ontbrekende_bron(cls.bron))
        cls.html = lees(INDEX)
        cls.pagina = Pagina(cls.html)
        cls.code = [el.alle_tekst() for el in cls.pagina.elementen() if el.tag == "code"]

    def test_hookregel_zoekt_op_beide_plekken(self):
        commandos = check_facts.hook_commandos(lees(os.path.join(self.bron, "SKILL.md")))
        self.assertTrue(commandos, "geen hook-commando's in de frontmatter gevonden")
        for cmd in commandos:
            self.assertIn("$HOME/.claude/skills/buildflow", cmd)
            self.assertIn("$CLAUDE_PROJECT_DIR/.claude/skills/buildflow", cmd)

    def test_paden_op_de_pagina_volgen_de_hookregel(self):
        cmd = check_facts.hook_commandos(lees(os.path.join(self.bron, "SKILL.md")))[0]
        thuis = re.search(r"\$HOME/(\.claude/skills/buildflow)", cmd).group(1)
        project = re.search(r"\$CLAUDE_PROJECT_DIR/(\.claude/skills/buildflow)", cmd).group(1)
        self.assertIn("~/" + thuis, self.html)
        self.assertRegex(self.html, r"(?<![~/\w])" + re.escape(project),
                         "projectpad .claude/skills/buildflow staat niet op de pagina")
        self.assertTrue(any("unzip -o buildflow.zip -d ~/.claude/skills" in c for c in self.code),
                        "uitpakcommando voor de homemap ontbreekt in de codeblokken")
        # De skill-mappen die de controle verwacht, volgen uit de hookregel.
        self.assertEqual(check_facts.HOME_SKILLS + "/buildflow", "~/" + thuis)
        self.assertEqual(check_facts.PROJECT_SKILLS + "/buildflow", project)

    def test_elk_installatiecommando_klopt_op_zijn_eigen_plek(self):
        meldingen = check_facts.controleer_installatie(self.pagina)
        self.assertEqual(meldingen, [], "\n".join(meldingen))

    def test_volgorde_van_de_hook_op_de_pagina_gelijk_aan_skill(self):
        cmds = check_facts.hook_commandos(lees(os.path.join(self.bron, "SKILL.md")))
        volgordes = {tuple(check_facts.hook_volgorde(c)) for c in cmds}
        self.assertEqual(len(volgordes), 1, f"hookregels verschillen in volgorde: {volgordes}")
        skill = list(volgordes.pop())
        self.assertEqual(sorted(skill), ["home", "project"])
        self.assertEqual(check_facts.pagina_volgorde(self.pagina), skill)

    def test_python_eis_gelijk_aan_readme(self):
        eis = check_facts.python_eis(lees(os.path.join(self.bron, "README.md")))
        self.assertRegex(eis, r"^3\.\d+$")
        tekst = self.pagina.root.alle_tekst()
        op_pagina = set(re.findall(r"Python\s+(3\.\d+)", tekst))
        self.assertEqual(op_pagina, {eis}, f"README zegt {eis}, pagina noemt {op_pagina}")

    def test_bijwerken_noemt_beide_installatieplekken(self):
        # open punt uit de review van cp01
        vraag = next((el for el in self.pagina.elementen() if el.tag == "details"
                      and "Hoe werk ik bij" in el.alle_tekst()), None)
        self.assertIsNotNone(vraag, "FAQ 'Hoe werk ik bij' ontbreekt")
        tekst = vraag.alle_tekst()
        self.assertIn("unzip -o buildflow.zip -d ~/.claude/skills", tekst)
        self.assertRegex(tekst, r"unzip -o buildflow\.zip -d \.claude/skills",
                         "bijwerken in het project (.claude/skills) ontbreekt")


def _pagina(html):
    return Pagina(html)


class ControleSlaatAan(unittest.TestCase):
    """Kopieën van index.html met één fout erin; de controle moet die vinden."""

    @classmethod
    def setUpClass(cls):
        cls.html = lees(INDEX)

    def vervang(self, oud, nieuw, n=1):
        self.assertEqual(self.html.count(oud), n, f"verwacht {n}x: {oud!r}")
        return self.html.replace(oud, nieuw)

    def meldingen(self, html):
        return check_facts.controleer_installatie(_pagina(html))

    def test_fout_uitpakcommando_in_stap_2(self):
        # De FAQ heeft het goede commando nog; dat mag stap 2 niet redden.
        oud = "mkdir -p ~/.claude/skills\nunzip -o buildflow.zip -d ~/.claude/skills</code>"
        html = self.vervang(oud, "mkdir -p ~/.claude/skills\nunzip -o buildflow.zip -d "
                            "~/.claude/skill</code>")
        m = self.meldingen(html)
        self.assertTrue(any("stap 2" in x for x in m), m)

    def test_fout_doctorpad_in_stap_3(self):
        html = self.vervang("<code>python3 ~/.claude/skills/buildflow/scripts/bf.py doctor",
                            "<code>python3 ~/.claude/buildflow/scripts/bf.py doctor")
        self.assertTrue(any("stap 3" in x for x in self.meldingen(html)))

    def test_fout_uitpakcommando_in_teamblok(self):
        oud = "mkdir -p .claude/skills\nunzip -o buildflow.zip -d .claude/skills\nrm buildflow.zip"
        html = self.vervang(oud, "mkdir -p .claude/skills\nunzip -o buildflow.zip -d "
                            ".claude\nrm buildflow.zip")
        m = self.meldingen(html)
        self.assertTrue(any("teamblok" in x for x in m), m)

    def test_uitpakken_naar_homemap_in_teamblok(self):
        oud = "mkdir -p .claude/skills\nunzip -o buildflow.zip -d .claude/skills\nrm buildflow.zip"
        html = self.vervang(oud, "mkdir -p .claude/skills\nunzip -o buildflow.zip -d "
                            "~/.claude/skills\nrm buildflow.zip")
        self.assertTrue(any("teamblok" in x for x in self.meldingen(html)))

    def test_fout_commando_in_faq_projectblok(self):
        oud = "rm -rf .claude/skills/buildflow\nunzip -o buildflow.zip -d .claude/skills</code>"
        html = self.vervang(oud, "rm -rf .claude/skills/buildflow\nunzip -o buildflow.zip -d "
                            "~/.claude/skills</code>")
        self.assertTrue(any("FAQ" in x for x in self.meldingen(html)))

    def test_fout_commando_in_faq_homeblok(self):
        oud = "rm -rf ~/.claude/skills/buildflow\nunzip"
        html = self.vervang(oud, "rm -rf ~/.claude/buildflow\nunzip")
        self.assertTrue(any("FAQ" in x for x in self.meldingen(html)))

    def test_omgedraaide_volgorde_op_de_pagina(self):
        oud = ("kijkt eerst in <code>~/.claude/skills/buildflow</code> en daarna in "
               "<code>.claude/skills/buildflow</code>")
        html = self.vervang(oud, "kijkt eerst in <code>.claude/skills/buildflow</code> van het "
                            "project en daarna in <code>~/.claude/skills/buildflow</code>")
        self.assertEqual(check_facts.pagina_volgorde(_pagina(html)), ["project", "home"])

    def test_zin_zonder_volgorde(self):
        html = self.vervang("kijkt eerst in", "kijkt in")
        with self.assertRaises(ValueError):
            check_facts.pagina_volgorde(_pagina(html))

    def test_omgedraaide_volgorde_in_de_skill(self):
        cmd = ('f="$CLAUDE_PROJECT_DIR/.claude/skills/buildflow/scripts/gate_hook.py"; '
               '[ -f "$f" ] || f="$HOME/.claude/skills/buildflow/scripts/gate_hook.py"; '
               '[ -f "$f" ] || exit 0; exec python3 "$f"')
        self.assertEqual(check_facts.hook_volgorde(cmd), ["project", "home"])
        self.assertNotEqual(check_facts.hook_volgorde(cmd),
                            check_facts.pagina_volgorde(_pagina(self.html)))

    def test_hookregel_met_andere_vorm(self):
        with self.assertRaises(ValueError):
            check_facts.hook_volgorde('exec python3 "$HOME/.claude/skills/buildflow/x.py"')


class Uitlezen(unittest.TestCase):
    """De leesfuncties zelf, los van de echte skillbron."""

    def test_hook_commandos_uit_frontmatter(self):
        skill = ("---\nname: x\nhooks:\n  Stop:\n    - hooks:\n        - type: command\n"
                 "          command: 'f=\"$HOME/a\"; exec python3 \"$f\"'\n---\n\n"
                 "command: 'niet in de frontmatter'\n")
        self.assertEqual(check_facts.hook_commandos(skill), ['f="$HOME/a"; exec python3 "$f"'])

    def test_python_eis_uit_readme(self):
        self.assertEqual(check_facts.python_eis("Vereisten: Python 3.11+ en git."), "3.11")


if __name__ == "__main__":
    unittest.main()
