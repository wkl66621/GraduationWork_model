"""
CoBAn 检测编排服务。

职责：
- 加载训练产物并执行 cluster 分配；
- 执行 irregular 术语扩展与上下文证据匹配；
- 计算机密分并给出阈值判定；
- 将检测结果写入 `coban_detection_result`。
"""

from __future__ import annotations

import json
import math
import pickle
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.database.connection import get_connection
from src.processors.coban_clusterer import assign_document_to_clusters
from src.processors.coban_text_preprocessor import preprocess_text, split_term_to_tokens


@dataclass
class CobanDetectionRequest:
    """CoBAn 检测请求。"""

    input_text: str
    doc_name: Optional[str] = None
    doc_path: Optional[str] = None
    run_id: Optional[str] = None
    top_k_clusters: int = 3
    cluster_similarity_threshold: Optional[float] = None
    irregular_ratio_threshold: float = 20.0
    detection_threshold: Optional[float] = None


@dataclass
class CobanClusterEvidence:
    """单个 cluster 的命中证据。"""

    cluster_id: int
    similarity: float
    score: float
    matched_terms: List[str] = field(default_factory=list)
    expanded_irregular_terms: List[str] = field(default_factory=list)
    matched_context_terms: List[str] = field(default_factory=list)


@dataclass
class CobanDetectionResult:
    """CoBAn 检测结果。"""

    run_id: str
    doc_uid: str
    confidentiality_score: float
    threshold_value: float
    is_confidential: bool
    matched_clusters: List[Dict[str, float]]
    evidence_terms: Dict[str, List[str]]
    decision_reason: str


def _fetch_model_run(run_id: Optional[str]) -> dict:
    """读取训练批次信息。"""
    if run_id:
        sql = """
        SELECT id, run_id, params_json, model_artifact_path
        FROM coban_model_run
        WHERE run_id = %(run_id)s AND status = 'succeeded' AND is_deleted = 0
        LIMIT 1
        """
        params = {"run_id": run_id}
    else:
        sql = """
        SELECT id, run_id, params_json, model_artifact_path
        FROM coban_model_run
        WHERE status = 'succeeded' AND is_deleted = 0
        ORDER BY id DESC
        LIMIT 1
        """
        params = {}
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    if row is None:
        raise ValueError("未找到可用的 CoBAn 成功训练批次。")
    return row


def _load_model_payload(model_artifact_path: str) -> dict:
    """加载模型产物。"""
    path = Path(model_artifact_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"模型产物不存在: {path}")
    with path.open("rb") as f:
        return pickle.load(f)


def _term_ratio(term_row: dict) -> float:
    """计算术语 irregular 比值。"""
    conf_support = float(term_row.get("support_conf_docs", 0))
    non_conf_support = float(term_row.get("support_non_conf_docs", 0))
    return (conf_support + 1.0) / (non_conf_support + 1.0)


def _expand_irregular_terms(
    matched_terms: Sequence[str],
    doc_tokens: Sequence[str],
    cluster_term_rows: Sequence[dict],
    irregular_ratio_threshold: float,
) -> List[str]:
    """执行 irregular 术语扩展。"""
    if not cluster_term_rows:
        return []
    matched_set = set(matched_terms)
    token_set = set(doc_tokens)
    expanded: List[str] = []
    for row in cluster_term_rows:
        term = row["term_value"]
        if term in matched_set:
            continue
        ratio = _term_ratio(row)
        if ratio < irregular_ratio_threshold:
            continue
        pieces = split_term_to_tokens(term)
        if not pieces:
            continue
        if token_set.intersection(pieces):
            expanded.append(term)
    return sorted(set(expanded))


