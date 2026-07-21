#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键工作流生成器 — 组装入口
- 每天认识一本书
- 每天认识一款香烟
- 每天认识一个神
"""

import os

from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config import print_startup_info
from routes.api import api_bp
from routes.views import views_bp


def create_app():
    application = Flask(__name__, template_folder="templates", static_folder="static")
    application.wsgi_app = ProxyFix(application.wsgi_app, x_for=1, x_proto=1, x_host=1)
    application.config["JSON_AS_ASCII"] = False
    CORS(application, allow_private_network=True)
    application.register_blueprint(views_bp)
    application.register_blueprint(api_bp)
    return application


app = create_app()
print_startup_info()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes", "on")
    print("\n" + "=" * 60)
    print("一键工作流生成器 - 服务启动中...")
    print("=" * 60)
    print(f"\n访问地址: http://localhost:{port}")
    print(f"工作目录: {os.getcwd()}")
    print("\n按 Ctrl+C 停止服务\n")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
