"""Normalizzazione di ciò che l'operatore carica, prima della pipeline (§7.5).

Chi fotografa una bolla col telefono manda un JPEG; chi la riceve via mail dal
fornitore ha un PDF; uno scanner da ufficio produce spesso un TIFF multipagina.
Qui tutto diventa la stessa cosa — un elenco di pagine in PNG — così barcode,
OCR e modello a valle non sanno nemmeno da che formato si è partiti.

Vale anche qui la regola non negoziabile del ciclo di vita: si lavora in
memoria, non si scrive niente su disco, e i byte in ingresso non vengono mai
registrati né loggati.
"""

import io

import pypdfium2 as pdfium
from PIL import Image, ImageSequence

from app.exceptions import ValidationAppError

# Formati accettati in ingresso. HEIC resta fuori di proposito: il browser lo
# converte in JPEG prima di caricarlo, così non serve la dipendenza LGPL (§2.3).
IMAGE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "image/gif",
    }
)
PDF_MIME_TYPES = frozenset({"application/pdf"})
ALLOWED_MIME_TYPES = IMAGE_MIME_TYPES | PDF_MIME_TYPES

# Un PDF di bolla è testo vettoriale: renderizzarlo a 200 DPI dà caratteri più
# netti di qualsiasi fotografia, e resta leggero da elaborare.
_PDF_RENDER_SCALE = 200 / 72
_MAX_PAGES_PER_DOCUMENT = 10


def _pil_to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _pages_from_pdf(data: bytes) -> list[bytes]:
    document = pdfium.PdfDocument(io.BytesIO(data))
    try:
        page_count = min(len(document), _MAX_PAGES_PER_DOCUMENT)
        if page_count == 0:
            raise ValidationAppError("Il PDF non contiene pagine.")
        pages = []
        for index in range(page_count):
            page = document[index]
            bitmap = page.render(scale=_PDF_RENDER_SCALE, grayscale=False)
            pages.append(_pil_to_png(bitmap.to_pil()))
        return pages
    finally:
        # pypdfium2 tiene un handle nativo: senza close i byte del documento
        # restano vivi oltre la richiesta.
        document.close()


def _pages_from_image(data: bytes) -> list[bytes]:
    with Image.open(io.BytesIO(data)) as image:
        frames = list(ImageSequence.Iterator(image))
        if len(frames) <= 1:
            return [_pil_to_png(image)]
        # TIFF multipagina da scanner: ogni pagina è un fotogramma.
        return [_pil_to_png(frame) for frame in frames[:_MAX_PAGES_PER_DOCUMENT]]


def to_pages(data: bytes, content_type: str | None) -> list[bytes]:
    """Un file caricato → l'elenco delle sue pagine come PNG.

    Il tipo dichiarato dal browser è solo un indizio: si prova comunque ad
    aprire il contenuto, e se non è un documento leggibile si risponde con un
    messaggio utile invece di un errore di libreria.
    """
    normalized = (content_type or "").split(";")[0].strip().lower()

    if normalized in PDF_MIME_TYPES or data[:5] == b"%PDF-":
        try:
            return _pages_from_pdf(data)
        except ValidationAppError:
            raise
        except Exception as exc:
            raise ValidationAppError(
                "Il PDF non è leggibile: potrebbe essere protetto da password o danneggiato."
            ) from exc

    try:
        return _pages_from_image(data)
    except Exception as exc:
        raise ValidationAppError(
            f"Formato non supportato: {normalized or 'sconosciuto'}. "
            "Accettati JPEG, PNG, WebP, TIFF, BMP, GIF e PDF."
        ) from exc
