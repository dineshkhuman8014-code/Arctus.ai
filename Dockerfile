# Arctus.ai — public container for Hugging Face Spaces / Docker Hub
# Non-root, port 7860. Server reads provider keys from env (HF Spaces Secrets).
# Includes OmniRoute (npm) for local 160+ provider routing on port 20128.
#
# Build:  docker build -t arctus-ai .
# Run:    docker run -p 7860:7860 -p 20128:20128 -e OPENAI_API_KEY=sk-... arctus-ai
#         (port 20128 = OmniRoute; only expose if you want direct access)

FROM node:22-slim AS node-builder

# Install OmniRoute globally into a temporary prefix so we can copy it out.
RUN npm install -g --prefix /opt/omniroute omniroute

# ---------- Python image ----------
FROM python:3.11-slim AS base

# Never run as root
RUN groupadd -r arctus && useradd -r -g arctus -u 1000 -m -d /home/arctus arctus

# Copy Node runtime + OmniRoute from the node-builder stage.
# (OmniRoute is a Node app; we keep a minimal Node runtime alongside Python.)
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
COPY --from=node-builder /opt/omniroute /opt/omniroute
ENV PATH="/opt/omniroute/bin:${PATH}"
ENV OMNIROUTE_HOME="/home/arctus/.config/omniroute"

WORKDIR /app

# Install the server extras only (keep image lean)
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -e ".[server]"

# Copy the package, server, and web assets
COPY arctus/ ./arctus/
COPY server/ ./server/
COPY web/ ./web/

# Config + sessions go to a writable volume inside the container
ENV ARCTUS_HOME=/data
RUN mkdir -p /data /home/arctus/.config/omniroute && \
    chown -R arctus:arctus /data /app /home/arctus
VOLUME /data

USER arctus

# OmniRoute listens on 20128 internally.
EXPOSE 20128
# Arctus FastAPI dashboard on 7860.
EXPOSE 7860

# Start OmniRoute in background, then the FastAPI server in foreground.
CMD ["sh", "-c", "omniroute setup --non-interactive 2>/dev/null || true; \
              omniroute &; \
              sleep 2; \
              python -m server.app"]
