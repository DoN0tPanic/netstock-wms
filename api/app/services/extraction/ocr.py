"""OCR con preprocessing scelto in base al tipo di documento (§7.2 stadio 2).

Un'etichetta di apparato e la foto di una bolla A4 sono due problemi diversi e
vogliono due trattamenti opposti. L'etichetta è piccola, ad alto contrasto, con
poche righe: la binarizzazione adattiva la ripulisce. La bolla è un foglio
intero fotografato, con testo piccolo e sottile su carta grigiastra: la stessa
binarizzazione lo mangia.

Confrontati sulle due pagine di una bolla fotografata, sugli stessi valori di
riferimento per pagina — codici articolo, codici produttore, seriali:

    binarizzazione adattiva + psm 4   (vecchio)   sulla pagina peggiore, nessuno
    grigio + upscale 2x + psm 4       (nuovo)     quasi tutti, su entrambe

Dove il vecchio percorso non azzeccava *nemmeno un valore*, un codice prodotto
usciva con l'ultimo carattere sbagliato e un codice interno di sette caratteri
con due cifre sbagliate. Nessun modello a valle può recuperare un testo così:
per questo il preprocessing viene prima di tutto il resto.
"""

import io

import cv2
import numpy as np
import pytesseract
from PIL import Image

# Documenti a pagina intera: colonne da preservare, niente binarizzazione.
_PAGE_DOC_TYPES = frozenset({"delivery_note", "packing_list", "invoice"})

# Sotto questa soglia l'immagine viene ingrandita: Tesseract vuole caratteri
# alti almeno una trentina di pixel, e la foto di un A4 da telefono ci arriva
# solo se la si porta oltre i 2000 px sul lato lungo.
_MIN_LONG_SIDE = 2000
_MAX_LONG_SIDE = 4500


def _deskew_angle(gray: np.ndarray) -> float:
    """Angolo di inclinazione del testo, in gradi.

    L'angolo va calcolato su una maschera binaria: su un'immagine in scala di
    grigi quasi nessun pixel vale esattamente 255, quindi `findNonZero` di una
    foto restituisce praticamente tutti i pixel e il rettangolo minimo che ne
    esce è il fotogramma intero — un angolo privo di significato.
    """
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    # Una foto scattata a mano è storta di qualche grado. Un angolo grande vuol
    # dire che la stima è andata a vuoto (di solito sul bordo del foglio), e
    # ruotare di 40 gradi un documento dritto lo rovinerebbe.
    return angle if 0.5 <= abs(angle) <= 15 else 0.0


def _rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _to_gray(image_bytes: bytes) -> np.ndarray:
    pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    bgr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _rescale(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape[:2]
    long_side = max(height, width)
    if long_side >= _MIN_LONG_SIDE:
        # Già abbastanza grande: rimpicciolisco solo se è enorme, perché oltre
        # una certa dimensione Tesseract rallenta senza leggere meglio.
        if long_side <= _MAX_LONG_SIDE:
            return gray
        scale = _MAX_LONG_SIDE / long_side
    else:
        scale = min(_MIN_LONG_SIDE / long_side, 3.0)
    return cv2.resize(
        gray, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_CUBIC
    )


def preprocess_page(image_bytes: bytes) -> np.ndarray:
    """Documento a pagina intera: grigio, raddrizzato, ingrandito. Nient'altro."""
    gray = _to_gray(image_bytes)
    angle = _deskew_angle(gray)
    if angle:
        gray = _rotate(gray, angle)
    return _rescale(gray)


def preprocess_label(image_bytes: bytes) -> np.ndarray:
    """Etichetta: contrasto locale e binarizzazione, come da §7.2."""
    gray = _to_gray(image_bytes)
    angle = _deskew_angle(gray)
    if angle:
        gray = _rotate(gray, angle)

    contrasted = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    binary = cv2.adaptiveThreshold(
        contrasted, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )

    height, width = binary.shape[:2]
    if min(height, width) < 1000:
        binary = cv2.resize(binary, (width * 2, height * 2), interpolation=cv2.INTER_CUBIC)
    return binary


def preprocess_for_ocr(image_bytes: bytes, doc_type: str = "device_label") -> np.ndarray:
    if doc_type in _PAGE_DOC_TYPES:
        return preprocess_page(image_bytes)
    return preprocess_label(image_bytes)


def ocr_languages() -> str:
    """Lingue installate fra quelle che ci interessano.

    Le bolle arrivano anche da distributori esteri, spesso bilingui
    tedesco/inglese, ma il pacchetto lingua potrebbe non esserci su
    un'installazione più vecchia dell'immagine. Chiedere a Tesseract una lingua
    assente fa fallire l'intera chiamata, quindi si chiede solo ciò che c'è.
    """
    wanted = ("ita", "eng", "deu")
    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        return "ita+eng"
    present = [lang for lang in wanted if lang in available]
    return "+".join(present) if present else "eng"


def run_ocr(image_bytes: bytes, doc_type: str) -> str:
    processed = preprocess_for_ocr(image_bytes, doc_type)
    # psm 4 = colonne di larghezza variabile, che è la forma di una tabella di
    # bolla; psm 6 = blocco uniforme, giusto per un'etichetta.
    psm = 4 if doc_type in _PAGE_DOC_TYPES else 6
    return pytesseract.image_to_string(processed, config=f"--psm {psm} -l {ocr_languages()}")
