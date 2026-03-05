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
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from src.config.settings import settings
from src.database.connection import get_connection
from src.processors.coban_clusterer import assign_document_to_clusters
from src.processors.coban_text_preprocessor import preprocess_text, split_term_to_tokens


def _safe_json_load(value: Any) -> Any:
    """将 JSON 字段安全转换为 Python 对象。

    Args:
        value: 待解析字段，可能为 `dict/list/str/None`。

    Returns:
        Any: 解析结果；解析失败时返回原值。
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _to_float(value: Any, default: float = 0.0) -> float:
    """将任意数值转换为浮点数。

    Args:
        value: 待转换数值。
        default: 转换失败时默认值。

    Returns:
        float: 转换结果。
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_iso_time(value: Any) -> Optional[str]:
    """将时间字段转换为 ISO 字符串。

    Args:
        value: 时间值，可能为 datetime 或其他类型。

    Returns:
        Optional[str]: ISO 时间字符串或 `None`。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


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


def get_coban_run_visualization(run_id: str) -> dict:
    """构建 CoBAn 训练批次可视化总览数据。

    Args:
        run_id: 训练批次业务 ID。

    Returns:
        dict: 含卡片、图表与最新检测列表的聚合结构。

    Raises:
        ValueError: 指定批次不存在时抛出。
    """
    run_sql = """
    SELECT
        id,
        run_id,
        run_name,
        dataset_name,
        source_type,
        train_doc_count,
        conf_doc_count,
        non_conf_doc_count,
        params_json,
        metrics_json,
        status,
        start_time,
        end_time
    FROM coban_model_run
    WHERE run_id = %(run_id)s AND is_deleted = 0
    LIMIT 1
    """
    cluster_sql = """
    SELECT
        cluster_code,
        cluster_size,
        conf_doc_count,
        non_conf_doc_count,
        similarity_threshold
    FROM coban_cluster
    WHERE run_id = %(run_pk)s
    ORDER BY cluster_size DESC, id ASC
    """
    detect_recent_sql = """
    SELECT
        doc_uid,
        doc_name,
        confidentiality_score,
        threshold_value,
        is_confidential,
        create_time
    FROM coban_detection_result
    WHERE run_id = %(run_pk)s
    ORDER BY id DESC
    LIMIT 200
    """
    detect_total_sql = """
    SELECT COUNT(*) AS total_count
    FROM coban_detection_result
    WHERE run_id = %(run_pk)s
    """
    detect_trend_sql = """
    SELECT
        DATE(create_time) AS dt,
        COUNT(*) AS total_count,
        SUM(CASE WHEN is_confidential = 1 THEN 1 ELSE 0 END) AS conf_count
    FROM coban_detection_result
    WHERE run_id = %(run_pk)s
    GROUP BY DATE(create_time)
    ORDER BY dt ASC
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(run_sql, {"run_id": run_id})
            run_row = cursor.fetchone()
            if run_row is None:
                raise ValueError(f"训练批次不存在: {run_id}")
            run_pk = int(run_row["id"])

            cursor.execute(cluster_sql, {"run_pk": run_pk})
            cluster_rows = cursor.fetchall() or []

            cursor.execute(detect_recent_sql, {"run_pk": run_pk})
            detect_rows = cursor.fetchall() or []

            cursor.execute(detect_total_sql, {"run_pk": run_pk})
            total_row = cursor.fetchone() or {"total_count": 0}

            cursor.execute(detect_trend_sql, {"run_pk": run_pk})
            trend_rows = cursor.fetchall() or []

    params = _safe_json_load(run_row.get("params_json")) or {}
    metrics = _safe_json_load(run_row.get("metrics_json")) or {}
    detect_total = int(total_row.get("total_count", 0) or 0)

    cluster_series = [
        {
            "cluster_code": row["cluster_code"],
            "cluster_size": int(row.get("cluster_size", 0) or 0),
            "conf_doc_count": int(row.get("conf_doc_count", 0) or 0),
            "non_conf_doc_count": int(row.get("non_conf_doc_count", 0) or 0),
            "similarity_threshold": _to_float(row.get("similarity_threshold")),
        }
        for row in cluster_rows
    ]

    score_bins = [0] * 10
    conf_detect_count = 0
    recent_rows: List[dict] = []
    for row in detect_rows:
        score = _to_float(row.get("confidentiality_score"))
        idx = min(9, max(0, int(score * 10)))
        score_bins[idx] += 1
        flag = bool(int(row.get("is_confidential", 0)))
        if flag:
            conf_detect_count += 1
        recent_rows.append(
            {
                "doc_uid": row["doc_uid"],
                "doc_name": row.get("doc_name"),
                "confidentiality_score": score,
                "threshold_value": _to_float(row.get("threshold_value")),
                "is_confidential": flag,
                "create_time": _to_iso_time(row.get("create_time")),
            }
        )

    histogram = []
    for idx, cnt in enumerate(score_bins):
        lower = idx / 10
        upper = (idx + 1) / 10
        histogram.append(
            {
                "range_label": f"{lower:.1f}-{upper:.1f}",
                "count": cnt,
            }
        )

    trend_series = [
        {
            "date": str(row["dt"]),
            "total_count": int(row.get("total_count", 0) or 0),
            "conf_count": int(row.get("conf_count", 0) or 0),
        }
        for row in trend_rows
    ]

    return {
        "run_id": run_row["run_id"],
        "run_name": run_row.get("run_name"),
        "dataset_name": run_row.get("dataset_name"),
        "status": run_row.get("status"),
        "source_type": run_row.get("source_type"),
        "params": params,
        "metrics": metrics,
        "cards": {
            "train_doc_count": int(run_row.get("train_doc_count", 0) or 0),
            "conf_doc_count": int(run_row.get("conf_doc_count", 0) or 0),
            "non_conf_doc_count": int(run_row.get("non_conf_doc_count", 0) or 0),
            "cluster_count": len(cluster_rows),
            "detection_total": detect_total,
            "conf_detection_count": conf_detect_count,
            "conf_detection_ratio": (conf_detect_count / detect_total) if detect_total > 0 else 0.0,
            "start_time": _to_iso_time(run_row.get("start_time")),
            "end_time": _to_iso_time(run_row.get("end_time")),
        },
        "chart_series": {
            "cluster_distribution": cluster_series,
            "detection_score_histogram": histogram,
            "detection_trend": trend_series,
        },
        "table_rows": recent_rows[:50],
    }


