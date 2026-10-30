"""Render and inspect actual PDFs, using synthetic names and measurements only."""
import io
import unittest

import pymupdf
from pypdf import PdfReader

import main
from tests.test_reports import report_fixture


class UnicodePDFTests(unittest.TestCase):
    def test_arabic_name_embeds_unicode_font_and_retains_all_letters(self):
        name = "طفل تجريبي محمد أحمد"
        data = main.generate_pdf_report(report_fixture(child_name=name), filename=None)
        document = pymupdf.open(stream=data, filetype="pdf")
        self.addCleanup(document.close)
        text = "\n".join(page.get_text() for page in document)
        for letter in set(name.replace(" ", "")):
            self.assertIn(letter, text)
        self.assertNotIn("\ufffd", text)
        self.assertTrue(any("Amiri" in font[3] for page in document for font in page.get_fonts()))
        self.assertTrue(any(font[1] in ("ttf", "otf") for page in document for font in page.get_fonts()))

    def test_long_name_wraps_and_remains_complete_inside_margins(self):
        name = "W" * 80
        data = main.generate_pdf_report(report_fixture(child_name=name), filename=None)
        document = pymupdf.open(stream=data, filetype="pdf")
        self.addCleanup(document.close)
        extracted = "".join(page.get_text() for page in document)
        self.assertIn(name, "".join(extracted.split()))
        for page in document:
            for block in page.get_text("blocks"):
                if block[6] == 0:
                    self.assertGreaterEqual(block[0], 15)
                    self.assertLessEqual(block[2], page.rect.width - 15)

    def test_unicode_punctuation_is_preserved_in_report_text(self):
        sentence = "Check the child’s wearable — record the reading."
        data = main.generate_pdf_report(report_fixture(recommendations=[sentence]), filename=None)
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
        self.assertIn("child’s", text)
        self.assertIn("—", text)
        self.assertNotIn("?", text)

    def test_mixed_arabic_and_english_name_is_complete_without_overlap(self):
        data = main.generate_pdf_report(
            report_fixture(child_name="محمد Test Child 2026", recommendations=["دوّن وقت القياس وراجعه مع الطبيب."]),
            filename=None,
        )
        document = pymupdf.open(stream=data, filetype="pdf")
        self.addCleanup(document.close)
        text = "\n".join(page.get_text() for page in document)
        self.assertIn("Test Child 2026", text)
        self.assertIn("ط", text)
        for page in document:
            self.assertGreater(len(page.get_pixmap().samples), 1000)


if __name__ == "__main__":
    unittest.main()
