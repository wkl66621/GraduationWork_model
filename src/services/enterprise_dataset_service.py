"""
企业数据集与知识图谱底座服务。

当前阶段能力：
1) 企业数据集注册
2) 属性元数据注册
3) 样本及属性值导入
4) 图谱节点与显性关系边写入

说明：
- 本阶段只做“数据集构建 + 关系构建”。
- 不实现数据比对能力。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.database.connection import get_connection


@dataclass
class DatasetPayload:
    dataset_code: str
    dataset_name: str
    domain_name: Optional[str] = None
    source_system: Optional[str] = None
    description: Optional[str] = None
    status: str = "active"


def _normalize_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value).strip()


def _fetch_dataset_by_code(dataset_code: str) -> Optional[dict]:
    sql = """
    SELECT id, dataset_code, dataset_name, domain_name, source_system, description, status
    FROM enterprise_dataset
    WHERE dataset_code = %(dataset_code)s AND is_deleted = 0
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"dataset_code": dataset_code})
            return cursor.fetchone()


def create_or_update_dataset(payload: DatasetPayload) -> dict:
    sql = """
    INSERT INTO enterprise_dataset (
        dataset_code,
        dataset_name,
        domain_name,
        source_system,
        description,
        status,
        version_no,
        is_deleted
    ) VALUES (
        %(dataset_code)s,
        %(dataset_name)s,
        %(domain_name)s,
        %(source_system)s,
        %(description)s,
        %(status)s,
        1,
        0
    )
    ON DUPLICATE KEY UPDATE
        dataset_name = VALUES(dataset_name),
        domain_name = VALUES(domain_name),
        source_system = VALUES(source_system),
        description = VALUES(description),
        status = VALUES(status),
        is_deleted = 0
    """
    params = {
        "dataset_code": payload.dataset_code,
        "dataset_name": payload.dataset_name,
        "domain_name": payload.domain_name,
        "source_system": payload.source_system,
        "description": payload.description,
        "status": payload.status,
    }

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)

    dataset = _fetch_dataset_by_code(payload.dataset_code)
    if dataset is None:
        raise RuntimeError("数据集写入成功但读取失败。")
    return dataset


def register_attributes(dataset_code: str, attributes: List[dict]) -> int:
    dataset = _fetch_dataset_by_code(dataset_code)
    if dataset is None:
        raise ValueError(f"数据集不存在: {dataset_code}")

    dataset_id = dataset["id"]
    sql = """
    INSERT INTO enterprise_attribute (
        dataset_id,
        attr_code,
        attr_name,
        attr_type,
        is_sensitive,
        sensitivity_level,
        is_identifier,
        nullable_flag,
        default_pic,
        description,
        is_deleted
    ) VALUES (
        %(dataset_id)s,
        %(attr_code)s,
        %(attr_name)s,
        %(attr_type)s,
        %(is_sensitive)s,
        %(sensitivity_level)s,
        %(is_identifier)s,
        %(nullable_flag)s,
        %(default_pic)s,
        %(description)s,
        0
    )
    ON DUPLICATE KEY UPDATE
        attr_name = VALUES(attr_name),
        attr_type = VALUES(attr_type),
        is_sensitive = VALUES(is_sensitive),
        sensitivity_level = VALUES(sensitivity_level),
        is_identifier = VALUES(is_identifier),
        nullable_flag = VALUES(nullable_flag),
        default_pic = VALUES(default_pic),
        description = VALUES(description),
        is_deleted = 0
    """

    rows: List[dict] = []
    for item in attributes:
        rows.append(
            {
                "dataset_id": dataset_id,
                "attr_code": item["attr_code"],
                "attr_name": item["attr_name"],
                "attr_type": item["attr_type"],
                "is_sensitive": int(item.get("is_sensitive", 0)),
                "sensitivity_level": int(item.get("sensitivity_level", 0)),
                "is_identifier": int(item.get("is_identifier", 0)),
                "nullable_flag": int(item.get("nullable_flag", 1)),
                "default_pic": item.get("default_pic"),
                "description": item.get("description"),
            }
        )

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)
    return len(rows)


