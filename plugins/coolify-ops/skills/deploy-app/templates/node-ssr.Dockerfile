# Template: Node SSR server (Nuxt, Astro, SvelteKit, Angular SSR, React Router).
# Variables: {{NODE_VERSION}} {{BUILD_CMD}} {{BUILD_DIR}} {{START_CMD}} {{PORT}} {{EXTRA_ENV}}
# The run stage keeps the build output at the same path under /app, so relative paths in the bundle still resolve.
FROM node:{{NODE_VERSION}}-slim AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN {{BUILD_CMD}}

FROM node:{{NODE_VERSION}}-slim
ENV NODE_ENV=production PORT={{PORT}} HOST=0.0.0.0{{EXTRA_ENV}}
WORKDIR /app
COPY package*.json ./
# --ignore-scripts: postinstall/prepare hooks (nuxt prepare, svelte-kit sync) need sources and dev tools; they ran in the build stage
RUN if [ -f package-lock.json ]; then npm ci --omit=dev --ignore-scripts; else npm install --omit=dev --ignore-scripts; fi
COPY --from=build /app/{{BUILD_DIR}} ./{{BUILD_DIR}}
USER node
EXPOSE {{PORT}}
CMD {{START_CMD}}
