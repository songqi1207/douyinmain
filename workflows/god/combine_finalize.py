# -*- coding: utf-8 -*-
"""神话工作流导出收尾：用独立模块中的规范合并代码覆盖节点 175205，避免运行环境 builder 版本不一致。"""


def apply_canonical_combine_node_175205(workflow: dict) -> bool:
    """
    将节点 175205 的 code 替换为 myth_combine_coze_code 中的全文。
    若模块不存在（旧部署），返回 False 且不修改。
    """
    try:
        from workflows.god.myth_combine_coze_code import COZE_COMBINE_CODE_175205
    except ImportError:
        return False
    for n in workflow.get("json", {}).get("nodes", []):
        if n.get("id") == "175205":
            ins = n.setdefault("data", {}).setdefault("inputs", {})
            ins["code"] = COZE_COMBINE_CODE_175205
            params = ins.get("inputParameters")
            if isinstance(params, list):
                ins["inputParameters"] = [
                    p for p in params if p.get("name") != "god_intro_images"
                ]
            return True
    return False


def refresh_dy_workflow_meta(workflow: dict) -> None:
    """根据当前 175205 节点 code 刷新根级 _dy_workflow_meta。"""
    try:
        _cn = next(n for n in workflow["json"]["nodes"] if n.get("id") == "175205")
        _code = (_cn.get("data") or {}).get("inputs", {}).get("code") or ""
        workflow["_dy_workflow_meta"] = {
            "combine_tail_fill": "last_img_end" in _code,
            "combine_code_len": len(_code),
            "combine_marker": "last_img_end",
            "canonical_module": "workflows.god.myth_combine_coze_code",
        }
    except (StopIteration, KeyError, TypeError):
        workflow["_dy_workflow_meta"] = {
            "combine_tail_fill": False,
            "combine_code_len": 0,
            "combine_marker": "last_img_end",
            "error": "meta_probe_failed",
        }
