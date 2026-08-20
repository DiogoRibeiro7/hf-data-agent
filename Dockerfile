# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- builder ----
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# pyproject reads the version from src/data_agent/__init__.py and the metadata
# from README.md / LICENSE, so all four are needed to build the wheel.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[mcp]"

# ---------------------------------------------------------------- runtime ----
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="hf-data-agent" \
      org.opencontainers.image.description="Open-source-LLM data agent with RAG and live data platform tools" \
      org.opencontainers.image.source="https://github.com/DiogoRibeiro7/hf-data-agent" \
      org.opencontainers.image.licenses="MIT"

# A container has to bind all interfaces for `-p` to reach it. That makes the
# port routable, so startup refuses unless DA_API_TOKEN is set, or
# DA_ALLOW_UNAUTHENTICATED=true declares the port protected some other way.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DA_API_HOST=0.0.0.0

# Run unprivileged. The agent only needs to write under /app/data.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin agent

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=agent:agent data ./data
COPY --chown=agent:agent scripts ./scripts

USER agent
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["python", "-m", "data_agent.entrypoints.run_api"]
