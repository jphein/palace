# Palace demo image: the web chat on the SYNTHETIC demo palace (PALACE_URL unset). Stdlib only.
# Build:  docker build -t palace-nemotron .
# Run:    docker run --rm -p 8080:8080 -e NEBIUS_API_KEY -e PALACE_MAX_ASKS_PER_HOUR=60 -e PALACE_MAX_ASKS_PER_DAY=200 palace-nemotron
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/jphein/palace" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.description="Palace: private personal AI on NVIDIA Nemotron via Nebius Token Factory"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# realm-sigil (LGPL-3.0) makes /version a sigil document; pinned to a commit, fetched as a tarball (no git in the image).
RUN pip install --no-cache-dir \
    "sigil.realm.watch @ https://github.com/jphein/sigil.realm.watch/archive/f3d7d9983fd1354521c2bdb414fe174e493dfb35.tar.gz#subdirectory=python"
WORKDIR /app
COPY palace ./palace
COPY demo ./demo
COPY LICENSE README.md pyproject.toml ./
ARG GIT_SHA=""
ARG GIT_BRANCH=""
ENV PALACE_GIT_SHA=$GIT_SHA PALACE_GIT_BRANCH=$GIT_BRANCH
RUN useradd --system --uid 10001 palace
USER palace
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/status',timeout=2).status==200 else 1)"
CMD ["python", "-m", "palace", "serve", "--host", "0.0.0.0", "--port", "8080"]
