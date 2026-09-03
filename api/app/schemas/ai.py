from typing import Any

from pydantic import BaseModel


class ModelloRequest(BaseModel):
    modello: str
    # `text` legge il testo dell'OCR, `vision` guarda l'immagine: la seconda
    # vuole un modello multimodale e molta più memoria.
    modalita: str | None = None


class StatoAiResponse(BaseModel):
    attiva: bool
    modello_in_uso: str
    modalita: str
    ollama_raggiungibile: bool
    indirizzo_ollama: str
    modelli: list[dict[str, Any]]
    # I tempi delle letture vere, non le promesse del modello: è il numero che
    # dice se conviene cambiare sul ferro che c'è.
    tempi: list[dict[str, Any]]
