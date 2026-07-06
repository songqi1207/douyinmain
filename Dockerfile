FROM python:3.11-slim

# 米核 Key 通过运行时的环境变量 MIHE_KEY 注入（docker run -e / --env-file / compose env_file），勿写入镜像层
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# /api/generate_god 通过 subprocess 调用 generate-god-template.js，需要 node 运行时
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

EXPOSE 7860

CMD ["sh", "-c", "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT} app:app"]
