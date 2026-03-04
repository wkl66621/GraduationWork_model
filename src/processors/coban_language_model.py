"""
CoBAn 术语与上下文打分模块。

职责：
- 基于 cluster 内文档统计机密术语分数（Eq.1 风格）；
- 基于术语命中窗口统计上下文词分数（Eq.2 风格）；
- 为术语图构建提供结构化打分产物。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from src.processors.coban_text_preprocessor import (
    CobanCorpusDocument,
    collect_context_tokens,
    locate_term_token_ranges,
)


@dataclass
class CobanConfidentialTermScore:
    """机密术语打分结果。"""

    cluster_id: int
    term: str
    score: float
    confidential_freq: int
    background_freq: int


@dataclass
class CobanContextTermScore:
    """上下文词打分结果。"""

    cluster_id: int
    conf_term: str
    context_term: str
    score: float
    pair_freq: int
    context_background_freq: int


def _safe_log_ratio(numerator: float, denominator: float) -> float:
    """计算对数比值并保证数值稳定。

    Args:
        numerator: 分子。
        denominator: 分母。

    Returns:
        float: 对数比值结果。
    """

    if numerator <= 0 or denominator <= 0:
        return 0.0
    return float(math.log(numerator / denominator))


def _collect_cluster_docs(
    documents: Sequence[CobanCorpusDocument],
    cluster_labels: Sequence[int],
) -> Mapping[int, List[CobanCorpusDocument]]:
    """按聚类标签聚合文档。

    Args:
        documents: 训练文档序列。
        cluster_labels: 与文档一一对应的 cluster 标签。

    Returns:
        Mapping[int, List[CobanCorpusDocument]]: cluster 到文档列表的映射。

    Raises:
        ValueError: 文档数量与标签数量不一致时抛出。
    """

    if len(documents) != len(cluster_labels):
        raise ValueError("文档数量与 cluster 标签数量不一致。")
    cluster_docs: Dict[int, List[CobanCorpusDocument]] = defaultdict(list)
    for index, cluster_id in enumerate(cluster_labels):
        cluster_docs[int(cluster_id)].append(documents[index])
    return cluster_docs


def score_confidential_terms(
    documents: Sequence[CobanCorpusDocument],
    cluster_labels: Sequence[int],
    top_k_per_cluster: int = 200,
    smoothing: float = 1.0,
) -> List[CobanConfidentialTermScore]:
    """计算每个 cluster 的机密术语分数。

    说明：
    - 正样本使用 `is_confidential=True` 文档中的术语；
    - 背景样本使用同 cluster 内全部文档术语；
    - 分数采用 log(P(term|conf) / P(term|bg))，仅保留正分数。

    Args:
        documents: 训练文档序列。
        cluster_labels: 与文档对应的 cluster 标签。
        top_k_per_cluster: 每个 cluster 返回术语数量上限。
        smoothing: 拉普拉斯平滑系数。

    Returns:
        List[CobanConfidentialTermScore]: 术语分数列表。
    """

    if not documents:
        return []

    cluster_docs = _collect_cluster_docs(documents=documents, cluster_labels=cluster_labels)
    term_scores: List[CobanConfidentialTermScore] = []
    for cluster_id, docs in cluster_docs.items():
        background_counter: Counter[str] = Counter()
        confidential_counter: Counter[str] = Counter()

        for doc in docs:
            background_counter.update(doc.terms)
            if doc.is_confidential:
                confidential_counter.update(doc.terms)

        # 如果该簇没有机密样本，则回退到全部样本，避免产生空模型。
        if not confidential_counter:
            confidential_counter = Counter(background_counter)

        vocab = set(background_counter.keys()) | set(confidential_counter.keys())
        if not vocab:
            continue

        conf_total = sum(confidential_counter.values())
        bg_total = sum(background_counter.values())
        vocab_size = max(1, len(vocab))

        per_cluster_scores: List[CobanConfidentialTermScore] = []
        for term in vocab:
            p_conf = (confidential_counter.get(term, 0) + smoothing) / (
                conf_total + smoothing * vocab_size
            )
            p_bg = (background_counter.get(term, 0) + smoothing) / (
                bg_total + smoothing * vocab_size
            )
            score = _safe_log_ratio(p_conf, p_bg)
            if score <= 0:
                continue
            per_cluster_scores.append(
                CobanConfidentialTermScore(
                    cluster_id=cluster_id,
                    term=term,
                    score=score,
                    confidential_freq=confidential_counter.get(term, 0),
                    background_freq=background_counter.get(term, 0),
                )
            )

        per_cluster_scores.sort(key=lambda item: item.score, reverse=True)
        term_scores.extend(per_cluster_scores[: max(1, top_k_per_cluster)])
    return term_scores


def _iter_conf_term_context_pairs(
    docs: Iterable[CobanCorpusDocument],
    conf_terms: Sequence[str],
    context_span: int,
) -> Iterable[Tuple[str, str]]:
    """遍历术语与上下文词配对。

    Args:
        docs: 文档迭代器。
        conf_terms: 机密术语序列。
        context_span: 上下文窗口半径。

    Yields:
        Tuple[str, str]: `(conf_term, context_term)` 配对。
    """

    for doc in docs:
        for conf_term in conf_terms:
            ranges = locate_term_token_ranges(tokens=doc.tokens, term=conf_term)
            if not ranges:
                continue
            contexts = collect_context_tokens(
                tokens=doc.tokens,
                term_ranges=ranges,
                context_span=context_span,
            )
            for context_term in contexts:
                yield conf_term, context_term


def score_context_terms(
    documents: Sequence[CobanCorpusDocument],
    cluster_labels: Sequence[int],
    confidential_term_scores: Sequence[CobanConfidentialTermScore],
    context_span: int = 20,
    top_k_per_term: int = 30,
    smoothing: float = 1.0,
) -> List[CobanContextTermScore]:
    """计算机密术语对应的上下文词分数。

    说明：
    - 在 cluster 内统计 `(conf_term, context_term)` 共现强度；
    - 背景概率来自 cluster 全文 token 分布；
    - 分数采用 log(P(ctx|term) / P(ctx|cluster-bg))，仅保留正分数。

    Args:
        documents: 训练文档序列。
        cluster_labels: 与文档对应的 cluster 标签。
        confidential_term_scores: 机密术语打分结果。
        context_span: 上下文窗口半径。
        top_k_per_term: 每个机密术语保留的上下文词上限。
        smoothing: 拉普拉斯平滑系数。

    Returns:
        List[CobanContextTermScore]: 上下文词打分列表。
    """

    if not documents or not confidential_term_scores:
        return []

    cluster_docs = _collect_cluster_docs(documents=documents, cluster_labels=cluster_labels)
    term_map: Dict[int, List[str]] = defaultdict(list)
    for item in confidential_term_scores:
        term_map[item.cluster_id].append(item.term)

    context_scores: List[CobanContextTermScore] = []
    for cluster_id, docs in cluster_docs.items():
        conf_terms = sorted(set(term_map.get(cluster_id, [])))
        if not conf_terms:
            continue

        cluster_token_counter: Counter[str] = Counter()
        for doc in docs:
            cluster_token_counter.update(doc.tokens)
        vocab = set(cluster_token_counter.keys())
        if not vocab:
            continue

        pair_counter: Dict[str, Counter[str]] = defaultdict(Counter)
        term_total_context_count: Counter[str] = Counter()
        for conf_term, context_term in _iter_conf_term_context_pairs(
            docs=docs,
            conf_terms=conf_terms,
            context_span=context_span,
        ):
            pair_counter[conf_term][context_term] += 1
            term_total_context_count[conf_term] += 1
            vocab.add(context_term)

        if not pair_counter:
            continue

        vocab_size = max(1, len(vocab))
        cluster_total = sum(cluster_token_counter.values())
        for conf_term, ctx_counter in pair_counter.items():
            total_for_term = term_total_context_count[conf_term]
            scored_items: List[CobanContextTermScore] = []
            for context_term, pair_freq in ctx_counter.items():
                p_ctx_given_term = (pair_freq + smoothing) / (
                    total_for_term + smoothing * vocab_size
                )
                p_ctx_bg = (cluster_token_counter.get(context_term, 0) + smoothing) / (
                    cluster_total + smoothing * vocab_size
                )
                score = _safe_log_ratio(p_ctx_given_term, p_ctx_bg)
                if score <= 0:
                    continue
                scored_items.append(
                    CobanContextTermScore(
                        cluster_id=cluster_id,
                        conf_term=conf_term,
                        context_term=context_term,
                        score=score,
                        pair_freq=pair_freq,
                        context_background_freq=cluster_token_counter.get(context_term, 0),
                    )
                )

            scored_items.sort(key=lambda item: item.score, reverse=True)
            context_scores.extend(scored_items[: max(1, top_k_per_term)])
    return context_scores

