"""Le distribuzioni Python installate e la loro licenza, in CSV su stdout.

Si lancia con l'interprete da ispezionare — quello dell'immagine, o un venv con
le sole dipendenze di produzione — e usa solo la libreria standard: niente da
installare, niente rete.

La licenza si prende, nell'ordine, da dove è più precisa: l'espressione SPDX
(`License-Expression`, PEP 639), poi i classificatori «License ::», poi il
campo `License` se è una sigla e non il testo intero della licenza.
"""

import csv
import sys
from importlib.metadata import distributions


def licenza(meta) -> str:
    espressione = (meta.get("License-Expression") or "").strip()
    if espressione:
        return espressione
    classificatori = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::") and c.strip() != "License :: OSI Approved"
    ]
    if classificatori:
        return "; ".join(dict.fromkeys(classificatori))
    testo = (meta.get("License") or "").strip()
    if testo and "\n" not in testo and len(testo) <= 80 and testo.upper() != "UNKNOWN":
        return testo
    return "SCONOSCIUTA"


righe = {}
for dist in distributions():
    nome = dist.metadata["Name"]
    if nome and nome.lower() not in righe:
        righe[nome.lower()] = [nome, dist.version, licenza(dist.metadata), "python"]

scrittore = csv.writer(sys.stdout, lineterminator="\n")
for chiave in sorted(righe):
    scrittore.writerow(righe[chiave])
