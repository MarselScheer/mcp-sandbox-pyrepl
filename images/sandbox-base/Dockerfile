ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# Install uv (Rust-based Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create sandbox user with UID 1000
RUN addgroup --system --gid 1000 sandbox && \
    adduser --system --uid 1000 --gid 1000 --home /home/sandbox sandbox

# Create writable directories for data, session venv, and user home
RUN mkdir -p /data /session && \
    chown -R sandbox:sandbox /data /session /home/sandbox

# Copy the REPL entrypoint
COPY entrypoint.py /entrypoint.py

# Switch to non-root user
USER sandbox
WORKDIR /home/sandbox

# Create a uv-managed virtual environment for the session
RUN uv venv /session/venv --python python${PYTHON_VERSION}

# Ensure the venv is activated by default for the entrypoint
ENV VIRTUAL_ENV=/session/venv
ENV PATH="/session/venv/bin:$PATH"

ENTRYPOINT ["python", "/entrypoint.py"]