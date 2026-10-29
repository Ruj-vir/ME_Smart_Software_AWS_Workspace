"""Fit spreadsheet PDF pages to A4 without changing their pagination."""
import pymupdf
from PIL import Image, ImageChops


def fit_pages_to_a4(pdf_bytes: bytes) -> bytes:
    """Trim outer white space and fit A4 with 8 mm margins on all sides.

    Rasterization is used only to locate visible content; output stays vector.
    Blank pages remain blank A4 pages. Page orientation and pagination remain
    unchanged, but horizontal and vertical scaling can differ.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as source, pymupdf.open() as output:
        # Preserve visible annotation appearances before embedding page content.
        source.bake()
        for page in source:
            page.remove_rotation()
            landscape = page.rect.width > page.rect.height
            width, height = 210 * 72 / 25.4, 297 * 72 / 25.4
            if landscape:
                width, height = height, width
            target = output.new_page(width=width, height=height)
            # Bound memory use for unusually large spreadsheet paper sizes.
            scale = min(2, 2400 / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            bbox = ImageChops.difference(
                image, Image.new("RGB", image.size, "white")
            ).getbbox()
            if bbox is None:
                continue
            clip = pymupdf.Rect(
                bbox[0] / scale, bbox[1] / scale,
                bbox[2] / scale, bbox[3] / scale,
            ) & page.rect
            margin = 8 * 72 / 25.4
            content_rect = pymupdf.Rect(margin, margin, width - margin, height - margin)
            target.show_pdf_page(
                content_rect, source, page.number, clip=clip, keep_proportion=False
            )
        return output.tobytes(garbage=3, deflate=True)
