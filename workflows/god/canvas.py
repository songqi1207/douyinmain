#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canvas schema 构建 & Coze _temp 元数据补全。"""

import json


def build_god_canvas_schema():
    schema = {
        "version": "6.0.0-rc2",
        "width": 1080,
        "height": 1920,
        "backgroundColor": "#000000ff",
        "customVariableRefs": [
            {"variableId": "godImageVar", "objectId": "god_image_group", "variableName": "data"},
            {"variableId": "godTitleVar", "objectId": "god_title_text", "variableName": "title"},
            {"variableId": "godSubtitleVar", "objectId": "god_subtitle_text", "variableName": "subtitle"}
        ],
        "objects": [
            {
                "subTargetCheck": False,
                "interactive": False,
                "width": 1080,
                "height": 1080,
                "backgroundColor": "",
                "padding": 0,
                "customFixedHeight": 1080,
                "customId": "god_image_group",
                "customType": "img",
                "type": "Group",
                "version": "6.0.0-rc2",
                "originX": "left",
                "originY": "top",
                "left": 0,
                "top": 420,
                "fill": "rgb(0,0,0)",
                "stroke": None,
                "strokeWidth": 0,
                "strokeDashArray": None,
                "strokeLineCap": "butt",
                "strokeDashOffset": 0,
                "strokeLineJoin": "miter",
                "strokeUniform": False,
                "strokeMiterLimit": 4,
                "scaleX": 1,
                "scaleY": 1,
                "angle": 0,
                "flipX": False,
                "flipY": False,
                "opacity": 1,
                "shadow": None,
                "visible": True,
                "fillRule": "nonzero",
                "paintFirst": "fill",
                "globalCompositeOperation": "source-over",
                "skewX": 0,
                "skewY": 0,
                "clipPath": {
                    "rx": 0,
                    "ry": 0,
                    "width": 1080,
                    "height": 1080,
                    "backgroundColor": "",
                    "padding": 0,
                    "type": "Rect",
                    "version": "6.0.0-rc2",
                    "originX": "left",
                    "originY": "top",
                    "left": -540,
                    "top": -540,
                    "fill": "rgb(0,0,0)",
                    "stroke": None,
                    "strokeWidth": 1,
                    "strokeDashArray": None,
                    "strokeLineCap": "butt",
                    "strokeDashOffset": 0,
                    "strokeLineJoin": "miter",
                    "strokeUniform": False,
                    "strokeMiterLimit": 4,
                    "scaleX": 1,
                    "scaleY": 1,
                    "angle": 0,
                    "flipX": False,
                    "flipY": False,
                    "opacity": 1,
                    "shadow": None,
                    "visible": True,
                    "fillRule": "nonzero",
                    "paintFirst": "fill",
                    "globalCompositeOperation": "source-over",
                    "skewX": 0,
                    "skewY": 0,
                    "inverted": False,
                    "absolutePositioned": False
                },
                "layoutManager": {
                    "type": "layoutManager",
                    "strategy": "fit-content"
                },
                "objects": [
                    {
                        "cropX": 0,
                        "cropY": 0,
                        "width": 400,
                        "height": 400,
                        "editable": False,
                        "backgroundColor": "",
                        "padding": 0,
                        "customFixedType": "fill",
                        "type": "Image",
                        "version": "6.0.0-rc2",
                        "originX": "left",
                        "originY": "top",
                        "left": -540,
                        "top": -540,
                        "fill": "rgb(0,0,0)",
                        "stroke": None,
                        "strokeWidth": 0,
                        "strokeDashArray": None,
                        "strokeLineCap": "butt",
                        "strokeDashOffset": 0,
                        "strokeLineJoin": "miter",
                        "strokeUniform": False,
                        "strokeMiterLimit": 4,
                        "scaleX": 2.7,
                        "scaleY": 2.7,
                        "angle": 0,
                        "flipX": False,
                        "flipY": False,
                        "opacity": 1,
                        "shadow": None,
                        "visible": True,
                        "fillRule": "nonzero",
                        "paintFirst": "fill",
                        "globalCompositeOperation": "source-over",
                        "skewX": 0,
                        "skewY": 0,
                        "src": "https://lf-coze-web-cdn.coze.cn/obj/eden-cn/lm-lgvj/ljhwZthlaukjlkulzlp//workflow/fabric-canvas/img-placeholder.png",
                        "crossOrigin": None,
                        "filters": []
                    }
                ]
            },
            {
                "customId": "god_title_text",
                "customType": "text",
                "type": "Textbox",
                "version": "6.0.0-rc2",
                "originX": "left",
                "originY": "top",
                "left": 140,
                "top": 180,
                "width": 800,
                "height": 120,
                "fill": "#FFFFFFFF",
                "stroke": "#000000CC",
                "strokeWidth": 1,
                "strokeDashArray": None,
                "strokeLineCap": "butt",
                "strokeDashOffset": 0,
                "strokeLineJoin": "miter",
                "strokeUniform": False,
                "strokeMiterLimit": 4,
                "scaleX": 1,
                "scaleY": 1,
                "angle": 0,
                "flipX": False,
                "flipY": False,
                "opacity": 1,
                "shadow": None,
                "visible": True,
                "backgroundColor": "",
                "fillRule": "nonzero",
                "paintFirst": "fill",
                "globalCompositeOperation": "source-over",
                "skewX": 0,
                "skewY": 0,
                "fontFamily": "KaiTi",
                "fontWeight": "700",
                "fontSize": 72,
                "text": "神话标题",
                "underline": False,
                "overline": False,
                "linethrough": False,
                "textAlign": "center",
                "fontStyle": "normal",
                "lineHeight": 1.15,
                "textBackgroundColor": "",
                "charSpacing": 0,
                "styles": []
            },
            {
                "customId": "god_subtitle_text",
                "customType": "text",
                "type": "Textbox",
                "version": "6.0.0-rc2",
                "originX": "left",
                "originY": "top",
                "left": 110,
                "top": 1540,
                "width": 860,
                "height": 180,
                "fill": "#FFFFFFFF",
                "stroke": "#000000FF",
                "strokeWidth": 2,
                "strokeDashArray": None,
                "strokeLineCap": "butt",
                "strokeDashOffset": 0,
                "strokeLineJoin": "miter",
                "strokeUniform": False,
                "strokeMiterLimit": 4,
                "scaleX": 1,
                "scaleY": 1,
                "angle": 0,
                "flipX": False,
                "flipY": False,
                "opacity": 1,
                "shadow": None,
                "visible": True,
                "backgroundColor": "",
                "fillRule": "nonzero",
                "paintFirst": "fill",
                "globalCompositeOperation": "source-over",
                "skewX": 0,
                "skewY": 0,
                "fontFamily": "Microsoft YaHei",
                "fontWeight": "700",
                "fontSize": 42,
                "text": "这里显示当前分镜字幕",
                "underline": False,
                "overline": False,
                "linethrough": False,
                "textAlign": "center",
                "fontStyle": "normal",
                "lineHeight": 1.3,
                "textBackgroundColor": "",
                "charSpacing": 0,
                "styles": []
            }
        ],
        "background": "#000000ff"
    }
    return json.dumps(schema, ensure_ascii=False, separators=(',', ':'))


