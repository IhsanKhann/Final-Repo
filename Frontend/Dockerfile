# Stage 1: Build the Vite production bundle
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# VITE_* values are compiled into the bundle, so the backend URL has to be known at
# BUILD time, not run time. Without this the image ships pointing at localhost:8000 and
# every request from a visitor hits their own machine -- the page loads and every panel
# is empty, which looks like a backend outage rather than a build mistake.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN echo "VITE_API_URL=${VITE_API_URL}" > .env && npm run build

# Stage 2: Serve with Nginx for Google Cloud Run
FROM nginx:alpine

ENV PORT=8080

# Template for dynamic Cloud Run port substitution
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy built static files
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["/bin/sh", "-c", "envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
