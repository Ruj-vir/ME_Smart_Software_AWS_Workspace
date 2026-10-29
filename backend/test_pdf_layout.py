import unittest
import pymupdf
from pdf_layout import fit_pages_to_a4


class PdfLayoutTests(unittest.TestCase):
    def test_page_count_orientation_text_and_blank_page(self):
        with pymupdf.open() as source:
            page = source.new_page(width=600, height=900)
            page.draw_rect((150, 200, 450, 650))
            page.insert_text((180, 230), "Portrait form")
            page = source.new_page(width=900, height=600)
            page.insert_text((200, 250), "Landscape form")
            source.new_page(width=600, height=900)
            data = source.tobytes()
        with pymupdf.open(stream=fit_pages_to_a4(data), filetype="pdf") as result:
            self.assertEqual(len(result), 3)
            for index, page in enumerate(result):
                dims = sorted((page.rect.width, page.rect.height))
                self.assertAlmostEqual(dims[0], 210 * 72 / 25.4, places=3)
                self.assertAlmostEqual(dims[1], 297 * 72 / 25.4, places=3)
                self.assertEqual(page.rect.width > page.rect.height, index == 1)
            self.assertIn("Portrait form", result[0].get_text())
            self.assertIn("Landscape form", result[1].get_text())
            self.assertEqual(result[2].get_text(), "")
            # Leave 8 mm of white space on all four sides of the form.
            # Allow one point for stroke width / raster rounding.
            border = result[0].get_drawings()[0]["rect"]
            margin = 8 * 72 / 25.4
            expected_rect = pymupdf.Rect(margin, margin, result[0].rect.width - margin,
                                        result[0].rect.height - margin)
            for actual, expected in zip(border, expected_rect):
                self.assertAlmostEqual(actual, expected, delta=1)

    def test_rotated_page_keeps_visible_text(self):
        with pymupdf.open() as source:
            page = source.new_page()
            page.insert_text((100, 100), "Rotated form")
            page.set_rotation(90)
            data = source.tobytes()
        with pymupdf.open(stream=fit_pages_to_a4(data), filetype="pdf") as result:
            self.assertGreater(result[0].rect.width, result[0].rect.height)
            self.assertIn("Rotated form", result[0].get_text())


if __name__ == "__main__":
    unittest.main()
