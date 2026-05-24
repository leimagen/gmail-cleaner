import os
from anthropic import AsyncAnthropic


async def get_breach_advice(breach_title: str, data_types: list[str], description: str) -> str:
    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    try:
        types_str = ", ".join(data_types) if data_types else "desconocidos"
        msg = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Brecha de datos: {breach_title}\n"
                    f"Datos expuestos: {types_str}\n"
                    f"Descripción: {description[:500] if description else 'Sin descripción.'}\n\n"
                    "Dame 3-5 pasos concretos y cortos que el usuario debe seguir ahora para protegerse. "
                    "Responde en español, en formato lista con guiones, sin introducciones ni conclusiones."
                ),
            }],
        )
        return msg.content[0].text
    finally:
        await client.aclose()
