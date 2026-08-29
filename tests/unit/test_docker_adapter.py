"""Unit tests for DockerFrameReader — pure socket I/O, no Docker needed.

Uses ``socket.socketpair()`` to create connected sockets directly,
so tests are fast and need zero infrastructure.
"""

from __future__ import annotations

import socket
import struct

import pytest

from docker_adapter import DockerFrameReader


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def reader() -> DockerFrameReader:
    """A fresh frame reader (stateless, shared per test is fine)."""
    return DockerFrameReader()


@pytest.fixture
def sockets() -> tuple[socket.socket, socket.socket]:
    """A pair of connected sockets.  Yields (writer, reader).

    The test should write test data to the *writer* and read
    from the *reader* via the DockerFrameReader.
    """
    a, b = socket.socketpair()
    yield a, b
    a.close()
    b.close()


# ── Helpers ──────────────────────────────────────────────────────────


def _write_frame(writer: socket.socket, stream_type: int, payload: bytes) -> None:
    """Write a single Docker-multiplexed frame to *writer*."""
    header = struct.pack(">B3sI", stream_type, b"\x00\x00\x00", len(payload))
    writer.sendall(header + payload)


# ── recv_exact ───────────────────────────────────────────────────────


class TestRecvExact:
    def test_reads_exact_bytes(self, reader: DockerFrameReader, sockets: tuple) -> None:
        """Happy path: reading exactly N bytes from a socket succeeds."""
        writer, reader_sock = sockets
        writer.sendall(b"hello")
        result = reader.recv_exact(reader_sock, 5)
        assert result == b"hello"

    def test_eof_raises_connection_error(
        self, reader: DockerFrameReader, sockets: tuple
    ) -> None:
        """Reading from a closed socket raises ConnectionError."""
        writer, reader_sock = sockets
        writer.close()
        with pytest.raises(ConnectionError, match="Connection closed"):
            reader.recv_exact(reader_sock, 10)
        reader_sock.close()

    def test_partial_reads_accumulate(
        self, reader: DockerFrameReader, sockets: tuple
    ) -> None:
        """Multiple short recv() calls are accumulated correctly."""
        writer, reader_sock = sockets
        writer.sendall(b"hello world")
        result = reader.recv_exact(reader_sock, 11)
        assert result == b"hello world"


# ── read_frame ───────────────────────────────────────────────────────


class TestReadFrame:
    def test_full_frame(self, reader: DockerFrameReader, sockets: tuple) -> None:
        """A complete Docker frame with non-zero payload is parsed."""
        writer, reader_sock = sockets
        _write_frame(writer, 1, b'{"ok":true}')
        frame = reader.read_frame(reader_sock)
        assert frame is not None
        stream_type, payload = frame
        assert stream_type == 1
        assert payload == b'{"ok":true}'

    def test_zero_payload(self, reader: DockerFrameReader, sockets: tuple) -> None:
        """A frame with zero-length payload is parsed correctly."""
        writer, reader_sock = sockets
        _write_frame(writer, 1, b"")
        frame = reader.read_frame(reader_sock)
        assert frame is not None
        stream_type, payload = frame
        assert stream_type == 1
        assert payload == b""

    def test_returns_none_on_empty_recv(
        self, reader: DockerFrameReader, sockets: tuple
    ) -> None:
        """Reading from a closed socket returns None."""
        writer, reader_sock = sockets
        writer.close()
        frame = reader.read_frame(reader_sock)
        assert frame is None
        reader_sock.close()

    def test_stderr_type(self, reader: DockerFrameReader, sockets: tuple) -> None:
        """A stderr frame (type 2) is parsed — only the type field differs."""
        writer, reader_sock = sockets
        _write_frame(writer, 2, b"traceback")
        frame = reader.read_frame(reader_sock)
        assert frame is not None
        stream_type, payload = frame
        assert stream_type == 2
        assert payload == b"traceback"

    def test_partial_header_accumulates(
        self, reader: DockerFrameReader, sockets: tuple
    ) -> None:
        """A header received in two parts is still parsed correctly.

        Uses a wrapper that limits the first ``recv(8)`` to return only
        4 bytes, forcing the ``len(header) < 8`` branch that calls
        ``recv_exact`` for the remaining 4 bytes.
        """

        class _PartialRecvSocket:
            """Wraps a real socket but returns limited data on first recv."""

            def __init__(self, wrapped: socket.socket) -> None:
                self._wrapped = wrapped
                self._first = True

            def recv(self, n: int) -> bytes:
                if self._first:
                    self._first = False
                    return self._wrapped.recv(4)
                return self._wrapped.recv(n)

        writer, reader_sock = sockets
        _write_frame(writer, 1, b"hello")
        wrapped = _PartialRecvSocket(reader_sock)
        frame = reader.read_frame(wrapped)  # type: ignore[arg-type]
        assert frame is not None
        stream_type, payload = frame
        assert stream_type == 1
        assert payload == b"hello"