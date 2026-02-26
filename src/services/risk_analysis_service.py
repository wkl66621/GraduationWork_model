"""
显隐性关系风险分析服务。

能力：
- 从企业数据集读取样本值
- 执行 LR/PIC/Risk 计算
- 将结果写入 enterprise_kg_edge_implicit
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from src.database.connection import get_connection
from src.processors.explicit_implicit_analysis import compute_explicit_implicit_scores


def _fetch_dataset(dataset_code: str) -> Optional[dict]:
    sql = """
    SELECT id, dataset_code, dataset_name
    FROM enterprise_dataset
    WHERE dataset_code = %(dataset_code)s AND is_deleted = 0
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"dataset_code": dataset_code})
            return cursor.fetchone()


def _fetch_attributes(dataset_id: int) -> List[dict]:
    sql = """
    SELECT id, attr_code, attr_name, is_sensitive, default_pic
    FROM enterprise_attribute
    WHERE dataset_id = %(dataset_id)s AND is_deleted = 0
    ORDER BY id ASC
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"dataset_id": dataset_id})
            return cursor.fetchall() or []


def _fetch_sample_rows(dataset_id: int, attr_codes: Sequence[str]) -> List[dict]:
    if not attr_codes:
        return []
    sql = """
    SELECT
        s.sample_key,
        a.attr_code,
        COALESCE(v.normalized_value, v.raw_value) AS attr_value
    FROM enterprise_sample s
    JOIN enterprise_sample_value v ON v.sample_id = s.id AND v.is_deleted = 0
    JOIN enterprise_attribute a ON a.id = v.attribute_id AND a.is_deleted = 0
    WHERE s.dataset_id = %(dataset_id)s
      AND s.is_deleted = 0
      AND a.attr_code IN %(attr_codes)s
    ORDER BY s.sample_key ASC
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                {
                    "dataset_id": dataset_id,
                    "attr_codes": tuple(attr_codes),
                },
            )
            raw_rows = cursor.fetchall() or []

    pivot: Dict[str, dict] = {}
    for row in raw_rows:
        sample_key = row["sample_key"]
        entry = pivot.setdefault(sample_key, {})
        entry[row["attr_code"]] = row["attr_value"]
    return list(pivot.values())


