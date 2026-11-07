# Template: Node server (Express, Hono, Fastify, NestJS…). Variables: {{NODE_VERSION}} {{PORT}}
# Requires a "start" script in package.json (and "build" for TypeScript). The app must listen on 0.0.0.0.
FROM node:{{NODE_VERSION}}-slim AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build --if-present

FROM node:{{NODE_VERSION}}-slim
ENV NODE_ENV=production PORT={{PORT}} HOST=0.0.0.0
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi
COPY --from=build /app .
USER node
EXPOSE {{PORT}}
CMD ["npm", "start"]
