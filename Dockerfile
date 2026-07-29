FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH

RUN useradd -m -u 1000 user

WORKDIR $HOME/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=user requirements.txt $HOME/app/requirements.txt

USER user

RUN pip install --no-cache-dir -r $HOME/app/requirements.txt

COPY --chown=user . $HOME/app
COPY --from=frontend-builder --chown=user /app/frontend/dist $HOME/app/frontend/dist

EXPOSE 7860

CMD ["sh", "-c", "uvicorn fastapi_app:app --host 0.0.0.0 --port ${PORT}"]
