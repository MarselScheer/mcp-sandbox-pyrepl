#!/usr/bin/env python3
"""Spike: Verify whether Docker attach_socket(params={stdout: 1, stream: 1})
adds 8-byte multiplexing frame headers.

Docker only adds the 8-byte header (stream type [1 byte] + pad [3 bytes] +
payload length [4 bytes]) when stdout AND stderr are both streamed.
With only stdout requested, the data should be raw — but we verify.

Usage:
    python spike_attach_headers.py
"""

from __future__ import annotations

import socket
import time

from docker import DockerClient
from docker.models.containers import Container


def _set_timeout(sock: socket.SocketIO, timeout: float) -> None:
    """Set a timeout on a SocketIO by accessing its underlying socket."""
    try:
        # SocketIO wraps a real socket — access via private attr as fallback
        raw = sock._sock  # type: ignore[attr-defined]
        if isinstance(raw, socket.socket):
            raw.settimeout(timeout)
            print(f"  (set timeout={timeout}s on underlying socket)")
    except AttributeError:
        pass


def main() -> None:
    client = DockerClient.from_env()
    image = "sandbox-base:latest"

    print(f"Creating container from {image}...")
    container: Container = client.containers.create(
        image=image,
        # No command needed — ENTRYPOINT in Dockerfile runs /entrypoint.py
        stdin_open=True,
        detach=True,
    )
    container.start()
    time.sleep(1)  # Let the entrypoint boot

    # IMPORTANT: Open stdout socket FIRST, before sending the request.
    # The socket only gets data written from the moment it connects.
    print("Attaching stdout socket (params={stdout: 1, stream: 1})...")
    stdout_sock = container.attach_socket(params={"stdout": 1, "stream": 1})
    print(f"Return type: {type(stdout_sock).__name__}")
    _set_timeout(stdout_sock, 5.0)

    print("Sending a ping request via exec (spike only)...")
    result = container.exec_run(
        [
            "python3",
            "-c",
            """import os
req = '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
with open('/proc/1/fd/0', 'w') as f:
    f.write(req + '\\n')
    f.flush()
    os.fsync(f.fileno())
""",
        ]
    )
    print(f"  exec exit_code={result.exit_code}")
    stderr = (result.output.decode() if isinstance(result.output, bytes) else result.output)
    if stderr.strip():
        print(f"  exec stderr: {stderr!r}")

    # Read from the already-open stdout socket
    print("  reading from stdout socket...")
    try:
        first_bytes = stdout_sock.read(16)
        print(f"  read returned {len(first_bytes)} bytes")
    except socket.timeout:
        print("  timed out reading from stdout socket!")
        first_bytes = b""

    stdout_sock.close()

    if not first_bytes:
        # Fallback: check container logs
        print("  checking container.logs() as fallback...")
        logs = container.logs(stdout=True, stderr=False, tail=10).decode("utf-8")
        print(f"  logs: {logs!r}")
    else:
        print(f"First 16 bytes (hex): {first_bytes.hex()}")
        print(f"First 16 bytes (repr): {first_bytes!r}")
        print(f"First byte: {first_bytes[0]:02x} = {chr(first_bytes[0])!r}")

        if first_bytes and first_bytes[0:1] == b"{":
            print("\n✓ No 8-byte headers detected — output is raw JSON")
            print("  Design assumption confirmed.")
        elif len(first_bytes) >= 8:
            stream_type = first_bytes[0]
            pad = first_bytes[1:4]
            payload_len = int.from_bytes(first_bytes[4:8], "big")
            print(f"\n✗ 8-byte headers detected!")
            print(f"  Stream type: {stream_type} (1=stdin, 2=stdout, 3=stderr)")
            print(f"  Padding: {pad}")
            print(f"  Payload length: {payload_len}")
            print("  Need to strip headers before JSON parsing.")
        else:
            print(f"\n⚠ Unexpected data: {first_bytes}")

    container.remove(force=True)
    print("\nDone.")


if __name__ == "__main__":
    main()