def ensure_coze_temp_metadata(template):
    node_size_map = {
        "1": (360, 86),
        "2": (360, 112),
        "3": (360, 188),
        "4": (360, 136),
        "5": (360, 136),
        "8": (360, 162),
        "15": (360, 136),
        "20": (360, 110),
        "21": (360, 136),
        "28": (360, 136),
        "31": (383, 200),
        "32": (360, 258),
        "23": (360, 136),
        "65": (360, 136)
    }
    color_map = {
        "1": "#5C62FF",
        "2": "#5C62FF",
        "3": "#5C62FF",
        "4": "#CA61FF",
        "5": "#00B2B2",
        "8": "#00B2B2",
        "15": "#3071F2",
        "20": "#00B2B2",
        "21": "#00B2B2",
        "28": "#00B2B2",
        "31": "",
        "32": "#00B2B2",
        "23": "#FF4DC3",
        "65": "#3071F2"
    }

    def ensure_temp(obj, owner_type, position, canvas_position=None):
        node_meta = obj.get('data', {}).get('nodeMeta', {})
        width, height = node_size_map.get(owner_type, (360, 136))
        x = position.get('x', 0)
        y = position.get('y', 0)

        if canvas_position is not None:
            x = canvas_position.get('x', 0) + x
            y = canvas_position.get('y', 0) + y
        else:
            x = x - width / 2

        temp = obj.setdefault('_temp', {})
        if 'bounds' not in temp:
            temp['bounds'] = {
                "x": x,
                "y": y,
                "width": width,
                "height": height
            }

        external = temp.setdefault('externalData', {})
        if not external.get('icon'):
            external['icon'] = node_meta.get('icon') or ''
        if not external.get('description'):
            external['description'] = node_meta.get('description') or ''
        if not external.get('title'):
            external['title'] = node_meta.get('title') or ''
        if not external.get('mainColor'):
            external['mainColor'] = node_meta.get('mainColor') or color_map.get(owner_type, '#5C62FF')

        if owner_type == "3" and 'skills' not in external:
            external['skills'] = []

    for node in template.get('json', {}).get('nodes', []):
        ensure_temp(node, node.get('type', ''), node.get('meta', {}).get('position', {}))
        canvas_position = node.get('meta', {}).get('canvasPosition')
        for block in node.get('blocks', []) or []:
            ensure_temp(
                block,
                block.get('type', ''),
                block.get('meta', {}).get('position', {}),
                canvas_position=canvas_position
            )

    return template
