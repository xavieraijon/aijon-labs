# Template: Next.js (next start). Variables: {{NODE_VERSION}} {{PORT}}
# NEXT_PUBLIC_* variables are inlined at build time: in Coolify they must be available at build time.
FROM node:{{NODE_VERSION}}-slim AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:{{NODE_VERSION}}-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT={{PORT}} HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build /app .
USER node
EXPOSE {{PORT}}
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "{{PORT}}"]
