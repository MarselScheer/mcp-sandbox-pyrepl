#!/usr/bin/env python3
"""Spike: use attach_socket bidirectionally for JSON-RPC in container_rpc().

Tests the hypothesis that we can replace the current two-legged approach
(docker exec for write + container.logs() polling for read) with a single
attach_socket used bidirectionally.

Protocol:
  Write side — raw bytes to stdin (no frame header).
  Read side  — Docker-multiplexed frames (8-byte header + payload):
               Byte 0: stream type (1=stdout, 2=stderr)
               Bytes 1-3: reserved (zero)
               Bytes 4-7: payload length (big-endian uint32)
               Bytes 8..: payload

Expectation:
  - We can write a JSON-RPC request to stdin
  - Read the multiplexed stdout frame(s) back
  - Parse the JSON-RPC response and match by request id
"""

from __future__ import annotations

import io
import json
import socket
import struct
import time
from typing import Any

import docker


# ── helpers ──────────────────────────────────────────────────────────


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly *n* bytes from the socket (partial-read aware)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:  # EOF
            break
        buf.extend(chunk)
    return bytes(buf)


def _attach_raw_socket(container: Any) -> socket.socket:
    """Attach to the container and return a raw socket.socket.

    Handles the same three cases as ``RealDockerClient.container_stdin()``:
        1. socket.socket — use directly
        2. socket.SocketIO — unwrap via ._sock
        3. fallback — raise TypeError
    """
    sock = container.attach_socket(
        params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1}
    )
    if isinstance(sock, socket.socket):
        return sock
    if hasattr(sock, "_sock") and isinstance(sock._sock, socket.socket):
        return sock._sock
    msg = f"Unexpected attach_socket type: {type(sock)}"
    raise TypeError(msg)


def _read_docker_frame(
    sock: socket.socket,
) -> tuple[int, bytes] | None:
    """Read one Docker-multiplexed frame.

    Returns (stream_type, payload) or None on EOF/timeout.

    stream_type: 1=stdout, 2=stderr
    """
    header = _recv_exact(sock, 8)
    if len(header) < 8:
        return None  # EOF or connection closed
    stream_type = header[0]
    # header[1:4] is reserved (should be zero)
    payload_len = struct.unpack(">I", header[4:8])[0]
    payload = _recv_exact(sock, payload_len)
    if len(payload) < payload_len:
        return None  # truncated — connection closed mid-frame
    return stream_type, payload


# ── main spike ───────────────────────────────────────────────────────


def main() -> None:
    client = docker.from_env()
    print("✓ connected to docker daemon")

    # 1. Create a container
    container = client.containers.run(
        "sandbox-base:3.12",
        detach=True,
        stdin_open=True,
        command=["python3", "-m", "entrypoint"],
    )
    try:
        cid = container.id[:12]
        print(f"✓ container started: {cid}")

        # Give the entrypoint a moment to boot
        time.sleep(2)

        # 2. Attach raw socket
        sock = _attach_raw_socket(container)
        sock.settimeout(5.0)
        print(f"✓ raw socket acquired: {type(sock)}")

        # 3. Send a JSON-RPC "ping" request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ping",
            "params": {},
        }
        request_bytes = (json.dumps(request) + "\n").encode("utf-8")
        sock.sendall(request_bytes)
        print(f"✓ sent request: {json.dumps(request)}")

        # 4. Read frames, looking for the matching response
        response: dict[str, Any] | None = None
        stderr_output: list[str] = []
        frame_count = 0
        t0 = time.perf_counter()

        while response is None:
            frame = _read_docker_frame(sock)
            if frame is None:
                print("✗ connection closed / EOF before response received")
                break
            stream_type, payload = frame
            frame_count += 1
            text = payload.decode("utf-8", errors="replace")

            if stream_type == 1:  # stdout
                print(f"  [frame {frame_count}] stdout ({len(payload)}b): {text!r}")
                # Could be multiple lines — try each
                for line in text.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        if isinstance(parsed, dict) and parsed.get("id") == 1:
                            response = parsed
                            break
                    except json.JSONDecodeError:
                        # Might be partial line or debug output
                        pass
            elif stream_type == 2:  # stderr
                stderr_output.append(text)
                print(f"  [frame {frame_count}] stderr ({len(payload)}b): {text!r}")
            else:
                print(f"  [frame {frame_count}] type={stream_type} ({len(payload)}b): {text!r}")

        elapsed = time.perf_counter() - t0
        print(f"\nread {frame_count} frames in {elapsed:.3f}s")

        if response:
            print(f"\n✓ MATCHED RESPONSE: {json.dumps(response, indent=2)}")
        else:
            print(f"\n✗ NO RESPONSE MATCHED")
            if stderr_output:
                print(f"  stderr collected: {stderr_output}")

        # 5. Clean test: send shutdown
        shutdown_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "shutdown",
            "params": {},
        }
        sock.sendall((json.dumps(shutdown_req) + "\n").encode("utf-8"))
        print("\n✓ sent shutdown — container should exit soon")
        time.sleep(1)

    finally:
        container.remove(force=True)
        print("✓ container removed")


if __name__ == "__main__":
    main()