def list_coban_detections_visualization(
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    is_confidential: Optional[bool] = None,
) -> dict:
    """分页查询 CoBAn 检测记录并返回可视化友好结构。

    Args:
        run_id: 训练批次业务 ID。
        limit: 每页条数。
        offset: 偏移量。
        is_confidential: 可选机密标记筛选。

    Returns:
        dict: 含分页信息、表格数据与趋势序列的结果。

    Raises:
        ValueError: 训练批次不存在时抛出。
    """
    page_size = max(1, min(int(limit), 200))
    page_offset = max(0, int(offset))

    run_sql = """
    SELECT id, run_id
    FROM coban_model_run
    WHERE run_id = %(run_id)s AND is_deleted = 0
    LIMIT 1
    """
    where_extra = ""
    query_params: Dict[str, Any] = {}
    if is_confidential is not None:
        where_extra = " AND d.is_confidential = %(is_confidential)s"
        query_params["is_confidential"] = int(is_confidential)

    total_sql = f"""
    SELECT COUNT(*) AS total_count
    FROM coban_detection_result d
    WHERE d.run_id = %(run_pk)s
    {where_extra}
    """
    list_sql = f"""
    SELECT
        d.doc_uid,
        d.doc_name,
        d.doc_path,
        d.confidentiality_score,
        d.threshold_value,
        d.is_confidential,
        d.matched_clusters_json,
        d.evidence_json,
        d.decision_reason,
        d.create_time
    FROM coban_detection_result d
    WHERE d.run_id = %(run_pk)s
    {where_extra}
    ORDER BY d.id DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """
    trend_sql = f"""
    SELECT
        DATE(d.create_time) AS dt,
        COUNT(*) AS total_count
    FROM coban_detection_result d
    WHERE d.run_id = %(run_pk)s
    {where_extra}
    GROUP BY DATE(d.create_time)
    ORDER BY dt ASC
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(run_sql, {"run_id": run_id})
            run_row = cursor.fetchone()
            if run_row is None:
                raise ValueError(f"训练批次不存在: {run_id}")
            run_pk = int(run_row["id"])

            base_params = {"run_pk": run_pk, **query_params}

            cursor.execute(total_sql, base_params)
            total_row = cursor.fetchone() or {"total_count": 0}
            total_count = int(total_row.get("total_count", 0) or 0)

            cursor.execute(
                list_sql,
                {
                    **base_params,
                    "limit": page_size,
                    "offset": page_offset,
                },
            )
            rows = cursor.fetchall() or []

            cursor.execute(trend_sql, base_params)
            trend_rows = cursor.fetchall() or []

    table_rows: List[dict] = []
    for row in rows:
        matched_clusters = _safe_json_load(row.get("matched_clusters_json")) or []
        evidence = _safe_json_load(row.get("evidence_json")) or {}
        clusters = evidence.get("clusters", [])
        evidence_term_count = 0
        context_term_count = 0
        for item in clusters:
            evidence_term_count += len(item.get("matched_terms", []))
            evidence_term_count += len(item.get("expanded_irregular_terms", []))
            context_term_count += len(item.get("matched_context_terms", []))
        table_rows.append(
            {
                "doc_uid": row["doc_uid"],
                "doc_name": row.get("doc_name"),
                "doc_path": row.get("doc_path"),
                "confidentiality_score": _to_float(row.get("confidentiality_score")),
                "threshold_value": _to_float(row.get("threshold_value")),
                "is_confidential": bool(int(row.get("is_confidential", 0))),
                "matched_cluster_count": len(matched_clusters),
                "evidence_term_count": evidence_term_count,
                "context_term_count": context_term_count,
                "decision_reason": row.get("decision_reason"),
                "create_time": _to_iso_time(row.get("create_time")),
            }
        )

    trend_series = [
        {
            "date": str(row["dt"]),
            "count": int(row.get("total_count", 0) or 0),
        }
        for row in trend_rows
    ]

    return {
        "run_id": run_id,
        "total_count": total_count,
        "limit": page_size,
        "offset": page_offset,
        "rows": table_rows,
        "trend": trend_series,
    }


def get_coban_detection_evidence_graph(doc_uid: str) -> dict:
    """构建单条检测记录的证据图可视化结构。

    Args:
        doc_uid: 检测文档 UID。

    Returns:
        dict: 包含基础卡片与图节点/边结构。

    Raises:
        ValueError: 检测记录不存在时抛出。
    """
    sql = """
    SELECT
        d.doc_uid,
        d.doc_name,
        d.confidentiality_score,
        d.threshold_value,
        d.is_confidential,
        d.matched_clusters_json,
        d.evidence_json,
        d.decision_reason,
        d.create_time,
        m.run_id AS run_uid
    FROM coban_detection_result d
    INNER JOIN coban_model_run m ON m.id = d.run_id
    WHERE d.doc_uid = %(doc_uid)s
    ORDER BY d.id DESC
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"doc_uid": doc_uid})
            row = cursor.fetchone()
    if row is None:
        raise ValueError(f"未找到检测记录: {doc_uid}")

    matched_clusters = _safe_json_load(row.get("matched_clusters_json")) or []
    evidence = _safe_json_load(row.get("evidence_json")) or {}
    evidence_clusters = evidence.get("clusters", [])
    score_map: Dict[int, dict] = {}
    for item in matched_clusters:
        cluster_id = int(item.get("cluster_id", -1))
        if cluster_id < 0:
            continue
        score_map[cluster_id] = {
            "similarity": _to_float(item.get("similarity")),
            "score": _to_float(item.get("score")),
        }

    nodes: Dict[str, dict] = {}
    edges: Dict[str, dict] = {}

    def upsert_node(node_id: str, payload: dict) -> None:
        """向节点字典写入节点并避免重复。"""
        if node_id not in nodes:
            nodes[node_id] = payload

    def upsert_edge(edge_id: str, payload: dict) -> None:
        """向边字典写入边并避免重复。"""
        if edge_id not in edges:
            edges[edge_id] = payload

    evidence_term_total = 0
    context_term_total = 0
    for cluster_item in evidence_clusters:
        cluster_id = int(cluster_item.get("cluster_id", -1))
        if cluster_id < 0:
            continue
        cluster_node_id = f"cluster_{cluster_id}"
        cluster_score = score_map.get(cluster_id, {})
        upsert_node(
            cluster_node_id,
            {
                "id": cluster_node_id,
                "label": f"cluster_{cluster_id}",
                "type": "cluster",
                "cluster_id": cluster_id,
                "similarity": cluster_score.get("similarity", 0.0),
                "score": cluster_score.get("score", 0.0),
            },
        )

        matched_terms = cluster_item.get("matched_terms", []) or []
        expanded_terms = cluster_item.get("expanded_irregular_terms", []) or []
        context_terms = cluster_item.get("matched_context_terms", []) or []
        evidence_term_total += len(matched_terms) + len(expanded_terms)
        context_term_total += len(context_terms)

        for term in matched_terms:
            term_id = f"term_{cluster_id}_m_{term}"
            upsert_node(
                term_id,
                {
                    "id": term_id,
                    "label": term,
                    "type": "matched_term",
                    "cluster_id": cluster_id,
                },
            )
            edge_id = f"edge_{cluster_node_id}_{term_id}"
            upsert_edge(
                edge_id,
                {
                    "id": edge_id,
                    "source": cluster_node_id,
                    "target": term_id,
                    "type": "cluster_to_matched_term",
                    "weight": 1.0,
                },
            )
            for ctx in context_terms:
                ctx_id = f"context_{cluster_id}_{ctx}"
                upsert_node(
                    ctx_id,
                    {
                        "id": ctx_id,
                        "label": ctx,
                        "type": "context_term",
                        "cluster_id": cluster_id,
                    },
                )
                ctx_edge_id = f"edge_{term_id}_{ctx_id}"
                upsert_edge(
                    ctx_edge_id,
                    {
                        "id": ctx_edge_id,
                        "source": term_id,
                        "target": ctx_id,
                        "type": "term_to_context",
                        "weight": 1.0,
                    },
                )

        for term in expanded_terms:
            term_id = f"term_{cluster_id}_e_{term}"
            upsert_node(
                term_id,
                {
                    "id": term_id,
                    "label": term,
                    "type": "expanded_term",
                    "cluster_id": cluster_id,
                },
            )
            edge_id = f"edge_{cluster_node_id}_{term_id}"
            upsert_edge(
                edge_id,
                {
                    "id": edge_id,
                    "source": cluster_node_id,
                    "target": term_id,
                    "type": "cluster_to_expanded_term",
                    "weight": 0.8,
                },
            )
            for ctx in context_terms:
                ctx_id = f"context_{cluster_id}_{ctx}"
                upsert_node(
                    ctx_id,
                    {
                        "id": ctx_id,
                        "label": ctx,
                        "type": "context_term",
                        "cluster_id": cluster_id,
                    },
                )
                ctx_edge_id = f"edge_{term_id}_{ctx_id}"
                upsert_edge(
                    ctx_edge_id,
                    {
                        "id": ctx_edge_id,
                        "source": term_id,
                        "target": ctx_id,
                        "type": "term_to_context",
                        "weight": 0.8,
                    },
                )

    return {
        "run_id": row["run_uid"],
        "doc_uid": row["doc_uid"],
        "doc_name": row.get("doc_name"),
        "cards": {
            "confidentiality_score": _to_float(row.get("confidentiality_score")),
            "threshold_value": _to_float(row.get("threshold_value")),
            "is_confidential": bool(int(row.get("is_confidential", 0))),
            "cluster_count": len(evidence_clusters),
            "evidence_term_count": evidence_term_total,
            "context_term_count": context_term_total,
            "create_time": _to_iso_time(row.get("create_time")),
        },
        "decision_reason": row.get("decision_reason"),
        "graph": {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        },
    }


