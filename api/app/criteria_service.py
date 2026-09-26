from json import JSONDecodeError, loads

from app.gemini_client import GeminiClient, GeminiGenerationError


class CriteriaGenerationError(Exception):
    """La respuesta de Gemini no pudo convertirse en criterios válidos."""


SYSTEM_PROMPT = """
Eres un Technical Product Manager especializado en software.

Genera entre 3 y 5 criterios de aceptación técnicos, precisos y comprobables
para una tarea de desarrollo.

Cada criterio debe:
- describir un resultado observable;
- poder verificarse mediante tests, revisión de código o una comprobación manual;
- evitar lenguaje ambiguo como "funciona bien", "debe ser rápido" o "debe ser intuitivo";
- ser independiente de los demás;
- estar escrito en español.

Devuelve ÚNICAMENTE JSON válido con esta forma exacta:

{
  "criteria": [
    "criterio 1",
    "criterio 2",
    "criterio 3"
  ]
}

No incluyas Markdown, explicaciones, comentarios ni texto fuera del JSON.
""".strip()


def generate_criteria(title: str, description: str) -> list[str]:
    prompt = f"""
{SYSTEM_PROMPT}

Título de la bounty:
{title}

Descripción:
{description}
""".strip()

    response = GeminiClient().generate(prompt)

    try:
        payload = loads(response)
    except JSONDecodeError as error:
        raise CriteriaGenerationError(
            "Gemini returned invalid JSON"
        ) from error

    criteria = payload.get("criteria")

    if not isinstance(criteria, list):
        raise CriteriaGenerationError(
            "Gemini response does not contain a criteria list"
        )

    cleaned = [
        item.strip()
        for item in criteria
        if isinstance(item, str) and item.strip()
    ]

    if not 3 <= len(cleaned) <= 5:
        raise CriteriaGenerationError(
            "Gemini must return between 3 and 5 criteria"
        )

    return cleaned