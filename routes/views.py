#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页面视图路由。"""

from flask import Blueprint, make_response, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
