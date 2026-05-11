#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页面视图路由。"""

from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    return render_template("index.html")
