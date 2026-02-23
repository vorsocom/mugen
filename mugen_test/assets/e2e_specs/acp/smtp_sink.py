#!/usr/bin/env python3
"""Minimal SMTP sink used by ACP invitation redeem E2E checks."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
from typing import Any


class SMTPMessageCapture:
    """Append-only JSON-lines writer for captured SMTP messages."""

    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path
        self._lock = asyncio.Lock()
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.touch(exist_ok=True)

    async def write(
        self,
        *,
        peer: Any,
        mail_from: str,
        rcpt_to: list[str],
        data_lines: list[str],
    ) -> None:
        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "peer": peer,
            "mail_from": mail_from,
            "rcpt_to": rcpt_to,
            "data": "\n".join(data_lines),
        }
        payload = json.dumps(record, ensure_ascii=True)
        async with self._lock:
            with self._output_path.open("a", encoding="utf8") as handle:
                handle.write(payload)
                handle.write("\n")


class SMTPConnectionState:
    """Tracks SMTP envelope state for one client connection."""

    def __init__(self) -> None:
        self.mail_from = ""
        self.rcpt_to: list[str] = []
        self.data_mode = False
        self.data_lines: list[str] = []

    def reset_envelope(self) -> None:
        """Reset current envelope state for next message."""
        self.mail_from = ""
        self.rcpt_to = []
        self.data_mode = False
        self.data_lines = []

    def reset_message_only(self) -> None:
        """Reset only DATA mode state while keeping envelope values."""
        self.data_mode = False
        self.data_lines = []


async def _send_line(writer: asyncio.StreamWriter, line: str) -> None:
    writer.write((line + "\r\n").encode("utf8"))
    await writer.drain()


def _strip_angle_brackets(value: str) -> str:
    return value.strip().lstrip("<").rstrip(">")


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    capture: SMTPMessageCapture,
) -> None:
    state = SMTPConnectionState()
    peer = writer.get_extra_info("peername")

    await _send_line(writer, "220 local-smtp-sink ESMTP ready")

    try:
        while not reader.at_eof():
            raw_line = await reader.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf8", errors="replace").rstrip("\r\n")

            if state.data_mode:
                if line == ".":
                    await capture.write(
                        peer=peer,
                        mail_from=state.mail_from,
                        rcpt_to=state.rcpt_to,
                        data_lines=state.data_lines,
                    )
                    state.reset_message_only()
                    await _send_line(writer, "250 2.0.0 Queued")
                    continue

                # SMTP dot-stuffing (RFC 5321 section 4.5.2).
                if line.startswith(".."):
                    line = line[1:]
                state.data_lines.append(line)
                continue

            command, sep, remainder = line.partition(" ")
            command = command.upper().strip()
            argument = remainder.strip() if sep else ""

            if command in {"EHLO", "HELO"}:
                await _send_line(writer, "250-local-smtp-sink")
                await _send_line(writer, "250 PIPELINING")
                continue

            if command == "NOOP":
                await _send_line(writer, "250 2.0.0 OK")
                continue

            if command == "RSET":
                state.reset_envelope()
                await _send_line(writer, "250 2.0.0 Reset")
                continue

            if command == "QUIT":
                await _send_line(writer, "221 2.0.0 Bye")
                break

            if command == "MAIL" and argument.upper().startswith("FROM:"):
                state.mail_from = _strip_angle_brackets(argument[5:].strip())
                state.rcpt_to = []
                await _send_line(writer, "250 2.1.0 Sender OK")
                continue

            if command == "RCPT" and argument.upper().startswith("TO:"):
                rcpt = _strip_angle_brackets(argument[3:].strip())
                state.rcpt_to.append(rcpt)
                await _send_line(writer, "250 2.1.5 Recipient OK")
                continue

            if command == "DATA":
                if not state.mail_from or not state.rcpt_to:
                    await _send_line(writer, "503 5.5.1 Need MAIL FROM and RCPT TO")
                    continue
                state.data_mode = True
                state.data_lines = []
                await _send_line(
                    writer,
                    "354 End data with <CR><LF>.<CR><LF>",
                )
                continue

            await _send_line(writer, "502 5.5.1 Command not implemented")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def _run_server(args: argparse.Namespace) -> int:
    output_path = Path(args.output).resolve()
    ready_path = Path(args.ready_file).resolve() if args.ready_file else None

    capture = SMTPMessageCapture(output_path=output_path)
    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, capture=capture),
        host=args.host,
        port=args.port,
    )

    sock = server.sockets[0]
    bound_host, bound_port = sock.getsockname()[0], sock.getsockname()[1]
    if ready_path is not None:
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        ready_payload = {
            "host": bound_host,
            "port": bound_port,
            "output": str(output_path),
        }
        ready_path.write_text(json.dumps(ready_payload), encoding="utf8")

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # add_signal_handler is unavailable on some platforms.
            pass

    async with server:
        await stop_event.wait()

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local SMTP sink and capture messages to JSON-lines.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ready-file")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.port < 0 or args.port > 65535:
        raise ValueError("port must be in range [0, 65535]")
    return asyncio.run(_run_server(args))


if __name__ == "__main__":
    raise SystemExit(main())
