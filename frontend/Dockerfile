FROM node:22-alpine AS build
WORKDIR /app

# No build arguments by design. Revision URLs are runtime configuration served
# by the API, so one image is valid in Compose and on Cloud Run alike.
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
