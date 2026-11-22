"""MCP stdio transport for a supervised, short-lived hook worker (POSIX)."""
from contextlib import asynccontextmanager
import asyncio

import anyio
from mcp import ClientSession
from mcp.client.stdio import get_default_environment
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage


@asynccontextmanager
async def hook_connection(connection):
    # Inherit the worker's process group. Its supervisor can terminate the entire
    # local command tree at the deadline, even when a server ignores stdin/TERM.
    process = await asyncio.create_subprocess_exec(
        connection['command'], *connection['args'], stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env=get_default_environment(), limit=1024 * 1024,
    )
    inbound, reader = anyio.create_memory_object_stream(0)
    writer, outbound = anyio.create_memory_object_stream(0)

    async def receive():
        async with inbound:
            while line := await process.stdout.readline():
                await inbound.send(SessionMessage(JSONRPCMessage.model_validate_json(line)))

    async def send():
        async with outbound:
            async for item in outbound:
                process.stdin.write((item.message.model_dump_json(by_alias=True, exclude_none=True) + '\n').encode())
                await process.stdin.drain()

    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(receive)
            tasks.start_soon(send)
            try:
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    yield client
            finally:
                tasks.cancel_scope.cancel()
    finally:
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), 0.15)
            except (TimeoutError, ProcessLookupError):
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        await reader.aclose()
        await writer.aclose()
