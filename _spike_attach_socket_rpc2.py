#!/usr/bin/env python3
"""Spike 2: exec call + multi-frame edge case."""

import json, socket, struct, time
from typing import Any
import docker


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _attach_raw_socket(container: Any) -> socket.socket:
    sock = container.attach_socket(
        params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1}
    )
    if isinstance(sock, socket.socket):
        return sock
    if hasattr(sock, "_sock") and isinstance(sock._sock, socket.socket):
        return sock._sock
    raise TypeError(f"Unexpected type: {type(sock)}")


def _read_frame(sock):
    header = _recv_exact(sock, 8)
    if len(header) < 8:
        return None
    stream_type = header[0]
    payload_len = struct.unpack(">I", header[4:8])[0]
    payload = _recv_exact(sock, payload_len)
    if len(payload) < payload_len:
        return None
    return stream_type, payload


def send_rpc(sock, req_id, method, params=None):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
    return req


def read_response(sock, expected_id, timeout=5.0):
    sock.settimeout(timeout)
    t0 = time.perf_counter()
    while True:
        frame = _read_frame(sock)
        if frame is None:
            return None, time.perf_counter() - t0
        stype, payload = frame
        if stype != 1:  # skip stderr
            continue
        text = payload.decode("utf-8", errors="replace")
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict) and parsed.get("id") == expected_id:
                    return parsed, time.perf_counter() - t0
            except json.JSONDecodeError:
                pass


def main():
    client = docker.from_env()
    container = client.containers.run(
        "sandbox-base:3.12", detach=True, stdin_open=True,
        command=["python3", "-m", "entrypoint"],
    )
    try:
        cid = container.id[:12]
        print(f"container: {cid}")
        time.sleep(2)

        sock = _attach_raw_socket(container)
        print(f"socket: {type(sock)}")

        # --- Test 1: ping (already proven) ---
        print("\n─── Test 1: ping ───")
        sent = send_rpc(sock, 1, "ping")
        resp, elapsed = read_response(sock, 1)
        print(f"  ping => {json.dumps(resp)} ({elapsed*1000:.1f}ms)")

        # --- Test 2: exec "42 + 1" ---
        print("\n─── Test 2: exec 42+1 ───")
        sent = send_rpc(sock, 2, "exec", {"code": "42 + 1", "timeout": 10})
        resp, elapsed = read_response(sock, 2)
        print(f"  exec => {json.dumps(resp)} ({elapsed*1000:.1f}ms)")

        # --- Test 3: exec with larger output ---
        print("\n─── Test 3: exec large output ───")
        sent = send_rpc(sock, 3, "exec", {"code": "print('hello' * 100)", "timeout": 10})
        resp, elapsed = read_response(sock, 3)
        r = (resp or {}).get("result", {})
        print(f"  exec len(stdout)={len(r.get('stdout',''))} ({elapsed*1000:.1f}ms)")
        print(f"  display: {r.get('display')}")

        # --- Test 4: exec with stderr (error) ---
        print("\n─── Test 4: exec with syntax error ───")
        sent = send_rpc(sock, 4, "exec", {"code": "1 / 0", "timeout": 10})
        resp, elapsed = read_response(sock, 4)
        r = (resp or {}).get("result", {})
        print(f"  error: {r.get('error', '')[:60]}...")
        print(f"  stderr: {r.get('stderr', '')[:60]}...")

        # --- Test 5: install a package ---
        print("\n─── Test 5: install packages ───")
        # Network connect first — the container was created with default bridge
        # but we disconnected it. Actually we didn't — but just in case...
        sent = send_rpc(sock, 5, "install", {"packages": [{"name": "pytz"}]})
        resp, elapsed = read_response(sock, 5, timeout=15.0)
        r = (resp or {}).get("result", {})
        print(f"  install error: {r.get('error', 'None')} ({elapsed*1000:.1f}ms)")

        print("\n─── All tests complete ───")

    finally:
        try:
            # No need to send shutdown — just remove with force
            pass
        finally:
            container.remove(force=True)
            print("container removed")


if __name__ == "__main__":
    main()
