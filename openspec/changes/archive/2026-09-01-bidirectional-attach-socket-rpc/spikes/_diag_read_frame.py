#!/usr/bin/env python3
"""Diagnostic: test my _read_frame and _recv_exact against a real container."""
from __future__ import annotations

import json
import socket
import struct
import time
import sys

import docker


# ── My implementation (from docker_adapter.py) ─────


def _recv_exact_my(sock: socket.socket, n: int) -> bytes:
    chunks = []
    while n > 0:
        chunk = sock.recv(n)
        if not chunk:
            msg = f"Connection closed after reading {sum(len(c) for c in chunks)} bytes, expected more"
            raise ConnectionError(msg)
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


def _read_frame_my(sock: socket.socket) -> tuple[int, bytes] | None:
    header = sock.recv(8)
    if not header:
        return None
    if len(header) < 8:
        header = header + _recv_exact_my(sock, 8 - len(header))
    stream_type = header[0]
    payload_len = struct.unpack(">I", header[4:8])[0]
    if payload_len == 0:
        return stream_type, b""
    payload = _recv_exact_my(sock, payload_len)
    return stream_type, payload


# ── Spike's implementation ─────────────────────────


def _recv_exact_spike(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _read_frame_spike(sock: socket.socket) -> tuple[int, bytes] | None:
    header = _recv_exact_spike(sock, 8)
    if len(header) < 8:
        return None
    stream_type = header[0]
    payload_len = struct.unpack(">I", header[4:8])[0]
    payload = _recv_exact_spike(sock, payload_len)
    if len(payload) < payload_len:
        return None
    return stream_type, payload


# ── Test harness ───────────────────────────────────


def test_read_method(name: str, recv_exact_fn, read_frame_fn):
    client = docker.from_env()
    container = client.containers.run(
        "sandbox-base:3.12",
        detach=True,
        stdin_open=True,
        command=["python3", "-m", "entrypoint"],
    )
    try:
        cid = container.id[:12]
        time.sleep(2)

        sock = container.attach_socket(
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1}
        )
        if isinstance(sock, socket.socket):
            raw = sock
        elif hasattr(sock, "_sock") and isinstance(sock._sock, socket.socket):
            raw = sock._sock
        else:
            print(f"  {name}: unexpected socket type {type(sock)}")
            return
        raw.settimeout(10.0)

        # Send ping
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        raw.sendall((req + "\n").encode("utf-8"))

        # Read frames
        frame = read_frame_fn(raw)
        if frame is None:
            print(f"  {name}: no frame")
            return
        stype, payload = frame
        payload_text = payload.decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(payload_text)
            print(f"  {name}: OK — id={parsed.get('id')}, match={parsed.get('id') == 1}")
            print(f"         payload={payload_text[:120]}")
        except json.JSONDecodeError as e:
            print(f"  {name}: JSON ERROR — {e}")
            print(f"         raw payload={payload_text[:200]!r}")

        # Send exec
        req2 = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "exec", "params": {"code": "[1, 2, 3]"}})
        raw.sendall((req2 + "\n").encode("utf-8"))

        frame = read_frame_fn(raw)
        if frame is None:
            print(f"  {name}: no frame for exec")
            return
        stype, payload = frame
        payload_text = payload.decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(payload_text)
            result = parsed.get("result", {})
            print(f"  {name} exec: display={result.get('display')}")
        except json.JSONDecodeError as e:
            print(f"  {name} exec: JSON ERROR — {e}")
            print(f"         raw payload={payload_text[:200]!r}")
            
    finally:
        container.remove(force=True)


if __name__ == "__main__":
    print("=== Testing MY implementation ===")
    test_read_method("my", _recv_exact_my, _read_frame_my)
    print()
    print("=== Testing SPIKE implementation ===")
    test_read_method("spike", _recv_exact_spike, _read_frame_spike)