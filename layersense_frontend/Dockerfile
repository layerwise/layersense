FROM oven/bun:1.3.5-debian AS deps

WORKDIR /app

COPY package.json bun.lock ./

RUN bun install --frozen-lockfile

FROM deps AS dev

COPY . .

EXPOSE 3000

CMD ["bun", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

FROM deps AS build

ARG VITE_AGENT_BASE=http://localhost:8000
ARG VITE_CONTROLLER_BASE=http://localhost:8001
ENV VITE_AGENT_BASE=${VITE_AGENT_BASE}
ENV VITE_CONTROLLER_BASE=${VITE_CONTROLLER_BASE}

COPY . .

RUN bun run build

FROM nginx:alpine AS prod

EXPOSE 80

COPY --from=build /app/dist /usr/share/nginx/html
