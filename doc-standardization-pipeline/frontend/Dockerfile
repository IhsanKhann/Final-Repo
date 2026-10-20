# Stage 1: Build the Vite production bundle
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Stage 2: Serve with Nginx for Google Cloud Run
FROM nginx:alpine

ENV PORT=8080

# Template for dynamic Cloud Run port substitution
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy built static files
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["/bin/sh", "-c", "envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
