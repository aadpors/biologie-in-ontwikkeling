"""Gerichte tests voor herkenning van meerkeuzevragen en antwoordopties."""
import unittest

from examenverwerker.question_analysis import detect_options, detect_question_type


class QuestionAnalysisTests(unittest.TestCase):
    def test_detects_parenthesised_and_punctuated_option_labels(self):
        text = "(A) Eerste antwoord\\n(B) Tweede antwoord\\nC. Derde antwoord\\nD) Vierde antwoord"
        options = detect_options(text)
        self.assertEqual([item["letter"] for item in options], ["A", "B", "C", "D"])
        self.assertEqual(options[0]["text"], "Eerste antwoord")
        self.assertEqual(options[3]["text"], "Vierde antwoord")
        self.assertEqual(detect_question_type(text, options)[0], "meerkeuze")

    def test_detects_option_letter_on_its_own_line(self):
        text = "A\\nEerste antwoord met een vervolgregel\\nB\\nTweede antwoord\\nC\\nDerde antwoord"
        options = detect_options(text)
        self.assertEqual([item["letter"] for item in options], ["A", "B", "C"])
        self.assertIn("vervolgregel", options[0]["text"])
        self.assertEqual(detect_question_type(text, options)[0], "meerkeuze")

    def test_detects_multiple_choice_prompt_without_extracted_options(self):
        prompts = [
            "Welke combinatie van uitspraken is juist?",
            "Kruis het juiste antwoord aan.",
            "Wat is juist?",
            "Welke van onderstaande processen vindt plaats?",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(detect_question_type(prompt, [])[0], "meerkeuze")

    def test_does_not_treat_words_starting_with_a_letter_as_options(self):
        text = "Als de temperatuur stijgt, neemt de snelheid toe.\\nBovendien verandert de druk."
        self.assertEqual(detect_options(text), [])

    def test_two_options_alone_do_not_force_multiple_choice_classification(self):
        options = detect_options("A. Ja\\nB. Nee")
        self.assertEqual([item["letter"] for item in options], ["A", "B"])
        self.assertEqual(detect_question_type("Kies tussen twee mogelijkheden.", options)[0], "onbekend")


if __name__ == "__main__":
    unittest.main()
