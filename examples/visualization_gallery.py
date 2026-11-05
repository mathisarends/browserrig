"""A contact sheet made from unaltered browser screenshots."""

import base64
import html
import json
from pathlib import Path

from browserrig import ChromeBrowser
from browserrig.browser import Launch, Viewport, screenshot


async def render_gallery(
    directory: Path, url: str, shots: list[dict], *, layout: str
) -> None:
    selected = [shot for shot in shots if shot["file"] != "observation.png"]
    cards = []
    for shot in selected:
        filename = html.escape(str(shot["file"]))
        caption = html.escape(str(shot["title"]))
        cards.append(
            f'<figure><img src="/proof/{filename}"><figcaption>{caption}</figcaption></figure>'
        )
    document = """<!doctype html><html><head><meta charset=utf-8><style>
      *{box-sizing:border-box}body{margin:0;background:#181818;color:#e6e6e6;
      font:14px/1.5 'Segoe UI',sans-serif;padding:42px}header{margin-bottom:30px;
      display:flex;justify-content:space-between;align-items:baseline}
      h1{font-size:25px;letter-spacing:-.6px;font-weight:500;margin:0}
      header span,figcaption{font-size:12px;color:#a3a3a5}
      main{display:grid;grid-template-columns:1fr 1fr;gap:24px}
      figure{margin:0;min-width:0}img{display:block;width:100%;height:490px;
      object-fit:contain;background:#141414;border:1px solid #ffffff1f;border-radius:8px}
      figcaption{padding:10px 0}footer{margin-top:24px;color:#a3a3a5;font-size:11px}
      </style></head><body><header><h1>Browser choreography</h1>
      <span>Chrome · native input · {{layout}} keyboard</span></header><main>"""
    document = document.replace("{{layout}}", "German" if layout == "de" else "English")
    document += "".join(cards)
    document += (
        "</main><footer>Unaltered browser captures. The model-thinking receipt is scripted; "
        "the walkthrough makes no model requests.</footer></body></html>"
    )
    (directory / "gallery.html").write_text(document, encoding="utf-8")
    async with ChromeBrowser(
        Launch(url=url + "/gallery", viewport=Viewport(width=1600, height=2800))
    ) as browser:
        tab = browser.active_tab
        await tab.evaluate(
            "Promise.all([...document.images].map(img => img.decode())).then(() => true)"
        )
        height = min(
            4320,
            json.loads(await tab.evaluate("document.documentElement.scrollHeight")),
        )
        await tab.cdp.emulation.set_device_metrics_override(
            width=1600, height=height, device_scale_factor=1, mobile=False
        )
        encoded = await screenshot(tab)
        (directory / "overview.png").write_bytes(base64.b64decode(encoded))
