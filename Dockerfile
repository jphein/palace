# Palace demo image: the web chat on the SYNTHETIC demo palace (PALACE_URL unset). Stdlib only.
# Build:  docker build -t palace-nemotron .
# Run:    docker run --rm -p 8080:8080 -e NEBIUS_API_KEY -e PALACE_MAX_ASKS_PER_HOUR=120 palace-nemotron
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/jphein/palace" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.description="Palace: private personal AI on NVIDIA Nemotron via Nebius Token Factory"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY palace ./palace
COPY demo ./demo
COPY LICENSE README.md pyproject.toml ./
RUN useradd --system --uid 10001 palace
USER palace
EXPOSE 8080
CMD ["python", "-m", "palace", "serve", "--host", "0.0.0.0", "--port", "8080"]
