"""Claude Vision OCR for brokerage screenshot trade extraction."""

import base64
import json
import re

import anthropic

from app.core.config import settings

OCR_PROMPT = """You are a trading assistant. Extract options trade details from this brokerage screenshot.

Return a JSON array of trades. Each trade must have these fields:
{
  "ticker": string,
  "optionType": "call" | "put",
  "direction": "buy" | "sell",
  "strikePrice": number,
  "expiryDate": "YYYY-MM-DD",
  "premium": number (per share, not per contract),
  "quantity": integer (number of contracts),
  "brokerage": string | null,
  "confidence": "high" | "low"
}

Use "low" confidence for any field you are uncertain about.
Return ONLY the JSON array, no markdown, no explanation."""


def extract_trades_from_image(image_bytes: bytes, media_type: str = "image/png") -> list[dict]:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": OCR_PROMPT},
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    # Strip markdown code blocks if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
