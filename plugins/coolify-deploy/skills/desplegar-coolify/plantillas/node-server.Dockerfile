# Plantilla: servidor Node (Express, Hono, Fastify, NestJS…). Variables: {{NODE_VERSION}} {{PUERTO}}
# Requiere en package.json un script "start" (y "build" si es TypeScript). La app debe escuchar en 0.0.0.0.
FROM node:{{NODE_VERSION}}-slim AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build --if-present

FROM node:{{NODE_VERSION}}-slim
ENV NODE_ENV=production PORT={{PUERTO}} HOST=0.0.0.0
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi
COPY --from=build /app .
USER node
EXPOSE {{PUERTO}}
CMD ["npm", "start"]
