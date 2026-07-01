# Minimal image for the ssh-terminal bridge. Build with:
#   az acr build --registry <acr-name> --image ssh-terminal:latest .
# (runs the build in the cloud via ACR Tasks -- no local Docker needed)
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY server.js ./
COPY public ./public

ENV PORT=8080
ENV HOST=0.0.0.0
EXPOSE 8080

CMD ["node", "server.js"]
