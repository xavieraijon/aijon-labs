# Plantilla: Next.js (next start). Variables: {{NODE_VERSION}} {{PUERTO}}
# Las variables NEXT_PUBLIC_* se incrustan al compilar: en Coolify deben estar disponibles en build.
FROM node:{{NODE_VERSION}}-slim AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:{{NODE_VERSION}}-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT={{PUERTO}} HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build /app .
USER node
EXPOSE {{PUERTO}}
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "{{PUERTO}}"]
