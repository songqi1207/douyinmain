FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH

RUN useradd -m -u 1000 user

WORKDIR $HOME/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=user requirements.txt $HOME/app/requirements.txt

USER user

RUN pip install --no-cache-dir -r $HOME/app/requirements.txt

COPY --chown=user . $HOME/app

EXPOSE 7860

CMD ["sh", "-c", "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT} app:app"]
