import asyncio
from collections.abc import AsyncIterator
from io import BytesIO

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from browserrig import LocalWorkspace


@pytest.fixture(autouse=True)
def _default_workspaces(tmp_path_factory, monkeypatch):
    """Keep default workspaces out of the repository."""
    monkeypatch.setattr(
        LocalWorkspace, "default_root", tmp_path_factory.mktemp("workspaces")
    )


@pytest.fixture
async def site(pdf_document, xlsx_document) -> AsyncIterator[str]:
    pages = {
        "/": """<!doctype html><title>Test form</title>
            <label>Email<input id=email></label>
            <label>Password<input id=secret type=password value=never-echo-this></label>
            <label>Choice<select id=choice><option>One</option><option>Two</option></select></label>
            <label>Date<input id=date type=date></label>
            <button id=submit onclick="this.textContent='Done'">Submit</button>
            <button id=unchanged>Nothing</button>
            <button id=jump onclick="window.scrollTo(0,1000)">Jump</button>
            <button id=hash onclick="location.hash='changed';window.scrollTo(0,1000)">Hash</button>
            <button id=popup onclick="window.open('/other')">New tab</button>
            <a id=download href='/download-pdf' download>Download PDF</a>
            <button id=dialog onclick="alert('Confirm me')">Dialog</button>
            <div id=shadow></div><script>
              const root=document.querySelector('#shadow').attachShadow({mode:'open'});
              root.innerHTML='<button>Shadow button</button>';
            </script><div style="height:2200px"></div>""",
        "/other": "<!doctype html><title>Other</title><h1>Other page</h1>",
        "/gestures": """<!doctype html><title>Gestures</title><style>
            body{margin:0} .box{position:absolute;width:120px;height:60px;background:#acf}
            #double{position:absolute;left:20px;top:20px;width:120px;height:40px}
            #native{left:20px;top:110px} #nativeTarget{left:300px;top:110px}
            #pointer{left:20px;top:260px} #pointerTarget{left:300px;top:260px}
            </style><button id=double>Double</button>
            <div id=native class=box draggable=true tabindex=0>Native source</div>
            <div id=nativeTarget class=box role=button>Native target</div>
            <div id=pointer class=box tabindex=0>Pointer source</div>
            <div id=pointerTarget class=box role=button>Pointer target</div>
            <script>
            window.details=[];window.doubles=0;window.nativeDrop='';window.pointerDrop=false;
            window.contexts=[];
            const double=document.querySelector('#double');
            double.addEventListener('click',e=>window.details.push(e.detail));
            double.addEventListener('dblclick',()=>window.doubles++);
            double.addEventListener('contextmenu',e=>{e.preventDefault();
                window.contexts.push({button:e.button,trusted:e.isTrusted})});
            const native=document.querySelector('#native');
            native.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain','payload'));
            const target=document.querySelector('#nativeTarget');
            target.addEventListener('dragover',e=>e.preventDefault());
            target.addEventListener('drop',e=>{e.preventDefault();
                window.nativeDrop=e.dataTransfer.getData('text/plain')});
            let dragging=false;
            document.querySelector('#pointer').addEventListener('pointerdown',e=>{
                e.preventDefault();dragging=true});
            document.addEventListener('pointerup',e=>{if(dragging){
                const r=document.querySelector('#pointerTarget').getBoundingClientRect();
                window.pointerDrop=e.clientX>=r.left&&e.clientX<=r.right&&
                    e.clientY>=r.top&&e.clientY<=r.bottom;dragging=false}});
            </script>""",
        "/canvas": """<!doctype html><title>Canvas</title><style>body{margin:0}</style>
            <canvas width=500 height=400></canvas><script>
            const ctx=document.querySelector('canvas').getContext('2d');
            ctx.fillStyle='white';ctx.fillRect(0,0,500,400);
            setTimeout(()=>{ctx.fillStyle='red';ctx.fillRect(0,0,200,200);},150);
            </script>""",
        "/frames": """<!doctype html><title>Frames</title><iframe src='/inner'></iframe>""",
        "/inner": "<!doctype html><label>Inside<input id=inside></label>",
        "/frame-host": """<!doctype html><style>body{margin:0;height:3000px}
            iframe{position:absolute;left:100px;top:100px;width:600px;height:300px;
            border:10px solid blue}</style><iframe src='/frame-leaf'></iframe>""",
        "/frame-middle": """<!doctype html><style>body{margin:0}</style>
            <iframe style='position:absolute;left:40px;top:50px;width:480px;height:220px;
            border:5px solid red' src='/frame-leaf'></iframe>""",
        "/frame-cross-middle": """<!doctype html><style>body{margin:0}</style>
            <iframe style='position:absolute;left:40px;top:50px;width:480px;height:220px;
            border:5px solid red'></iframe><script>
            const url=new URL('/frame-leaf',location.href);
            url.hostname=location.hostname==='localhost'?'127.0.0.1':'localhost';
            document.querySelector('iframe').src=url.href;</script>""",
        "/frame-leaf": """<!doctype html><style>body{margin:0}
            button{position:absolute;left:80px;top:60px;width:120px;height:40px}
            input{position:absolute;left:80px;top:120px}</style>
            <button onclick="document.body.dataset.clicked=event.isTrusted">Frame button</button>
            <input aria-label='Frame input'>""",
        "/ticker": """<!doctype html><title>Ticker</title><div id=t></div>
            <script>setInterval(()=>{document.querySelector('#t').textContent=Date.now()},20)</script>""",
    }

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            path = raw.split(b" ")[1].decode().split("?")[0]
            if path == "/download":
                body = b"download payload"
                content_type = (
                    b"Content-Type: application/octet-stream\r\n"
                    b"Content-Disposition: attachment; filename=example.txt\r\n"
                )
            elif path == "/download-xlsx":
                body = xlsx_document
                content_type = (
                    b"Content-Type: application/vnd.openxmlformats-officedocument."
                    b"spreadsheetml.sheet\r\n"
                    b"Content-Disposition: attachment; filename=report.xlsx\r\n"
                )
            elif path == "/download-pdf":
                body = pdf_document
                content_type = (
                    b"Content-Type: application/pdf\r\n"
                    b"Content-Disposition: attachment; filename=report.pdf\r\n"
                )
            else:
                body = pages.get(path, "<title>Missing</title>").encode()
                content_type = b"Content-Type: text/html; charset=utf-8\r\n"
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + content_type
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture(name="xlsx_document")
def _xlsx_document() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Revenue"
    sheet.append(["Mission", "Value", "Formula"])
    sheet.append(["Voyager", 42, "=B2*2"])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


@pytest.fixture(name="pdf_document")
def _pdf_document() -> bytes:
    writer = PdfWriter()
    for text in ("First page: Voyager 1", "Second page: Voyager 2"):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode())
        page.replace_contents(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