def _viz_output_dir(module_name: str) -> Path:
    """获取 CoBAn 可视化图像输出目录。

    Args:
        module_name: 子模块名称。

    Returns:
        Path: 可写入目录路径。
    """
    output_dir = (settings.paths.output_dir / "visualization" / module_name).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_cache_key(payload: dict) -> str:
    """构建可视化缓存键。

    Args:
        payload: 参数字典。

    Returns:
        str: 哈希前缀。
    """
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _setup_coban_chart_theme() -> None:
    """设置 CoBAn 图表主题。"""
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams["axes.unicode_minus"] = False


def _to_generated_at(file_path: Path) -> str:
    """从文件元信息生成标准时间字符串。

    Args:
        file_path: 图片文件路径。

    Returns:
        str: 文件修改时间（ISO 格式，秒级）。
    """
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
    return mtime.isoformat(timespec="seconds")


def _build_image_export_response(
    *,
    biz_id: str,
    module_name: str,
    chart_type: str,
    image_format: str,
    image_path: Path,
    cache_key: str,
    cache_hit: bool,
    chart_meta: dict,
) -> dict:
    """构建统一的图像导出响应契约。

    Args:
        biz_id: 业务主键（如 run_id）。
        module_name: 模块名称（如 `coban_overview`）。
        chart_type: 图类型。
        image_format: 图片格式。
        image_path: 图片文件路径。
        cache_key: 缓存键。
        cache_hit: 是否命中缓存文件。
        chart_meta: 图表元信息。

    Returns:
        dict: 统一导出响应。
    """
    return {
        "biz_id": biz_id,
        "module_name": module_name,
        "chart_type": chart_type,
        "image_format": image_format,
        "image_url": str(image_path),
        "generated_at": _to_generated_at(image_path),
        "chart_meta": {
            **chart_meta,
            "cache_key": cache_key,
            "cache_hit": cache_hit,
        },
    }


