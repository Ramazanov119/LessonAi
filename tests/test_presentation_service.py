import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from models import AIConfig, NBDeck, NBSlide
from services.presentation_service import PresentationRequest, PresentationService
from services.presenton_service import PresentonResult


def request():
    return PresentationRequest(
        subject="Информатика",
        topic="Алгоритмы",
        specialty="Разработка ПО",
        language="Русский",
        lesson_type="Новый урок",
        lesson_duration="70 минут",
        teacher="Преподаватель",
        college="ETEC",
        group="ИС-21",
        lesson_plan="План",
        lecture="Лекция",
        practice="Практика",
        lesson_date="23.09.2026",
    )


class PresentationServiceTest(unittest.TestCase):
    @patch("services.presentation_service.render_nb_deck")
    @patch("services.presentation_service.create_presentation_deck")
    def test_native_engine_remains_default_path(self, create_deck, render):
        deck = NBDeck(
            "Алгоритмы", "Информатика", "Преподаватель", "ETEC", "ИС-21",
            "23.09.2026", (NBSlide("title", "Алгоритмы"),),
        )
        create_deck.return_value = deck
        render.return_value = BytesIO(b"native-pptx")
        service = PresentationService("native", AIConfig("openai", "router"))

        artifact = service.generate(request())

        self.assertEqual(artifact.content.getvalue(), b"native-pptx")
        self.assertEqual(artifact.stored_content["title"], "Алгоритмы")
        create_deck.assert_called_once()

    def test_presenton_engine_returns_downloadable_bytes(self):
        client = Mock()
        client.generate.return_value = PresentonResult(
            "deck-1", "/app_data/deck-1/lesson.pptx", BytesIO(b"presenton-pptx")
        )
        service = PresentationService(
            "presenton", AIConfig("openai", "router"), client
        )

        artifact = service.generate(request())

        self.assertEqual(artifact.content.getvalue(), b"presenton-pptx")
        self.assertEqual(artifact.stored_content["engine"], "presenton")
        source = client.generate.call_args.args[0]
        self.assertIn("## Поурочный план\nПлан", source)
        self.assertIn("## Преподаватель\nПреподаватель", source)


if __name__ == "__main__":
    unittest.main()