def _upsert_kg_node(
    dataset_id: int,
    node_type: str,
    node_key: str,
    display_name: Optional[str],
    metadata: Optional[dict],
) -> int:
    upsert_sql = """
    INSERT INTO enterprise_kg_node (
        dataset_id, node_type, node_key, display_name, metadata_json, is_deleted
    ) VALUES (
        %(dataset_id)s, %(node_type)s, %(node_key)s, %(display_name)s, %(metadata_json)s, 0
    )
    ON DUPLICATE KEY UPDATE
        display_name = VALUES(display_name),
        metadata_json = VALUES(metadata_json),
        is_deleted = 0
    """
    query_sql = """
    SELECT id
    FROM enterprise_kg_node
    WHERE dataset_id = %(dataset_id)s AND node_type = %(node_type)s AND node_key = %(node_key)s
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                upsert_sql,
                {
                    "dataset_id": dataset_id,
                    "node_type": node_type,
                    "node_key": node_key,
                    "display_name": display_name,
                    "metadata_json": json.dumps(metadata, ensure_ascii=False)
                    if metadata
                    else None,
                },
            )
            cursor.execute(
                query_sql,
                {
                    "dataset_id": dataset_id,
                    "node_type": node_type,
                    "node_key": node_key,
                },
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError(f"节点创建后读取失败: {node_type}:{node_key}")
            return row["id"]


def _save_implicit_edges(
    dataset_id: int,
    sensitive_attr: dict,
    analysis_result: dict,
    calc_batch_id: str,
) -> None:
    sensitive_node_id = _upsert_kg_node(
        dataset_id=dataset_id,
        node_type="attribute",
        node_key=sensitive_attr["attr_code"],
        display_name=sensitive_attr["attr_name"],
        metadata={"is_sensitive": True},
    )
    insert_sql = """
    INSERT INTO enterprise_kg_edge_implicit (
        dataset_id,
        from_node_id,
        to_node_id,
        sensitive_attr_id,
        metric_type,
        metric_value,
        pic_value,
        risk_value,
        calc_batch_id,
        source_type,
        evidence_json,
        confidence
    ) VALUES (
        %(dataset_id)s,
        %(from_node_id)s,
        %(to_node_id)s,
        %(sensitive_attr_id)s,
        %(metric_type)s,
        %(metric_value)s,
        %(pic_value)s,
        %(risk_value)s,
        %(calc_batch_id)s,
        'calc',
        %(evidence_json)s,
        %(confidence)s
    )
    """
    rows = []
    for item in analysis_result["all_results"]:
        combo = item["combo_attrs"]
        combo_key = "|".join(combo)
        from_node_id = _upsert_kg_node(
            dataset_id=dataset_id,
            node_type="attribute_group",
            node_key=combo_key,
            display_name=combo_key,
            metadata={"combo_attrs": combo},
        )
        rows.append(
            {
                "dataset_id": dataset_id,
                "from_node_id": from_node_id,
                "to_node_id": sensitive_node_id,
                "sensitive_attr_id": sensitive_attr["id"],
                "metric_type": "lr",
                "metric_value": item["lr"],
                "pic_value": item["pic"],
                "risk_value": item["risk"],
                "calc_batch_id": calc_batch_id,
                "evidence_json": json.dumps(
                    {
                        "combo_attrs": combo,
                        "sample_size": item["sample_size"],
                        "mutual_information": item["mutual_information"],
                        "entropy_sensitive": item["entropy_sensitive"],
                    },
                    ensure_ascii=False,
                ),
                "confidence": 0.8,
            }
        )
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(insert_sql, rows)


def analyze_dataset_risk(
    dataset_code: str,
    sensitive_attr_code: str,
    candidate_attr_codes: Optional[List[str]] = None,
    pic_defaults: Optional[Dict[str, float]] = None,
    default_pic: float = 0.5,
    max_combination_size: int = 3,
    sampling_times: int = 200,
    theta: float = 0.2,
) -> dict:
    dataset = _fetch_dataset(dataset_code)
    if dataset is None:
        raise ValueError(f"数据集不存在: {dataset_code}")
    dataset_id = dataset["id"]

    attributes = _fetch_attributes(dataset_id)
    attr_map = {a["attr_code"]: a for a in attributes}
    sensitive_attr = attr_map.get(sensitive_attr_code)
    if sensitive_attr is None:
        raise ValueError(f"敏感属性不存在: {sensitive_attr_code}")

    if candidate_attr_codes:
        candidates = [code for code in candidate_attr_codes if code != sensitive_attr_code]
    else:
        candidates = [
            a["attr_code"]
            for a in attributes
            if a["attr_code"] != sensitive_attr_code and int(a["is_sensitive"]) == 0
        ]
    if not candidates:
        raise ValueError("无可用候选属性，请先注册非敏感属性。")

    effective_pic = dict(pic_defaults or {})
    for attr in attributes:
        code = attr["attr_code"]
        if code not in effective_pic and attr.get("default_pic") is not None:
            effective_pic[code] = float(attr["default_pic"])

    need_attrs = list(set(candidates + [sensitive_attr_code]))
    rows = _fetch_sample_rows(dataset_id=dataset_id, attr_codes=need_attrs)
    if not rows:
        raise ValueError("样本为空或样本属性值缺失，无法执行分析。")

    result = compute_explicit_implicit_scores(
        rows=rows,
        sensitive_attr=sensitive_attr_code,
        candidate_attrs=candidates,
        pic_defaults=effective_pic,
        default_pic=default_pic,
        max_combination_size=max_combination_size,
        sampling_times=sampling_times,
        theta=theta,
    )
    calc_batch_id = f"batch_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    _save_implicit_edges(
        dataset_id=dataset_id,
        sensitive_attr=sensitive_attr,
        analysis_result=result,
        calc_batch_id=calc_batch_id,
    )

    return {
        "dataset_code": dataset_code,
        "dataset_id": dataset_id,
        "calc_batch_id": calc_batch_id,
        "risk_final": result["risk_final"],
        "theta": result["theta"],
        "is_high_risk": result["is_high_risk"],
        "top_results": result["top_results"],
    }