def export_coban_run_overview_image(
    run_id: str,
    chart_type: str = "cluster_distribution",
    dpi: int = 200,
    image_format: str = "png",
) -> dict:
    """导出 CoBAn 批次总览图像。

    Args:
        run_id: 训练批次业务 ID。
        chart_type: 图类型，支持 `cluster_distribution/score_histogram/detection_trend`。
        dpi: 图像 DPI。
        image_format: 图片格式，支持 `png/svg`。

    Returns:
        dict: 图像输出元数据。
    """
    fmt = str(image_format).strip().lower()
    if fmt not in {"png", "svg"}:
        raise ValueError(f"不支持的图片格式: {image_format}")
    ctype = str(chart_type).strip().lower()
    supported = {"cluster_distribution", "score_histogram", "detection_trend"}
    if ctype not in supported:
        raise ValueError(f"不支持的图类型: {chart_type}")

    payload = get_coban_run_visualization(run_id=run_id)
    cache_key = _build_cache_key(
        {
            "run_id": run_id,
            "chart_type": ctype,
            "dpi": int(dpi),
            "format": fmt,
            "status": payload.get("status"),
            "detection_total": payload.get("cards", {}).get("detection_total", 0),
            "cluster_count": payload.get("cards", {}).get("cluster_count", 0),
        }
    )
    output_dir = _viz_output_dir("coban_overview")
    filename = f"coban_overview_{ctype}_{run_id}_{cache_key}.{fmt}"
    file_path = (output_dir / filename).resolve()
    cache_hit = file_path.exists()
    if not cache_hit:
        _setup_coban_chart_theme()
        fig, ax = plt.subplots(figsize=(12, 7))
        if ctype == "cluster_distribution":
            rows = payload["chart_series"]["cluster_distribution"]
            labels = [row["cluster_code"] for row in rows]
            values = [row["cluster_size"] for row in rows]
            palette = sns.color_palette("crest", n_colors=max(3, len(values)))
            sns.barplot(x=labels, y=values, ax=ax, palette=palette)
            ax.set_title(f"CoBAn Cluster Distribution ({run_id})")
            ax.set_xlabel("Cluster")
            ax.set_ylabel("Document Count")
        elif ctype == "score_histogram":
            rows = payload["chart_series"]["detection_score_histogram"]
            labels = [row["range_label"] for row in rows]
            values = [row["count"] for row in rows]
            sns.barplot(x=labels, y=values, ax=ax, color="#4E79A7")
            ax.set_title(f"CoBAn Detection Score Histogram ({run_id})")
            ax.set_xlabel("Score Bucket")
            ax.set_ylabel("Count")
            ax.tick_params(axis="x", rotation=30)
        else:
            rows = payload["chart_series"]["detection_trend"]
            labels = [row["date"] for row in rows]
            total_vals = [row["total_count"] for row in rows]
            conf_vals = [row["conf_count"] for row in rows]
            if labels:
                ax.plot(labels, total_vals, marker="o", linewidth=1.8, label="total")
                ax.plot(labels, conf_vals, marker="o", linewidth=1.8, label="confidential")
                ax.tick_params(axis="x", rotation=30)
            ax.set_title(f"CoBAn Detection Trend ({run_id})")
            ax.set_xlabel("Date")
            ax.set_ylabel("Count")
            ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(file_path, dpi=max(72, int(dpi)), format=fmt)
        plt.close(fig)

    return _build_image_export_response(
        biz_id=run_id,
        module_name="coban_overview",
        chart_type=ctype,
        image_format=fmt,
        image_path=file_path,
        cache_key=cache_key,
        cache_hit=cache_hit,
        chart_meta={
            "dpi": int(dpi),
            "status": payload.get("status"),
            "detection_total": payload.get("cards", {}).get("detection_total", 0),
            "cluster_count": payload.get("cards", {}).get("cluster_count", 0),
        },
    )


