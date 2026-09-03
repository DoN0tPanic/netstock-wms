"""Normalizzazione dei file caricati: tutto diventa un elenco di pagine."""

import io

import pytest
from PIL import Image

from app.exceptions import ValidationAppError
from app.services.extraction.documents import ALLOWED_MIME_TYPES, to_pages


def _image_bytes(fmt: str = "PNG", size: tuple[int, int] = (300, 400)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format=fmt)
    return buffer.getvalue()


def _pdf_bytes(pages: int = 2) -> bytes:
    buffer = io.BytesIO()
    images = [Image.new("RGB", (300, 400), "white") for _ in range(pages)]
    images[0].save(buffer, "PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


class TestImages:
    @pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "BMP", "TIFF"])
    def test_single_page_formats(self, fmt):
        pages = to_pages(_image_bytes(fmt), f"image/{fmt.lower()}")
        assert len(pages) == 1
        assert Image.open(io.BytesIO(pages[0])).size == (300, 400)

    def test_output_is_always_png(self):
        page = to_pages(_image_bytes("JPEG"), "image/jpeg")[0]
        assert Image.open(io.BytesIO(page)).format == "PNG"


class TestPdf:
    def test_every_page_becomes_an_image(self):
        assert len(to_pages(_pdf_bytes(3), "application/pdf")) == 3

    def test_detected_by_content_when_the_browser_lies(self):
        """Alcuni browser mandano application/octet-stream: conta il contenuto."""
        assert len(to_pages(_pdf_bytes(2), "application/octet-stream")) == 2

    def test_rendered_larger_than_the_source_page(self):
        """A 200 DPI il testo di una bolla resta leggibile dall'OCR; alla
        risoluzione nominale del PDF (72 DPI) no."""
        page = to_pages(_pdf_bytes(1), "application/pdf")[0]
        assert min(Image.open(io.BytesIO(page)).size) > 400

    def test_a_broken_pdf_says_what_to_do(self):
        with pytest.raises(ValidationAppError, match="protetto da password o danneggiato"):
            to_pages(b"%PDF-rotto", "application/pdf")


class TestRejections:
    def test_unknown_content_is_refused_with_the_accepted_list(self):
        with pytest.raises(ValidationAppError, match="JPEG, PNG, WebP, TIFF, BMP, GIF e PDF"):
            to_pages(b"non un documento", "application/zip")

    def test_heic_is_not_accepted_server_side(self):
        """La conversione avviene nel browser, per non tirarsi in casa una
        dipendenza LGPL (§2.3)."""
        assert "image/heic" not in ALLOWED_MIME_TYPES
