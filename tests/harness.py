"""Starts the TV add-on (tests/addon_harness.js) with a fake TV behind it."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

HERE = Path(__file__).parent


def available() -> bool:
    return shutil.which("node") is not None


class Addon:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.port = 0
        self.code = ""
        self.events: list[dict] = []
        self._new = asyncio.Event()
        self._reader: asyncio.Task | None = None

    async def start(self) -> Addon:
        self.proc = await asyncio.create_subprocess_exec(
            "node", str(HERE / "addon_harness.js"), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
        )
        first = json.loads(await asyncio.wait_for(self.proc.stdout.readline(), 15))
        self.port, self.code = first["port"], first["code"]
        self._reader = asyncio.create_task(self._read())
        return self

    async def _read(self) -> None:
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                return
            try:
                self.events.append(json.loads(line))
            except ValueError:
                continue
            self._new.set()

    async def command(self, cmd: str) -> None:
        self.proc.stdin.write((cmd + "\n").encode())
        await self.proc.stdin.drain()

    async def wait_for(self, pred, timeout: float = 5, start: int = 0) -> dict:
        async def loop():
            seen = start
            while True:
                for e in self.events[seen:]:
                    if pred(e):
                        return e
                seen = len(self.events)
                self._new.clear()
                await self._new.wait()

        return await asyncio.wait_for(loop(), timeout)

    async def new_code(self) -> str:
        n = len(self.events)
        await self.command("pair")
        return (await self.wait_for(lambda e: e.get("ev") == "code", start=n))["code"]

    async def stop(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