def export_coban_detections_image(
    run_id: str,
    chart_type: str = "score_boxplot",
    limit: int = 200,
    offset: int = 0,
    is_confidential: Optional[bool] = None,
    dpi: int = 200,
    image_format: str = "png",
) -> dict:
    """导出 CoBAn 检测列表统计图像。

    Args:
        run_id: 训练批次业务 ID。
        chart_type: 图类型，支持 `score_boxplot/status_bar/trend_line`。
        limit: 分页大小。
        offset: 分页偏移。
        is_confidential: 可选机密过滤。
        dpi: 图像 DPI。
        image_format: 图片格式，支持 `png/svg`。

    Returns:
        dict: 图像输出元数据。
    """
    fmt = str(image_format).strip().lower()
    if fmt not in {"png", "svg"}:
        raise ValueError(f"不支持的图片格式: {image_format}")
    ctype = str(chart_type).strip().lower()
    supported = {"score_boxplot", "status_bar", "trend_line"}
    if ctype not in supported:
        raise ValueError(f"不支持的图类型: {chart_type}")

    payload = list_coban_detections_visualization(
        run_id=run_id,
        limit=limit,
        offset=offset,
        is_confidential=is_confidential,
    )
    rows = payload["rows"]
    cache_key = _build_cache_key(
        {
            "run_id": run_id,
            "chart_type": ctype,
            "limit": int(limit),
            "offset": int(offset),
            "is_confidential": is_confidential,
            "dpi": int(dpi),
            "format": fmt,
            "total_count": payload["total_count"],
            "row_count": len(rows),
        }
    )
    output_dir = _viz_output_dir("coban_detections")
    filename = f"coban_detections_{ctype}_{run_id}_{cache_key}.{fmt}"
    file_path = (output_dir / filename).resolve()
    cache_hit = file_path.exists()
    if not cache_hit:
        _setup_coban_chart_theme()
        fig, ax = plt.subplots(figsize=(12, 7))
        if ctype == "score_boxplot":
            if rows:
                statuses = ["confidential" if row["is_confidential"] else "non_confidential" for row in rows]
                scores = [row["confidentiality_score"] for row in rows]
                sns.boxplot(x=statuses, y=scores, ax=ax, palette=["#E15759", "#4E79A7"])
                sns.stripplot(x=statuses, y=scores, ax=ax, color="#1F2937", size=3, alpha=0.35)
            ax.set_title(f"CoBAn Score Distribution by Label ({run_id})")
            ax.set_xlabel("Predicted Label")
            ax.set_ylabel("Confidentiality Score")
        elif ctype == "status_bar":
            conf_count = len([row for row in rows if row["is_confidential"]])
            non_conf_count = len(rows) - conf_count
            labels = ["confidential", "non_confidential"]
            values = [conf_count, non_conf_count]
            sns.barplot(x=labels, y=values, ax=ax, palette=["#D1495B", "#4E79A7"])
            ax.set_title(f"CoBAn Detection Status Count ({run_id})")
            ax.set_xlabel("Status")
            ax.set_ylabel("Count")
        else:
            trend = payload["trend"]
            labels = [item["date"] for item in trend]
            values = [item["count"] for item in trend]
            if labels:
                ax.plot(labels, values, marker="o", linewidth=1.8, color="#4E79A7")
                ax.tick_params(axis="x", rotation=30)
            ax.set_title(f"CoBAn Detection Volume Trend ({run_id})")
            ax.set_xlabel("Date")
            ax.set_ylabel("Count")
        fig.tight_layout()
        fig.savefig(file_path, dpi=max(72, int(dpi)), format=fmt)
        plt.close(fig)

    return _build_image_export_response(
        biz_id=run_id,
        module_name="coban_detections",
        chart_type=ctype,
        image_format=fmt,
        image_path=file_path,
        cache_key=cache_key,
        cache_hit=cache_hit,
        chart_meta={
            "dpi": int(dpi),
            "limit": int(limit),
            "offset": int(offset),
            "is_confidential": is_confidential,
            "total_count": payload["total_count"],
            "row_count": len(rows),
        },
    )

