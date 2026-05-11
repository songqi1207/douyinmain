#!/bin/bash
# 一键启动脚本

echo "启动一键工作流生成器..."
cd "$(dirname "$0")"

# 检查依赖
pip3 install flask flask-cors requests beautifulsoup4 -q 2>/dev/null

# 启动服务
python3 app.py