"""Exercise real Chrome and OTLP without a provider SDK, API key or remote page.

docker compose up -d --wait
uv run --extra otel python -m examples.tracing_smoke --trace-content
"""

import argparse
import asyncio

from dotenv import load_dotenv
from harnessed import PolicyDecision
from harnessed.events import ToolCallFinishedEvent
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Agent, Chrome
from examples.telemetry import add_tracing_arguments, tracing_plugins


async def _serve_page(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        await reader.readuntil(b"\r\n\r\n")
        body = (
            b"<!doctype html><title>Browserrig tracing</title><h1>Trace smoke test</h1>"
        )
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Send a scripted browser trace to local Phoenix"
    )
    add_tracing_arguments(parser)
    parser.set_defaults(trace=True)
    args = parser.parse_args()
    server = await asyncio.start_server(_serve_page, "127.0.0.1", 0)
    page = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
    async with (
        server,
        tracing_plugins(
            enabled=args.trace,
            capture_content=args.trace_content,
            max_content_length=args.trace_max_content_length,
        ) as telemetry,
    ):
        agent = Agent(
            model=ScriptedModel(
                [call("navigate", url=page), "Browserrig tracing smoke test completed."]
            ),
            browser=Chrome.launch(url="about:blank"),
            plugins=[Approvals(default=PolicyDecision.ALLOW), *telemetry],
        )
        async with agent.session() as session:
            result = await session.run(
                "Open the local smoke-test page and confirm completion."
            )
            tools = [
                event
                for event in result.events
                if isinstance(event, ToolCallFinishedEvent)
            ]
            if len(tools) != 1 or tools[0].result.is_error:
                raise RuntimeError(
                    "Smoke-test navigation failed; inspect the tool span in Phoenix"
                )
            print(result.text)
            print(f"Session: {session.id}")
    print(
        "Phoenix: http://127.0.0.1:6006 (project: browserrig). Check stderr for export errors."
    )


if __name__ == "__main__":
    asyncio.run(main())
