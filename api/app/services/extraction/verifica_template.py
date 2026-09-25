"""Un template IA si controlla quando si salva, non quando si legge una bolla.

Il campo `field_specs` era un dizionario qualsiasi: si salvava tutto. Un
template con la struttura sbagliata, o con un'espressione regolare che non
compila, veniva accettato senza una parola — e poi, alla prima etichetta, non
trovava niente. Chi era al banco concludeva che la lettura automatica non
funzionasse; chi aveva scritto il template non lo scopriva mai. Il beta test
ne ha salvati due così, e la prova sul template rispondeva «tutto bene».

Qui si controlla la forma che la pipeline legge davvero
(`templates._field_specs_from_dict`), e si compila ogni regex. Le chiavi
sconosciute si rifiutano: `regx` al posto di `regex` è esattamente il genere
di errore che altrimenti passa in silenzio.
"""

import re
from typing import Any

_CHIAVI_CIMA = {"fields", "llm_instructions"}
_CHIAVI_CAMPO = {
    "name",
    "target",
    "regex",
    "keywords",
    "keyword_window",
    "barcode_formats",
    "match_against_catalog",
    "ocr_fixes",
    "required",
}
_BOOLEANI = ("match_against_catalog", "ocr_fixes", "required")
_ELENCHI = ("keywords", "barcode_formats")


def verifica_field_specs(specifiche: Any) -> dict[str, Any]:
    """Restituisce le specifiche se sono valide; altrimenti `ValueError` in italiano."""
    if not isinstance(specifiche, dict):
        raise ValueError(
            "Le specifiche del template devono essere un oggetto con l'elenco «fields»."
        )
    ignote = set(specifiche) - _CHIAVI_CIMA
    if ignote:
        raise ValueError(
            f"Chiavi non riconosciute: {', '.join(sorted(ignote))}. "
            f"Sono ammesse: {', '.join(sorted(_CHIAVI_CIMA))}."
        )
    campi = specifiche.get("fields")
    if not isinstance(campi, list) or not campi:
        raise ValueError("Il template deve avere almeno un campo in «fields».")
    istruzioni = specifiche.get("llm_instructions")
    if istruzioni is not None and not isinstance(istruzioni, str):
        raise ValueError("«llm_instructions» deve essere un testo.")

    nomi: set[str] = set()
    for posizione, campo in enumerate(campi, start=1):
        dove = f"Campo {posizione}"
        if not isinstance(campo, dict):
            raise ValueError(f"{dove}: deve essere un oggetto.")
        nome = campo.get("name")
        if not isinstance(nome, str) or not nome.strip():
            raise ValueError(f"{dove}: manca il nome («name»).")
        dove = f"Campo «{nome}»"
        if nome in nomi:
            raise ValueError(f"{dove}: il nome compare due volte.")
        nomi.add(nome)
        ignote = set(campo) - _CHIAVI_CAMPO
        if ignote:
            raise ValueError(
                f"{dove}: chiavi non riconosciute: {', '.join(sorted(ignote))}. "
                f"Sono ammesse: {', '.join(sorted(_CHIAVI_CAMPO))}."
            )
        regex = campo.get("regex")
        if regex is not None:
            if not isinstance(regex, str) or not regex:
                raise ValueError(f"{dove}: «regex» deve essere un'espressione non vuota.")
            try:
                re.compile(regex)
            except re.error as errore:
                raise ValueError(
                    f"{dove}: l'espressione regolare non è valida ({errore})."
                ) from errore
        for chiave in _ELENCHI:
            valore = campo.get(chiave)
            if valore is not None and (
                not isinstance(valore, list) or not all(isinstance(v, str) for v in valore)
            ):
                raise ValueError(f"{dove}: «{chiave}» deve essere un elenco di testi.")
        for chiave in _BOOLEANI:
            valore = campo.get(chiave)
            if valore is not None and not isinstance(valore, bool):
                raise ValueError(f"{dove}: «{chiave}» deve essere vero o falso.")
        finestra = campo.get("keyword_window")
        if finestra is not None and (
            isinstance(finestra, bool) or not isinstance(finestra, int) or finestra <= 0
        ):
            raise ValueError(f"{dove}: «keyword_window» deve essere un numero intero positivo.")
        destinazione = campo.get("target")
        if destinazione is not None and (not isinstance(destinazione, str) or not destinazione):
            raise ValueError(f"{dove}: «target» deve essere un testo.")
    return specifiche
