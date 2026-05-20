# -----------------------------------------------------------------------------
# Base image: node:18-slim + python3 (apt-installed).
# Both runtimes are required because server.js (Node) spawns Python scripts.
# Refdata sync CronJobs override CMD with `python /opt/app/scripts/<sync>.py`.
# -----------------------------------------------------------------------------
FROM public.ecr.aws/docker/library/node:22-slim AS base

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=300 \
    BUILD_DIR="/var/build" \
    RUNTIME_DIR="/opt/app" \
    VENV_DIR="/opt/.venv"

ENV PATH="$VENV_DIR/bin:$PATH"

# Python runtime + libpq for psycopg2-binary. ca-certificates so TLS to MySQL/PG works.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY ./docker/pip.conf /etc/pip.conf
COPY ./docker/docker-entrypoint.sh /opt/docker-entrypoint.sh
RUN chmod +x /opt/docker-entrypoint.sh


# -----------------------------------------------------------------------------
# Build stage: install Node + Python deps, build the React bundle.
# -----------------------------------------------------------------------------
FROM base AS build

WORKDIR $BUILD_DIR

# Python venv with locked deps.
RUN python3 -m venv $VENV_DIR
COPY ./requirements-freeze.txt requirements-freeze.txt
RUN . $VENV_DIR/bin/activate \
    && python -m pip install --upgrade pip \
    && pip install -r requirements-freeze.txt

# Node deps. Copy lockfile first for layer caching.
COPY ./package.json ./package-lock.json* ./
RUN npm ci --no-audit --no-fund

# App source + Vite build.
COPY ./index.html ./vite.config.js ./
COPY ./src ./src
COPY ./public ./public
RUN npm run build


# -----------------------------------------------------------------------------
# Production stage: minimal runtime layer.
# Contains: node_modules, Python venv, server.js, scripts/, public/, dist/.
# No source maps, no tests, no docs.
# -----------------------------------------------------------------------------
FROM base AS production

WORKDIR $RUNTIME_DIR

# Production node_modules (server.js uses only built-ins, but reinstall for
# any future deps; --omit=dev drops vite/tailwind/etc.).
COPY ./package.json ./package-lock.json* ./
RUN npm ci --omit=dev --no-audit --no-fund \
    && npm cache clean --force

# Python venv from build stage.
COPY --from=build $VENV_DIR $VENV_DIR

# Runtime code.
COPY ./server.js ./
COPY ./scripts ./scripts
COPY ./public ./public

# Built React bundle from build stage.
COPY --from=build $BUILD_DIR/dist ./dist

# Non-root user (UID 10001 matches tokka platform convention).
RUN useradd --no-create-home --uid 10001 --user-group --shell /usr/sbin/nologin app \
    && chown -R app:app $RUNTIME_DIR
USER app

EXPOSE 5181

ENTRYPOINT ["/opt/docker-entrypoint.sh"]
CMD ["node", "server.js"]


# -----------------------------------------------------------------------------
# Test stage: build target=test in CI to run pytest inside the container.
# -----------------------------------------------------------------------------
FROM build AS test

WORKDIR $BUILD_DIR

# Install test-only deps. requirements-dev.txt does `-r requirements.txt`
# so the runtime deps (already installed in this venv from the build
# stage's requirements-freeze.txt) still need the file present on disk
# for pip to resolve the reference. Both files are copied.
COPY ./requirements.txt ./requirements.txt
COPY ./requirements-dev.txt ./requirements-dev.txt
RUN . $VENV_DIR/bin/activate \
    && pip install -r requirements-dev.txt

# Bring tests into the test image (excluded from production).
COPY ./tests ./tests

CMD ["python", "-m", "pytest", "tests/", "-vv"]
