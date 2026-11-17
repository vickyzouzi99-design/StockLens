FROM node:26-alpine AS build
WORKDIR /app/frontend
ENV NODE_OPTIONS=--max-old-space-size=512
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig*.json frontend/vite.config.ts ./
COPY frontend/src/ ./src/
COPY frontend/public/ ./public/
# No backend env files, API keys, build arguments or Vite dev server.
RUN npm run build

FROM caddy:2-alpine
ENV GOMEMLIMIT=128MiB
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/frontend/dist/ /srv/
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/
