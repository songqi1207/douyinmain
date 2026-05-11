FROM python:3.11-slim

# 米核 Key 通过运行时的环境变量 MIHE_KEY 注入（docker run -e / --env-file / compose env_file），勿写入镜像层
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 7860

CMD ["sh", "-c", "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT} app:app"]