def _fetch_attribute_map(dataset_id: int) -> Dict[str, dict]:
    sql = """
    SELECT id, attr_code, attr_name
    FROM enterprise_attribute
    WHERE dataset_id = %(dataset_id)s AND is_deleted = 0
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"dataset_id": dataset_id})
            rows = cursor.fetchall() or []
    return {row["attr_code"]: row for row in rows}


def ingest_samples(dataset_code: str, samples: List[dict]) -> dict:
    dataset = _fetch_dataset_by_code(dataset_code)
    if dataset is None:
        raise ValueError(f"数据集不存在: {dataset_code}")
    dataset_id = dataset["id"]
    attr_map = _fetch_attribute_map(dataset_id)
    if not attr_map:
        raise ValueError(f"数据集未注册属性，无法导入样本: {dataset_code}")

    insert_sample_sql = """
    INSERT INTO enterprise_sample (
        dataset_id,
        sample_key,
        sample_hash,
        source_trace,
        event_time,
        is_deleted
    ) VALUES (
        %(dataset_id)s,
        %(sample_key)s,
        %(sample_hash)s,
        %(source_trace)s,
        %(event_time)s,
        0
    )
    ON DUPLICATE KEY UPDATE
        sample_hash = VALUES(sample_hash),
        source_trace = VALUES(source_trace),
        event_time = VALUES(event_time),
        is_deleted = 0
    """
    select_sample_sql = """
    SELECT id
    FROM enterprise_sample
    WHERE dataset_id = %(dataset_id)s AND sample_key = %(sample_key)s
    LIMIT 1
    """
    upsert_value_sql = """
    INSERT INTO enterprise_sample_value (
        sample_id,
        attribute_id,
        raw_value,
        normalized_value,
        masked_value,
        is_deleted
    ) VALUES (
        %(sample_id)s,
        %(attribute_id)s,
        %(raw_value)s,
        %(normalized_value)s,
        %(masked_value)s,
        0
    )
    ON DUPLICATE KEY UPDATE
        raw_value = VALUES(raw_value),
        normalized_value = VALUES(normalized_value),
        masked_value = VALUES(masked_value),
        is_deleted = 0
    """

    sample_count = 0
    value_count = 0
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for item in samples:
                cursor.execute(
                    insert_sample_sql,
                    {
                        "dataset_id": dataset_id,
                        "sample_key": item["sample_key"],
                        "sample_hash": item.get("sample_hash"),
                        "source_trace": item.get("source_trace"),
                        "event_time": item.get("event_time"),
                    },
                )
                cursor.execute(
                    select_sample_sql,
                    {"dataset_id": dataset_id, "sample_key": item["sample_key"]},
                )
                sample_row = cursor.fetchone()
                if sample_row is None:
                    raise RuntimeError(f"样本写入后读取失败: {item['sample_key']}")
                sample_id = sample_row["id"]
                sample_count += 1

                values = item.get("values", {})
                for attr_code, raw in values.items():
                    attr = attr_map.get(attr_code)
                    if attr is None:
                        continue
                    cursor.execute(
                        upsert_value_sql,
                        {
                            "sample_id": sample_id,
                            "attribute_id": attr["id"],
                            "raw_value": _normalize_value(raw),
                            "normalized_value": _normalize_value(raw),
                            "masked_value": None,
                        },
                    )
                    value_count += 1

    return {"sample_count": sample_count, "value_count": value_count}


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
    select_sql = """
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
                select_sql,
                {
                    "dataset_id": dataset_id,
                    "node_type": node_type,
                    "node_key": node_key,
                },
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError(f"图谱节点写入后读取失败: {node_type}:{node_key}")
            return row["id"]


def create_explicit_edges(dataset_code: str, edges: List[dict]) -> int:
    dataset = _fetch_dataset_by_code(dataset_code)
    if dataset is None:
        raise ValueError(f"数据集不存在: {dataset_code}")
    dataset_id = dataset["id"]

    edge_sql = """
    INSERT INTO enterprise_kg_edge_explicit (
        dataset_id,
        from_node_id,
        to_node_id,
        relation_type,
        relation_desc,
        source_type,
        evidence_json,
        confidence
    ) VALUES (
        %(dataset_id)s,
        %(from_node_id)s,
        %(to_node_id)s,
        %(relation_type)s,
        %(relation_desc)s,
        %(source_type)s,
        %(evidence_json)s,
        %(confidence)s
    )
    ON DUPLICATE KEY UPDATE
        relation_desc = VALUES(relation_desc),
        source_type = VALUES(source_type),
        evidence_json = VALUES(evidence_json),
        confidence = VALUES(confidence)
    """

    rows = []
    for item in edges:
        from_id = _upsert_kg_node(
            dataset_id=dataset_id,
            node_type=item["from_node_type"],
            node_key=item["from_node_key"],
            display_name=item.get("from_display_name"),
            metadata=item.get("from_metadata"),
        )
        to_id = _upsert_kg_node(
            dataset_id=dataset_id,
            node_type=item["to_node_type"],
            node_key=item["to_node_key"],
            display_name=item.get("to_display_name"),
            metadata=item.get("to_metadata"),
        )
        rows.append(
            {
                "dataset_id": dataset_id,
                "from_node_id": from_id,
                "to_node_id": to_id,
                "relation_type": item["relation_type"],
                "relation_desc": item.get("relation_desc"),
                "source_type": item.get("source_type", "manual"),
                "evidence_json": json.dumps(item.get("evidence"), ensure_ascii=False)
                if item.get("evidence")
                else None,
                "confidence": item.get("confidence", 1.0),
            }
        )

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(edge_sql, rows)
    return len(rows)
