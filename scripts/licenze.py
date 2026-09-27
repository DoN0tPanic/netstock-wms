#!/usr/bin/env python3
"""Inventario delle licenze e controllo che siano tutte ammesse.

Tre fonti, messe in un solo elenco:

- i pacchetti Python, dal CSV di `scripts/licenze_python.py`, che gira con
  l'interprete da ispezionare: l'immagine dell'API in locale, un ambiente con le
  sole dipendenze di produzione in CI;
- i pacchetti npm, letti dai `package.json` di `web/node_modules`, annidati
  compresi;
- i componenti che non stanno in nessun gestore di pacchetti — immagini, motore
  OCR, modello — con le versioni lette da compose e Dockerfile.

Poi controlla quattro cose, e fallisce se una non torna:

1. ogni licenza è in `compliance/allowed-licenses.txt`, oppure ha
   un'eccezione motivata in `compliance/eccezioni-licenze.txt` per quella
   dichiarazione esatta — se il pacchetto cambia licenza, l'eccezione decade;
2. ogni componente installato compare nell'inventario pubblicato
   (`compliance/licenses.csv`), che quindi non può invecchiare in silenzio;
3. le licenze dell'inventario pubblicato sono anch'esse ammesse;
4. la premessa dell'ADR 0006 regge: nessun video aperto con OpenCV, quindi il
   FFmpeg (LGPL) che il suo pacchetto si porta dietro resta peso morto.

Uso:
  scripts/licenze.py --python-csv FILE            controlla, senza cambiare file
  scripts/licenze.py --python-csv FILE --scrivi   rigenera l'inventario, poi controlla
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
AMMESSE = RADICE / "compliance/allowed-licenses.txt"
ECCEZIONI = RADICE / "compliance/eccezioni-licenze.txt"
INVENTARIO = RADICE / "compliance/licenses.csv"
INTESTAZIONE = ["componente", "versione", "licenza", "origine"]

# Come i pacchetti scrivono le licenze nei metadati, ricondotto al nome SPDX.
# I classificatori Python («MIT License», «BSD License») sono nomi, non sigle.
SINONIMI = {
    "mit license": "MIT",
    "expat": "MIT",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "bsd license": "BSD",
    "new bsd license": "BSD-3-Clause",
    "simplified bsd license": "BSD-2-Clause",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "python software foundation license": "PSF-2.0",
    "psf": "PSF-2.0",
    "postgresql license": "PostgreSQL",
    "the unlicense": "Unlicense",
    "the unlicense (unlicense)": "Unlicense",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "cc0 1.0 universal": "CC0-1.0",
}

# La licenza di un modello non sta in nessun metadato che si possa leggere da
# qui: la si dichiara per famiglia, e un modello di una famiglia non elencata
# risulta SCONOSCIUTA — cioè il controllo fallisce finché qualcuno non guarda.
# Le scelte e i divieti sono nell'ADR 0005.
MODELLI = {
    "qwen3": "Apache-2.0",
    "phi4-mini": "MIT",
    "granite3": "Apache-2.0",
}


def licenza_modello(modello: str) -> str:
    famiglia = modello.split(":")[0].lower()
    return next((lic for pref, lic in MODELLI.items() if famiglia.startswith(pref)), "SCONOSCIUTA")


def canonica(nome: str) -> str:
    nome = nome.strip()
    return SINONIMI.get(nome.lower(), nome).lower()


def leggi_ammesse() -> set[str]:
    righe = AMMESSE.read_text(encoding="utf-8").splitlines()
    return {canonica(r) for r in righe if r.strip() and not r.lstrip().startswith("#")}


def leggi_eccezioni() -> dict[tuple[str, str], str]:
    eccezioni = {}
    for riga in ECCEZIONI.read_text(encoding="utf-8").splitlines():
        if not riga.strip() or riga.lstrip().startswith("#"):
            continue
        componente, licenza, motivo = (parte.strip() for parte in riga.split("|", 2))
        eccezioni[(componente.lower(), licenza)] = motivo
    return eccezioni


def _parentesi_esterne(testo: str) -> bool:
    """Vero se la prima parentesi si chiude proprio alla fine del testo."""
    livello = 0
    for i, carattere in enumerate(testo):
        livello += {"(": 1, ")": -1}.get(carattere, 0)
        if livello == 0:
            return i == len(testo) - 1
    return False


def _spdx(testo: str, ammesse: set[str]) -> bool:
    """Un'espressione SPDX: OR basta un'alternativa ammessa, AND le vuole tutte.

    `WITH` introduce un'eccezione alla licenza, che aggiunge permessi e non ne
    toglie: conta la licenza che la precede.
    """
    token = re.findall(r"\(|\)|[^\s()]+", testo)
    pos = 0

    def espressione() -> bool:
        nonlocal pos
        valori = [termine()]
        while pos < len(token) and token[pos].upper() == "OR":
            pos += 1
            valori.append(termine())
        return any(valori)

    def termine() -> bool:
        nonlocal pos
        valori = [fattore()]
        while pos < len(token) and token[pos].upper() == "AND":
            pos += 1
            valori.append(fattore())
        return all(valori)

    def fattore() -> bool:
        nonlocal pos
        if token[pos] == "(":
            pos += 1
            valore = espressione()
            if token[pos] != ")":
                raise ValueError("parentesi non chiusa")
            pos += 1
            return valore
        nome = token[pos]
        pos += 1
        if pos < len(token) and token[pos].upper() == "WITH":
            pos += 2
        return canonica(nome) in ammesse

    try:
        valore = espressione()
    except (IndexError, ValueError):
        return False
    return valore and pos == len(token)


def ammessa(dichiarata: str, ammesse: set[str]) -> bool:
    testo = dichiarata.strip()
    while testo.startswith("(") and _parentesi_esterne(testo):
        testo = testo[1:-1].strip()
    if canonica(testo) in ammesse:
        return True
    if re.search(r"\s(OR|AND|WITH)\s|\(", testo):
        return _spdx(testo, ammesse)
    # Più classificatori, o un elenco libero: si pretende che ogni parte sia
    # ammessa. È la lettura prudente — per un doppio licenziamento basterebbe
    # una — e con licenze tutte permissive non costa niente.
    if ";" in testo or "," in testo:
        parti = [p for p in re.split(r"[;,]", testo) if p.strip()]
        return all(ammessa(p, ammesse) for p in parti)
    return False


def pacchetti_python(file: Path) -> list[list[str]]:
    progetto = re.search(
        r'^name\s*=\s*"([^"]+)"', (RADICE / "api/pyproject.toml").read_text(), re.M
    ).group(1)
    with file.open(newline="", encoding="utf-8") as f:
        # NetStock stesso compare fra i componenti fissi, con la sua licenza.
        return [r for r in csv.reader(f) if r and r[0].lower() != progetto.lower()]


def pacchetti_npm() -> list[list[str]]:
    cartella = RADICE / "web/node_modules"
    if not cartella.is_dir():
        sys.exit("web/node_modules non c'è: prima `npm ci` in web/.")
    righe: dict[tuple[str, str], list[str]] = {}

    def visita(percorso: Path) -> None:
        try:
            voci = sorted(os.scandir(percorso), key=lambda v: v.name)
        except FileNotFoundError:
            return
        for voce in voci:
            if not voce.is_dir() or voce.name.startswith("."):
                continue
            if voce.name.startswith("@"):
                visita(Path(voce.path))
                continue
            try:
                manifesto = json.loads((Path(voce.path) / "package.json").read_text())
            except (OSError, ValueError):
                continue
            licenza = manifesto.get("license")
            if isinstance(licenza, dict):
                licenza = licenza.get("type")
            vecchio_formato = manifesto.get("licenses")
            if not licenza and isinstance(vecchio_formato, list):
                tipi = [str(x.get("type")) for x in vecchio_formato if isinstance(x, dict)]
                licenza = " OR ".join(t for t in tipi if t and t != "None")
            nome = manifesto.get("name") or voce.name
            versione = manifesto.get("version") or ""
            righe[(nome, versione)] = [nome, versione, (licenza or "SCONOSCIUTA").strip(), "npm"]
            visita(Path(voce.path) / "node_modules")

    visita(cartella)
    return sorted(righe.values(), key=lambda r: (r[0].lower(), r[1]))


def componenti_fissi() -> list[list[str]]:
    compose = (RADICE / "docker-compose.yml").read_text()
    web = (RADICE / "web/Dockerfile").read_text()
    api = (RADICE / "api/Dockerfile").read_text()
    pyproject = (RADICE / "api/pyproject.toml").read_text()

    def etichetta(testo: str, immagine: str) -> str:
        trovata = re.search(rf"(?<![\w/-]){re.escape(immagine)}:([\w.-]+)", testo)
        return trovata.group(1) if trovata else "?"

    trovato = re.search(r"EXTRACT_MODEL:-([^}\s]+)", compose)
    modello = trovato.group(1) if trovato else "?"
    versione = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
    return [
        ["netstock", versione, "MIT", "progetto"],
        ["postgres", etichetta(compose, "postgres"), "PostgreSQL", "immagine"],
        ["caddy", etichetta(compose, "caddy"), "Apache-2.0", "immagine"],
        ["nginx", etichetta(web, "nginx"), "BSD-2-Clause", "immagine"],
        ["ollama", etichetta(compose, "ollama/ollama"), "MIT", "immagine"],
        ["python (interprete dell'immagine API)", etichetta(api, "python"), "PSF-2.0", "immagine"],
        [
            "debian (base dell'immagine API)",
            etichetta(api, "python"),
            "misto (vedi compliance/LICENZE.md)",
            "immagine",
        ],
        ["tesseract-ocr", "5.x", "Apache-2.0", "pacchetto di sistema"],
        ["postgresql-client", "16", "PostgreSQL", "pacchetto di sistema"],
        [modello, "—", licenza_modello(modello), "modello"],
    ]


def video_con_opencv() -> list[str]:
    return sorted(
        str(p.relative_to(RADICE))
        for p in (RADICE / "api/app").rglob("*.py")
        if re.search(r"\bVideo(Capture|Writer)\b", p.read_text(encoding="utf-8", errors="ignore"))
    )


def leggi_inventario() -> list[list[str]]:
    with INVENTARIO.open(newline="", encoding="utf-8") as f:
        righe = list(csv.reader(f))
    return [r for r in righe[1:] if r]


def fuori_elenco(righe, ammesse, eccezioni) -> tuple[list[list[str]], list[list[str]]]:
    vietate, eccezionali = [], []
    for riga in righe:
        nome, _, licenza, _ = riga
        if ammessa(licenza, ammesse):
            continue
        (eccezionali if (nome.lower(), licenza) in eccezioni else vietate).append(riga)
    return vietate, eccezionali


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python-csv", type=Path, required=True)
    parser.add_argument("--scrivi", action="store_true", help="rigenera compliance/licenses.csv")
    argomenti = parser.parse_args()

    ammesse, eccezioni = leggi_ammesse(), leggi_eccezioni()
    installati = pacchetti_python(argomenti.python_csv) + pacchetti_npm() + componenti_fissi()
    if argomenti.scrivi:
        with INVENTARIO.open("w", newline="", encoding="utf-8") as f:
            scrittore = csv.writer(f, lineterminator="\n")
            scrittore.writerow(INTESTAZIONE)
            scrittore.writerows(installati)
        print(f"Scritto {INVENTARIO.relative_to(RADICE)}: {len(installati)} componenti.")

    problemi = 0
    per_origine: dict[str, int] = {}
    for riga in installati:
        per_origine[riga[3]] = per_origine.get(riga[3], 0) + 1
    print(
        f"Licenze: {len(installati)} componenti ("
        + ", ".join(f"{n} {o}" for o, n in per_origine.items())
        + ")"
    )

    vietate, eccezionali = fuori_elenco(installati, ammesse, eccezioni)
    if vietate:
        problemi += 1
        print("  ✗ licenze non ammesse e senza eccezione motivata:")
        for nome, versione, licenza, origine in vietate:
            print(f"      {origine:>8}  {nome} {versione}: «{licenza}»")
        print("    Si sostituisce il componente, oppure si decide per iscritto: la licenza in")
        print("    compliance/allowed-licenses.txt, o un'eccezione in")
        print("    compliance/eccezioni-licenze.txt.")
    else:
        print("  ✓ tutte ammesse" + (f" ({len(eccezionali)} con eccezione motivata: "
              + ", ".join(r[0] for r in eccezionali) + ")" if eccezionali else ""))

    pubblicato = leggi_inventario()
    elencati = {(r[3], r[0].lower()) for r in pubblicato}
    mancanti = [r for r in installati if (r[3], r[0].lower()) not in elencati]
    if mancanti:
        problemi += 1
        print(f"  ✗ installati ma assenti da compliance/licenses.csv ({len(mancanti)}):")
        for nome, versione, licenza, origine in mancanti[:20]:
            print(f"      {origine:>8}  {nome} {versione}: «{licenza}»")
        print("    Rigenera l'inventario con `make licenses` e committalo.")
    else:
        print("  ✓ l'inventario pubblicato elenca tutto ciò che è installato")

    vietate_pubblicate, _ = fuori_elenco(pubblicato, ammesse, eccezioni)
    if vietate_pubblicate:
        problemi += 1
        print(f"  ✗ licenze non ammesse nell'inventario pubblicato ({len(vietate_pubblicate)}):")
        for nome, versione, licenza, origine in vietate_pubblicate[:20]:
            print(f"      {origine:>8}  {nome} {versione}: «{licenza}»")
    video = video_con_opencv()
    if video:
        problemi += 1
        print("  ✗ OpenCV apre video in: " + ", ".join(video))
        print("    L'ADR 0006 ammette il FFmpeg (LGPL) dentro OpenCV solo perché nessun")
        print("    percorso del codice lo usa: con questo, va rivista la decisione.")
    else:
        print("  ✓ premessa dell'ADR 0006: nessun video aperto con OpenCV")
    return 1 if problemi else 0


if __name__ == "__main__":
    sys.exit(main())
