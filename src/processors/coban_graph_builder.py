"""
CoBAn 术语图构建模块。

职责：
- 将机密术语与上下文词打分结果转换为图边；
- 生成 cluster 维度的术语图邻接结构；
- 提供可落库的边列表结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from src.processors.coban_language_model import (
    CobanConfidentialTermScore,
    CobanContextTermScore,
)


@dataclass
class CobanGraphEdge:
    """CoBAn 术语图边。"""

    cluster_id: int
    conf_term: str
    context_term: str
    weight: float
    conf_score: float
    context_score: float


@dataclass
class CobanGraphBuildResult:
    """CoBAn 术语图构建结果。"""

    edges: List[CobanGraphEdge]
    adjacency: Dict[int, Dict[str, List[Tuple[str, float]]]]


def build_conf_context_graph(
    confidential_term_scores: Sequence[CobanConfidentialTermScore],
    context_term_scores: Sequence[CobanContextTermScore],
    min_edge_weight: float = 0.0,
) -> CobanGraphBuildResult:
    """构建 CoBAn 机密术语-上下文术语图。

    说明：
    - 以 `context_term_scores` 作为边候选；
    - 边权重定义为 `conf_score * context_score`；
    - 当边权重小于阈值时过滤。

    Args:
        confidential_term_scores: 机密术语打分列表。
        context_term_scores: 上下文词打分列表。
        min_edge_weight: 最小保留边权重。

    Returns:
        CobanGraphBuildResult: 含边列表和邻接结构。
    """

    conf_term_score_map: Dict[Tuple[int, str], float] = {}
    for item in confidential_term_scores:
        conf_term_score_map[(item.cluster_id, item.term)] = item.score

    edges: List[CobanGraphEdge] = []
    adjacency: Dict[int, Dict[str, List[Tuple[str, float]]]] = {}
    for context_item in context_term_scores:
        key = (context_item.cluster_id, context_item.conf_term)
        conf_score = conf_term_score_map.get(key, 0.0)
        if conf_score <= 0:
            continue
        weight = conf_score * context_item.score
        if weight < min_edge_weight:
            continue

        edge = CobanGraphEdge(
            cluster_id=context_item.cluster_id,
            conf_term=context_item.conf_term,
            context_term=context_item.context_term,
            weight=weight,
            conf_score=conf_score,
            context_score=context_item.score,
        )
        edges.append(edge)
        adjacency.setdefault(edge.cluster_id, {}).setdefault(edge.conf_term, []).append(
            (edge.context_term, edge.weight)
        )

    for cluster_id in adjacency:
        for conf_term in adjacency[cluster_id]:
            adjacency[cluster_id][conf_term].sort(key=lambda item: item[1], reverse=True)

    edges.sort(key=lambda item: item.weight, reverse=True)
    return CobanGraphBuildResult(edges=edges, adjacency=adjacency)

