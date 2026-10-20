# Full RoboVerse Studio (API + WebSocket co-simulation + built UI) in one container.
# Deploy on any host that runs long-lived containers with WebSockets (Render, Railway, Fly.io).
FROM node:22-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=ui /app/frontend/dist /app/frontend/dist
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn roboverse.main:app --host 0.0.0.0 --port ${PORT}"]
