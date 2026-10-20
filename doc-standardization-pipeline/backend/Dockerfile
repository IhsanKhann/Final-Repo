FROM node:20-slim

WORKDIR /usr/src/app

ENV NODE_ENV=production \
    PORT=8080

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE 8080

CMD ["node", "src/app.js"]
