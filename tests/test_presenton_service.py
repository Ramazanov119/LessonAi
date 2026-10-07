import unittest
from unittest.mock import Mock, patch

import requests

from services.presenton_service import PresentonClient, PresentonServiceError


class PresentonClientTest(unittest.TestCase):
    @patch("services.presenton_service.requests.get")
    @patch("services.presenton_service.requests.post")
    def test_generate_and_download_pptx(self, post, get):
        post_response = Mock()
        post_response.json.return_value = {
            "presentation_id": "deck-1",
            "path": "/app_data/deck-1/lesson.pptx",
        }
        post_response.raise_for_status.return_value = None
        post.return_value = post_response

        get_response = Mock(content=b"PK\x03\x04pptx")
        get_response.raise_for_status.return_value = None
        get.return_value = get_response

        result = PresentonClient(
            "http://localhost:5001", "secret", 30
        ).generate("LessonAI source", "Русский")

        self.assertEqual(result.presentation_id, "deck-1")
        self.assertEqual(result.content.getvalue(), b"PK\x03\x04pptx")
        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["web_search"])
        self.assertEqual(payload["n_slides"], 9)
        self.assertEqual(
            get.call_args.args[0],
            "http://localhost:5001/app_data/deck-1/lesson.pptx",
        )

    def test_rejects_external_download_url(self):
        client = PresentonClient("http://localhost:5001")
        with self.assertRaises(PresentonServiceError):
            client.download("https://example.com/file.pptx")

    def test_requires_base_url(self):
        with self.assertRaises(PresentonServiceError):
            PresentonClient("").generate("content", "Русский")

    @patch("services.presenton_service.requests.post")
    def test_unavailable_service_has_user_facing_error(self, post):
        post.side_effect = requests.ConnectionError("offline")
        with self.assertRaisesRegex(
            PresentonServiceError,
            "Сервис генерации презентаций временно недоступен",
        ):
            PresentonClient("http://localhost:5001").generate(
                "content", "Русский"
            )


if __name__ == "__main__":
    unittest.main()
