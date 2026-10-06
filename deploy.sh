#!/bin/bash

set -e

APP_NAME="tripweave"
APP_DIR="/opt/projects/tripweave"
APP_PORT="8000"

cd "$APP_DIR"

echo "==> Pulling latest code..."
git pull origin main

echo "==> Building Docker image..."
docker build -t "${APP_NAME}:latest" .

echo "==> Stopping existing container..."
docker stop "$APP_NAME" 2>/dev/null || true

echo "==> Removing existing container..."
docker rm "$APP_NAME" 2>/dev/null || true

echo "==> Starting new container..."
docker run -d \
  --name "$APP_NAME" \
  --env-file .env \
  --restart unless-stopped \
  -p 127.0.0.1:${APP_PORT}:${APP_PORT} \
  "${APP_NAME}:latest"

echo "==> Deployment successful."
docker ps --filter "name=${APP_NAME}"