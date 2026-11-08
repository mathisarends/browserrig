"""Small inline previews; screenshot ownership stays with perception."""

import base64
from io import BytesIO

from PIL import Image


def thumbnail(image: str) -> str:
    data = image.partition(",")[2] if image.startswith("data:") else image
    try:
        with Image.open(BytesIO(base64.b64decode(data))) as source:
            preview = source.convert("RGB")
            preview.thumbnail((320, 180))
            output = BytesIO()
            preview.save(output, format="JPEG", quality=75)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode(
            "ascii"
        )
    except (ValueError, OSError):
        return ""