def _cluster_score(
    similarity: float,
    matched_term_rows: Sequence[dict],
    expanded_term_rows: Sequence[dict],
    matched_context_rows: Sequence[dict],
    irregular_ratio_threshold: float,
) -> float:
    """计算单个 cluster 的机密分。"""
    term_score = 0.0
    for row in matched_term_rows:
        term_score += float(row["term_score"])

    irregular_score = 0.0
    for row in expanded_term_rows:
        base = float(row["term_score"])
        ratio = _term_ratio(row)
        bonus = min(2.0, ratio / max(1.0, irregular_ratio_threshold))
        irregular_score += base * bonus

    context_score = sum(float(row["context_score"]) for row in matched_context_rows)
    raw_score = max(0.0, similarity) * (term_score + 0.7 * irregular_score + 0.5 * context_score)
    return float(1.0 - math.exp(-raw_score))


def _persist_detection(
    model_run_pk: int,
    doc_uid: str,
    doc_name: Optional[str],
    doc_path: Optional[str],
    input_text: str,
    matched_clusters_json: list,
    confidentiality_score: float,
    threshold_value: float,
    is_confidential: bool,
    evidence_json: dict,
    decision_reason: str,
) -> None:
    """写入检测结果表。"""
    sql = """
    INSERT INTO coban_detection_result (
        run_id, doc_uid, doc_name, doc_path, input_text, matched_clusters_json,
        confidentiality_score, threshold_value, is_confidential, evidence_json, decision_reason
    ) VALUES (
        %(run_id)s, %(doc_uid)s, %(doc_name)s, %(doc_path)s, %(input_text)s, %(matched_clusters_json)s,
        %(confidentiality_score)s, %(threshold_value)s, %(is_confidential)s, %(evidence_json)s, %(decision_reason)s
    )
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                {
                    "run_id": model_run_pk,
                    "doc_uid": doc_uid,
                    "doc_name": doc_name,
                    "doc_path": doc_path,
                    "input_text": input_text,
                    "matched_clusters_json": json.dumps(matched_clusters_json, ensure_ascii=False),
                    "confidentiality_score": confidentiality_score,
                    "threshold_value": threshold_value,
                    "is_confidential": int(is_confidential),
                    "evidence_json": json.dumps(evidence_json, ensure_ascii=False),
                    "decision_reason": decision_reason,
                },
            )


def detect_coban_confidentiality(request: CobanDetectionRequest) -> CobanDetectionResult:
    """执行 CoBAn 文本检测。

    Args:
        request: 检测请求。

    Returns:
        CobanDetectionResult: 检测判定结果。
    """
    if not request.input_text.strip():
        raise ValueError("检测失败：输入文本为空。")

    run_row = _fetch_model_run(run_id=request.run_id)
    run_params = run_row.get("params_json") or {}
    if isinstance(run_params, str):
        run_params = json.loads(run_params)

    model_payload = _load_model_payload(run_row["model_artifact_path"])
    ngram_range = tuple(model_payload.get("params", {}).get("ngram_range", [1, 3]))
    _, doc_terms, normalized_text = preprocess_text(
        text=request.input_text,
        stopwords=None,
        ngram_range=ngram_range,
    )
    doc_tokens = normalized_text.split(" ") if normalized_text else []

    similarity_threshold = (
        float(request.cluster_similarity_threshold)
        if request.cluster_similarity_threshold is not None
        else float(model_payload.get("params", {}).get("cluster_similarity_threshold", 0.05))
    )
    assigned_clusters = assign_document_to_clusters(
        text=normalized_text,
        vectorizer=model_payload["vectorizer"],
        centroid_vectors=model_payload["centroid_vectors"],
        top_k=max(1, request.top_k_clusters),
        similarity_threshold=similarity_threshold,
    )

    conf_term_rows_all = model_payload.get("confidential_terms", [])
    context_term_rows_all = model_payload.get("context_terms", [])

    cluster_evidences: List[CobanClusterEvidence] = []
    cluster_scores: List[Tuple[float, float]] = []
    doc_term_set = set(doc_terms)
    doc_token_set = set(doc_tokens)
    for cluster_id, similarity in assigned_clusters:
        cluster_conf_terms = [
            row for row in conf_term_rows_all if int(row["cluster_id"]) == int(cluster_id)
        ]
        matched_term_rows = [row for row in cluster_conf_terms if row["term_value"] in doc_term_set]
        matched_terms = sorted({row["term_value"] for row in matched_term_rows})

        expanded_terms = _expand_irregular_terms(
            matched_terms=matched_terms,
            doc_tokens=doc_tokens,
            cluster_term_rows=cluster_conf_terms,
            irregular_ratio_threshold=request.irregular_ratio_threshold,
        )
        expanded_term_rows = [
            row for row in cluster_conf_terms if row["term_value"] in set(expanded_terms)
        ]

        effective_terms = set(matched_terms) | set(expanded_terms)
        cluster_context_rows = [
            row for row in context_term_rows_all if int(row["cluster_id"]) == int(cluster_id)
        ]
        matched_context_rows = [
            row
            for row in cluster_context_rows
            if row["conf_term"] in effective_terms and row["context_term"] in doc_token_set
        ]
        matched_context_terms = sorted({row["context_term"] for row in matched_context_rows})

        score = _cluster_score(
            similarity=float(similarity),
            matched_term_rows=matched_term_rows,
            expanded_term_rows=expanded_term_rows,
            matched_context_rows=matched_context_rows,
            irregular_ratio_threshold=request.irregular_ratio_threshold,
        )
        cluster_scores.append((float(similarity), float(score)))
        cluster_evidences.append(
            CobanClusterEvidence(
                cluster_id=int(cluster_id),
                similarity=float(similarity),
                score=float(score),
                matched_terms=matched_terms,
                expanded_irregular_terms=expanded_terms,
                matched_context_terms=matched_context_terms,
            )
        )

    sim_sum = sum(item[0] for item in cluster_scores)
    if sim_sum > 0:
        confidentiality_score = sum(sim * s for sim, s in cluster_scores) / sim_sum
    else:
        confidentiality_score = max((score for _, score in cluster_scores), default=0.0)

    threshold_value = (
        float(request.detection_threshold)
        if request.detection_threshold is not None
        else float(model_payload.get("params", {}).get("detection_threshold", 0.8))
    )
    is_confidential = confidentiality_score >= threshold_value
    if is_confidential:
        decision_reason = (
            f"score={confidentiality_score:.4f} 超过阈值 {threshold_value:.4f}，判定为机密文本。"
        )
    else:
        decision_reason = (
            f"score={confidentiality_score:.4f} 未达到阈值 {threshold_value:.4f}，判定为非机密文本。"
        )

    doc_uid = uuid.uuid4().hex
    matched_clusters_json = [
        {
            "cluster_id": item.cluster_id,
            "similarity": item.similarity,
            "score": item.score,
        }
        for item in cluster_evidences
    ]
    evidence_json = {
        "clusters": [
            {
                "cluster_id": item.cluster_id,
                "matched_terms": item.matched_terms,
                "expanded_irregular_terms": item.expanded_irregular_terms,
                "matched_context_terms": item.matched_context_terms,
            }
            for item in cluster_evidences
        ]
    }
    _persist_detection(
        model_run_pk=int(run_row["id"]),
        doc_uid=doc_uid,
        doc_name=request.doc_name,
        doc_path=request.doc_path,
        input_text=request.input_text,
        matched_clusters_json=matched_clusters_json,
        confidentiality_score=float(confidentiality_score),
        threshold_value=threshold_value,
        is_confidential=is_confidential,
        evidence_json=evidence_json,
        decision_reason=decision_reason,
    )

    all_terms = sorted(
        {
            *[term for item in cluster_evidences for term in item.matched_terms],
            *[term for item in cluster_evidences for term in item.expanded_irregular_terms],
        }
    )
    all_context_terms = sorted(
        {term for item in cluster_evidences for term in item.matched_context_terms}
    )
    return CobanDetectionResult(
        run_id=run_row["run_id"],
        doc_uid=doc_uid,
        confidentiality_score=float(confidentiality_score),
        threshold_value=float(threshold_value),
        is_confidential=is_confidential,
        matched_clusters=matched_clusters_json,
        evidence_terms={
            "evidence_terms": all_terms,
            "context_terms": all_context_terms,
        },
        decision_reason=decision_reason,
    )

