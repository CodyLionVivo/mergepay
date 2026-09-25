from google import genai

from app.config import settings


class GeminiConfigurationError(Exception):
    """La configuración de Gemini está incompleta."""


class GeminiGenerationError(Exception):
    """Gemini no pudo generar una respuesta."""


class GeminiClient:
    def __init__(self) -> None:
        if not settings.google_api_key:
            raise GeminiConfigurationError(
                "GOOGLE_API_KEY is not configured"
            )

        self._client = genai.Client(
            api_key=settings.google_api_key,
        )
        self._model = settings.gemini_model.removeprefix("models/")

    def generate(self, prompt: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
        except Exception as error:
            raise GeminiGenerationError(
                "Gemini request failed"
            ) from error

        text = response.text or ""

        if not text.strip():
            raise GeminiGenerationError(
                "Gemini returned an empty response"
            )

        return text.strip()