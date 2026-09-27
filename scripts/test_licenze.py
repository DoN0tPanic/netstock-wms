"""Il controllo delle licenze si vede fallire, non solo passare.

Si lancia con la sola libreria standard:  python3 -m unittest scripts/test_licenze.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import licenze  # noqa: E402

AMMESSE = licenze.leggi_ammesse()


class LicenzeAmmesse(unittest.TestCase):
    def test_permissive_scritte_in_tutti_i_modi_in_cui_capitano(self):
        for dichiarata in [
            "MIT", "MIT License", "Apache Software License", "Apache License, Version 2.0",
            "BSD License", "ISC License (ISCL)", "The Unlicense (Unlicense)", "PSF-2.0",
            "Mozilla Public License 2.0 (MPL 2.0)", "(MIT OR CC0-1.0)", "MIT AND PSF-2.0",
            "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", "Apache-2.0 OR BSD-2-Clause",
            "Apache Software License; MIT License", "Apache-2.0 WITH LLVM-exception",
        ]:
            with self.subTest(dichiarata):
                self.assertTrue(licenze.ammessa(dichiarata, AMMESSE))

    def test_copyleft_forte_proprietarie_e_sconosciute_si_fermano(self):
        for dichiarata in [
            "GPL-3.0-only", "AGPL-3.0", "GNU General Public License v3 (GPLv3)", "SSPL-1.0",
            "LGPL-2.1-or-later", "MIT AND GPL-3.0", "GPL-2.0-only WITH Classpath-exception-2.0",
            "Other/Proprietary License", "SEE LICENSE IN LICENSE", "SCONOSCIUTA", "",
            "BSD-3-Clause, Apache-2.0, dependency licenses", "MIT OR", "(MIT",
        ]:
            with self.subTest(dichiarata):
                self.assertFalse(licenze.ammessa(dichiarata, AMMESSE))

    def test_basta_un_alternativa_ammessa(self):
        self.assertTrue(licenze.ammessa("GPL-3.0 OR MIT", AMMESSE))


class Eccezioni(unittest.TestCase):
    def test_valgono_solo_per_la_dichiarazione_esatta(self):
        eccezioni = {("pypdfium2", "BSD-3-Clause, Apache-2.0, dependency licenses"): "motivo"}
        righe = [
            ["pypdfium2", "5", "BSD-3-Clause, Apache-2.0, dependency licenses", "python"],
            ["pypdfium2", "6", "BSD-3-Clause, GPL-3.0, dependency licenses", "python"],
        ]
        vietate, eccezionali = licenze.fuori_elenco(righe, AMMESSE, eccezioni)
        self.assertEqual([r[1] for r in eccezionali], ["5"])
        self.assertEqual([r[1] for r in vietate], ["6"])


class Modello(unittest.TestCase):
    def test_famiglie_note_e_sconosciute(self):
        self.assertEqual(licenze.licenza_modello("qwen3:4b"), "Apache-2.0")
        self.assertEqual(licenze.licenza_modello("phi4-mini"), "MIT")
        self.assertEqual(licenze.licenza_modello("granite3.2-vision:2b"), "Apache-2.0")
        # Qwen2.5-VL ha una licenza che vieta l'uso commerciale (ADR 0005).
        self.assertEqual(licenze.licenza_modello("qwen2.5vl:3b"), "SCONOSCIUTA")
        self.assertEqual(licenze.licenza_modello("llama3.1:8b"), "SCONOSCIUTA")


class InventarioPubblicato(unittest.TestCase):
    def test_e_tutto_ammesso(self):
        vietate, _ = licenze.fuori_elenco(
            licenze.leggi_inventario(), AMMESSE, licenze.leggi_eccezioni()
        )
        self.assertEqual(vietate, [])


if __name__ == "__main__":
    unittest.main()
