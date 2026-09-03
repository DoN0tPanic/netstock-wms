import json

import httpx
import structlog

from app.config import get_settings
from app.services import ai_config
from app.services.extraction.prompts import SYSTEM_PROMPT
from app.services.extraction.schemas import FieldSpec

logger = structlog.get_logger("netstock.extraction.llm")

settings = get_settings()


async def extract_via_llm(
    ocr_text: str, field_specs: list[FieldSpec], extra_instructions: str | None
) -> dict[str, str | None]:
    """Calls Ollama for the fields still unresolved after rules (§7.2 stage 4).

    A timeout is not fatal: caller falls back to barcode+rules-only results
    with engine 'ocr+rules'.
    """
    field_names = [spec.name for spec in field_specs]
    user_prompt = (
        f"Campi da estrarre: {', '.join(field_names)}.\n"
        + (f"Istruzioni aggiuntive: {extra_instructions}\n" if extra_instructions else "")
        + f"Testo OCR:\n---\n{ocr_text}\n---"
    )

    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=30.0) as client:
            response = await client.post(
                "/api/generate",
                json={
                    "model": await ai_config.modello(),
                    "system": SYSTEM_PROMPT,
                    "prompt": user_prompt,
                    "format": "json",
                    "stream": False,
                    # Senza, un modello con il ragionamento attivo antepone il
                    # proprio monologo al JSON e `json.loads` fallisce: nei log
                    # si vedeva `llm_extraction_failed` a ogni estrazione, con
                    # lo stadio 4 di fatto spento e qualche secondo buttato.
                    "think": False,
                    "options": {"temperature": 0, "top_p": 0.1, "num_predict": 256},
                },
            )
            response.raise_for_status()
            payload = response.json()
            raw = payload.get("response", "{}")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {}
            return {k: (v if isinstance(v, str) else None) for k, v in parsed.items()}
    except (httpx.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("llm_extraction_failed", error=str(exc))
        return {}
