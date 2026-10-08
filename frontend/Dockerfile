FROM node:22-alpine AS build
WORKDIR /app

# Vite inlines VITE_* at build time, so revision URLs must be present here.
ARG VITE_USE_LIVE_TARGETS=false
ARG VITE_STABLE_LATENCY_URL=""
ARG VITE_CANDIDATE_LATENCY_URL=""
ARG VITE_STABLE_CONTRACT_URL=""
ARG VITE_CANDIDATE_CONTRACT_URL=""
ENV VITE_USE_LIVE_TARGETS=${VITE_USE_LIVE_TARGETS} \
    VITE_STABLE_LATENCY_URL=${VITE_STABLE_LATENCY_URL} \
    VITE_CANDIDATE_LATENCY_URL=${VITE_CANDIDATE_LATENCY_URL} \
    VITE_STABLE_CONTRACT_URL=${VITE_STABLE_CONTRACT_URL} \
    VITE_CANDIDATE_CONTRACT_URL=${VITE_CANDIDATE_CONTRACT_URL}

COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache gettext
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["/entrypoint.sh"]
