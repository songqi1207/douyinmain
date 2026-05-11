---
title: Dy Tt
emoji: ⚡
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

## 米核 Key（部署与更换）

应用通过环境变量 **`MIHE_KEY`** 读取米核 API Key（见 `app.py`）。**不要**把真实 Key 写进代码或提交到 Git。

### 重新部署时要换 Key

1. 在部署平台里改环境变量 **`MIHE_KEY`** 为新 Key，保存后触发重新部署（或重启实例）。
2. **Hugging Face Space**：打开 Space → **Settings** → **Variables and secrets** → 新增或编辑 **`MIHE_KEY`**（建议设为 *Secret*）→ 保存后 **Factory reboot** 或等待自动重建。
3. **Render**：Dashboard → 对应 Web Service → **Environment** → 编辑 **`MIHE_KEY`** → 保存后会自动重新部署（本仓库 `render.yaml` 已声明该变量，`sync: false` 表示值在控制台填写）。
4. 本地运行：复制 `env.example` 为 `.env`，填写 `MIHE_KEY=你的key`。

### Docker 部署（本仓库含 `Dockerfile`）

镜像里**不要**写死 `MIHE_KEY`，只在**运行容器时**注入环境变量。

**首次或换 Key 后启动**

1. 在宿主机准备 `.env`（从 `env.example` 复制），内容包含一行：`MIHE_KEY=你的key`。
2. 使用 Compose（推荐）：

   ```bash
   cp env.example .env   # 编辑 .env 填入 MIHE_KEY
   docker compose up -d --build
   ```

   默认映射 `7860`；改宿主机端口可设环境变量：`HOST_PORT=5001 docker compose up -d`。

3. 或不用 Compose，直接 `docker run`：

   ```bash
   docker build -t dy-tt .
   docker run --rm -p 7860:7860 --env-file .env dy-tt
   ```

   也可临时注入：`docker run --rm -p 7860:7860 -e MIHE_KEY=你的key dy-tt`（勿把真实 Key 写进 shell 历史时可改用 `--env-file`）。

**仅更换 Key（代码未变）**：修改宿主机 `.env` 或编排中的环境变量后，执行 `docker compose up -d --force-recreate`（或 `docker stop` / `docker run` 新容器），**不必**重新 `docker build`。

**为什么改了还是「之前的 Key」？**

1. **容器没重启**：环境变量在**进程启动时**读一次；只改宿主机 `.env` 或改命令行参数，**正在跑的容器里仍是旧值**，必须 `docker compose up -d --force-recreate` 或重新 `docker run`。
2. **当时用的是 `docker run -e MIHE_KEY=旧值`**：换 Key 后要**整条命令重新执行**，带上新的 `-e MIHE_KEY=新值`（或改用 `--env-file` 指向已更新的 `.env`）；旧容器里的环境不会自动变。
3. **看的是旧文件**：以前下载的「工作流 .txt」里已经嵌入了生成时的 Key；要新 Key 需在本服务**重新生成并下载**，或在 Coze「开始」节点里手动改。
4. **变量被覆盖**：若同时用了 `docker-compose.yml` 里的 `environment:` 和 `env_file`，或编排里写死了旧值，会以实际生效的为准；用 `docker exec 容器名 env | grep MIHE` 可确认当前容器内变量（注意不要泄露给他人）。

更换 Key 后，用本站点生成的工作流 JSON 会带上当前服务端的默认 Key；若曾在 Coze 里写死旧 Key，需在流程「开始」节点里同步更新。

---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference

本地启动仍然使用
python app.py即可