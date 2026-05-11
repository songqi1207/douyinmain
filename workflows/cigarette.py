#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""香烟工作流生成。"""

from config import CIGARETTE_TEMPLATE_CANDIDATES
from utils.template_loader import load_first_available_template
from utils.media import build_cigarette_match_key
from utils.sanitize import sanitize_template_media_urls
from workflows.common import make_ref
from workflows.god.canvas import ensure_coze_temp_metadata


def generate_cigarette_workflow(cigarette_name):
    """
    生成香烟工作流
    """
    template = load_first_available_template(CIGARETTE_TEMPLATE_CANDIDATES)
    nodes = {n.get("id"): n for n in template.get("json", {}).get("nodes", []) if isinstance(n, dict)}

    for node in template['json']['nodes']:
        if node['id'] == '100001':
            outputs = node['data'].get('outputs', [])
            for output in outputs:
                if output['name'] == 'xiangyan_name':
                    output['value'] = cigarette_name
                    output['defaultValue'] = cigarette_name
                elif output['name'] == 'left_top':
                    output['value'] = '吸烟有害身体健康'
                    output['defaultValue'] = '吸烟有害身体健康'
                elif output['name'] == 'left':
                    output['value'] = '未成年人禁止吸烟'
                    output['defaultValue'] = '未成年人禁止吸烟'

    if "900001" in nodes:
        end_data = nodes["900001"].setdefault("data", {})
        end_inputs = end_data.setdefault("inputs", {})
        end_inputs["terminatePlan"] = "returnVariables"
        end_data["outputs"] = [
            {"type": "string", "name": "output", "required": False, "description": "剪映草稿 draft_id"},
            {"type": "string", "name": "tts_code", "required": False, "description": "配音接口状态码（0 常为成功）"},
            {"type": "string", "name": "tts_msg", "required": False, "description": "配音接口消息（失败时看这里）"},
        ]
        end_inputs["inputParameters"] = [
            {"name": "output", "input": {"type": "string", "value": make_ref("148842", "draft_id")}},
            {"name": "tts_code", "input": {"type": "string", "value": make_ref("163300", "code")}},
            {"name": "tts_msg", "input": {"type": "string", "value": make_ref("163300", "msg")}},
        ]

    ensure_coze_temp_metadata(template)
    match_key = build_cigarette_match_key(cigarette_name)
    template = sanitize_template_media_urls(template, "cigarette", match_key)
    return template
