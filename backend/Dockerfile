FROM python:3.12-slim

# psycopg2 builds against libpq; weasyprint prints the evidence pdfs with pango
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libpq-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /backend

COPY uv.lock pyproject.toml ./

RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/backend/.venv/bin:$PATH"

COPY . .

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app app \
    && mkdir -p /beat \
    && chown app:app /beat

USER app
