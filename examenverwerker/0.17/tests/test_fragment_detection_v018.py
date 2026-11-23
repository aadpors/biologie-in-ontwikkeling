"""Regressietests voor de conservatieve fragmentdetectie van 0.18.

De belangrijkste regressie die deze test afvangt: een grote witruimte
midden in een meerregelige vraag mag nooit automatisch als vraaggrens
worden behandeld. Alleen de expliciete, goedgekeurde vraagstart en de
volgende vraagstart begrenzen het automatische voorstel.
"""
from PIL import Image, ImageDraw

from examenverwerker.question_fragments import normalise_stitched_selections


def test_internal_blank_line_does_not_truncate_question(tmp_path):
    image_path = tmp_path / "stitched.png"
    image = Image.new("RGB", (120, 1000), "white")
    draw = ImageDraw.Draw(image)

    # Simuleer tekst en een figuur verspreid over één lange vraag.
    # De volledig witte rij op y=300 is een interne alinea-/figuurscheiding,
    # niet het einde van de vraag.
    draw.rectangle((10, 100, 110, 280), fill="black")
    draw.rectangle((10, 320, 110, 600), fill="black")
    draw.rectangle((10, 620, 110, 900), fill="black")
    image.save(image_path)

    selections = [
        {
            "id": "q1",
            "type": "vraag",
            "top": 100,
            "bottom": 300,
            "question_numbers": [1],
        },
        {
            "id": "q2",
            "type": "vraag",
            "top": 620,
            "bottom": 950,
            "question_numbers": [2],
        },
    ]
    # De witte rijen zijn over de volledige beeldbreedte wit. De interne
    # witregel op 300 mag niet als automatische ondergrens worden gekozen.
    white_rows = [[50, 50], [300, 300], [610, 610], [950, 950]]

    result = normalise_stitched_selections(
        selections,
        white_rows,
        image_path,
        image_height=1000,
        leading_top=50,
    )

    question_one = next(item for item in result if item["type"] == "vraag"
                        and item["question_numbers"] == [1])
    assert question_one["bottom"] > 300
    assert question_one["bottom"] == 610


def test_fragment_boundaries_are_only_selected_from_white_rows(tmp_path):
    image_path = tmp_path / "stitched.png"
    image = Image.new("RGB", (80, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 80, 79, 319), fill="black")
    image.save(image_path)

    white_rows = [[20, 20], [60, 60], [340, 340]]
    result = normalise_stitched_selections(
        [{
            "id": "q1", "type": "vraag", "top": 83, "bottom": 315,
            "question_numbers": [1],
        }],
        white_rows,
        image_path,
        image_height=400,
        leading_top=20,
    )

    question = next(item for item in result if item["type"] == "vraag")
    assert question["top"] in {20, 60, 340}
    assert question["bottom"] in {20, 60, 340}
