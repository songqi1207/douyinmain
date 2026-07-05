#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 Coze 边拓扑违规的工具函数。

NOTE: 原模板有多个菱形交叉模式但能成功导入 Coze，说明 Coze 不在导入时强制执行拓扑规则。
此函数目前只做边去重，不移除任何边。
"""

from collections import defaultdict


def fix_coze_edge_topology(template):
    """
    修复 Coze 边拓扑违规：只做去重，不移除原模板中的边。

    原模板有多个菱形交叉模式但能成功导入，说明 Coze 在导入验证时不强制拓扑规则。
    移除边可能导致节点执行顺序改变，引发 "引用变量不存在" 错误。
    """
    edges = template["json"].setdefault("edges", [])

    # Step 1: 去重
    seen = set()
    deduped = []
    for e in edges:
        key = (e.get("sourceNodeID"), e.get("targetNodeID"), e.get("sourcePortID", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    edges[:] = deduped

    # [DISABLED] 不移除任何边，原模板的边配置能成功导入
    # 以下代码已禁用，保留供参考
    #
    # # 识别批处理节点 (type=4，注意type是字符串)
    # nodes_list = template["json"].get("nodes", [])
    # batch_nodes = {n["id"] for n in nodes_list if str(n.get("type", "")) == "4"}
    #
    # WHITELIST_EDGES = {
    #     ("177645", "310628"),
    # }
    #
    # # 批处理节点的所有入边都加入白名单
    # for e in edges:
    #     tgt = e.get("targetNodeID")
    #     if tgt in batch_nodes:
    #         WHITELIST_EDGES.add((e.get("sourceNodeID"), tgt))
    #
    # # 构建邻接表
    # adj = defaultdict(set)
    # for e in edges:
    #     src = e.get("sourceNodeID")
    #     tgt = e.get("targetNodeID")
    #     adj[src].add(tgt)
    #     adj.setdefault(tgt, set())
    #
    # # BFS 检查路径
    # def has_path(start, end):
    #     if start == end:
    #         return True
    #     visited = {start}
    #     stack = [start]
    #     while stack:
    #         node = stack.pop()
    #         for neighbor in adj.get(node, set()):
    #             if neighbor == end:
    #                 return True
    #             if neighbor not in visited:
    #                 visited.add(neighbor)
    #                 stack.append(neighbor)
    #     return False
    #
    # # 识别冗余边
    # incoming = defaultdict(list)
    # for e in edges:
    #     incoming[e.get("targetNodeID")].append((e.get("sourceNodeID"), e.get("sourcePortID", "")))
    #
    # edges_to_remove = []
    # for target, sources in incoming.items():
    #     if len(sources) <= 1:
    #         continue
    #     for i, (s1, p1) in enumerate(sources):
    #         for (s2, p2) in sources[i+1:]:
    #             if has_path(s1, s2):
    #                 if (s2, target) not in WHITELIST_EDGES and not p2:
    #                     edges_to_remove.append((s2, target, p2))
    #             elif has_path(s2, s1):
    #                 if (s1, target) not in WHITELIST_EDGES and not p1:
    #                     edges_to_remove.append((s1, target, p1))
    #
    # if edges_to_remove:
    #     edges[:] = [e for e in edges if (e.get("sourceNodeID"), e.get("targetNodeID"), e.get("sourcePortID", "")) not in edges_to_remove]

    return template