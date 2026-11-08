# The 3D viewer and the live timeline, served by nginx. Build context: twin/src/viewer
FROM node:22-slim AS build
WORKDIR /viewer
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /viewer/dist /usr/share/nginx/html
