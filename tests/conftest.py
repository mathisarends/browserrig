import asyncio
from collections.abc import AsyncIterator

import pytest


@pytest.fixture
async def site() -> AsyncIterator[str]:
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
            const double=document.querySelector('#double');
            double.addEventListener('click',e=>window.details.push(e.detail));
            double.addEventListener('dblclick',()=>window.doubles++);
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
        "/blank-canvas": (
            "<!doctype html><title>Blank</title><canvas width=500 height=400></canvas>"
        ),
        "/frames": """<!doctype html><title>Frames</title><iframe src='/inner'></iframe>""",
        "/inner": "<!doctype html><label>Inside<input id=inside></label>",
        "/ticker": """<!doctype html><title>Ticker</title><div id=t></div>
            <script>setInterval(()=>{document.querySelector('#t').textContent=Date.now()},20)</script>""",
    }

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            path = raw.split(b" ")[1].decode().split("?")[0]
            body = (
                b"download payload"
                if path == "/download"
                else pages.get(path, "<title>Missing</title>").encode()
            )
            content_type = (
                (
                    b"Content-Type: application/octet-stream\r\n"
                    b"Content-Disposition: attachment; filename=example.txt\r\n"
                )
                if path == "/download"
                else b"Content-Type: text/html; charset=utf-8\r\n"
            )
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
