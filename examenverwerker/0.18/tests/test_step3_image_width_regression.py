"""Regressietest voor het verlies van de rechterzijde in stap 3.

Deze test controleert de CSS-contractregels die voorkomen dat de stitched
afbeelding door flex-minimums of overflow wordt afgekapt. Een browsertest
blijft wenselijk, maar deze controle voorkomt dat de herstelregels ongemerkt
uit het stylesheet verdwijnen.
"""
from pathlib import Path
import unittest


CSS_PATH = Path(__file__).parents[1] / "static" / "app.css"


class Step3ImageWidthRegressionTests(unittest.TestCase):
    def test_stitched_image_and_scroll_container_allow_full_width(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        # De scrollcontainer moet horizontale overflow kunnen afhandelen.
        self.assertIn(".stitched-image-scroll", css)
        self.assertIn("overflow-x: auto;", css)
        # Flex-items en afbeelding mogen niet door oude max-width-regels
        # onbedoeld kleiner worden gemaakt of aan de rechterkant afgekapt.
        self.assertIn("min-width: 0;", css)
        self.assertIn(".stitched-image-wrap", css)
        self.assertIn("max-width: none;", css)
        self.assertIn(".stitched-overlay", css)


if __name__ == "__main__":
    unittest.main()
