# Foundry REST API Relay (ThreeHats), built from source so it runs on ARM.
# The official Docker image is Intel-only, so we compile it here.
# GitHub Actions builds this file and publishes the image to ghcr.io.
# Home Assistant then pulls that image, so the Pi never has to compile.
ARG RELAY_REF=3.4.1

# Stage 1: Go relay server
FROM golang:1.26-alpine AS builder
ARG RELAY_REF
RUN apk add --no-cache git ca-certificates
RUN git clone --depth 1 --branch ${RELAY_REF} \
    https://github.com/ThreeHats/foundryvtt-rest-api-relay.git /src
WORKDIR /src/go-relay
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /relay ./cmd/server/

# Stage 2: web dashboard (Astro)
FROM node:22-alpine AS frontend
ARG RELAY_REF
RUN apk add --no-cache git
RUN git clone --depth 1 --branch ${RELAY_REF} \
    https://github.com/ThreeHats/foundryvtt-rest-api-relay.git /src
WORKDIR /src/frontend
RUN corepack enable && pnpm install --frozen-lockfile && pnpm run build

# Stage 3: small runtime image
FROM alpine:3.21
RUN apk add --no-cache jq ca-certificates tzdata
WORKDIR /app
COPY --from=builder /relay /app/relay
COPY --from=builder /src/public/*.json /app/static/public/
COPY --from=frontend /src/public-dist/ /app/static/public-dist/
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
