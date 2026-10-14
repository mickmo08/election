# syntax=docker/dockerfile:1.7
FROM node:22-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_OIDC_AUTHORITY
ARG NEXT_PUBLIC_OIDC_CLIENT_ID
# Rewrites are resolved into the build manifest, so the API origin is a build argument.
ARG ELECTION_API_ORIGIN=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 ELECTION_API_ORIGIN=${ELECTION_API_ORIGIN}
RUN npm run build

FROM node:22-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /src/.next/standalone ./
COPY --from=build --chown=node:node /src/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
