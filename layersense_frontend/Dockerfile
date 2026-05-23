FROM node:25-bookworm-slim AS deps

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

FROM deps AS dev

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

FROM deps AS build

ARG VITE_AGENT_BASE=http://localhost:8000
ARG VITE_CONTROLLER_BASE=http://localhost:8001
ENV VITE_AGENT_BASE=${VITE_AGENT_BASE}
ENV VITE_CONTROLLER_BASE=${VITE_CONTROLLER_BASE}

COPY . .

RUN npm run build

FROM nginx:alpine AS prod

COPY --from=build /app/dist /usr/share/nginx/html
