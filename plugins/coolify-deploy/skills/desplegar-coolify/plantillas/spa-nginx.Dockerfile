# Plantilla: SPA (Angular, Vite/React/Vue, CRA) compilada y servida con nginx.
# Variables: {{NODE_VERSION}} {{BUILD_CMD}} {{BUILD_DIR}}
FROM node:{{NODE_VERSION}}-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN {{BUILD_CMD}}

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/{{BUILD_DIR}} /usr/share/nginx/html
EXPOSE 80
