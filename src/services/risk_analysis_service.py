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
import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from src.config.settings import settings
from src.database.connection import get_connection
from src.processors.explicit_implicit_analysis import compute_explicit_implicit_scores


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
    """将数值安全转换为浮点数。

    Args:
        value: 任意输入值。
        default: 转换失败时默认值。

    Returns:
        float: 转换后的浮点数。
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


def _fetch_dataset(dataset_code: str) -> Optional[dict]:
    """按数据集编码查询数据集。

    Args:
        dataset_code: 数据集编码。

    Returns:
        Optional[dict]: 命中时返回数据集记录，否则返回 `None`。
    """
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
    """查询数据集下的属性定义。

    Args:
        dataset_id: 数据集 ID。

    Returns:
        List[dict]: 属性列表，按主键升序返回。
    """
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
    """拉取并透视样本属性值。

    Args:
        dataset_id: 数据集 ID。
        attr_codes: 需要参与分析的属性编码集合。

    Returns:
        List[dict]: 以样本为单位的扁平字典列表。
    """
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
    """创建或更新图谱节点并返回节点 ID。

    Args:
        dataset_id: 数据集 ID。
        node_type: 节点类型。
        node_key: 节点业务键。
        display_name: 展示名称。
        metadata: 扩展元数据。

    Returns:
        int: 节点主键 ID。

    Raises:
        RuntimeError: 节点写入后无法回读时抛出。
    """
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
    """将风险分析结果保存为隐性关系边。

    Args:
        dataset_id: 数据集 ID。
        sensitive_attr: 敏感属性信息。
        analysis_result: 风险计算结果（包含全部组合）。
        calc_batch_id: 当前计算批次号。

    Returns:
        None: 仅执行数据库写入。
    """
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
    """执行数据集隐性关系与泄露风险分析。

    Args:
        dataset_code: 数据集编码。
        sensitive_attr_code: 敏感属性编码。
        candidate_attr_codes: 可选候选属性集合，不传则自动推断非敏感属性。
        pic_defaults: 属性级 PIC 默认值映射。
        default_pic: 未命中映射时的默认 PIC。
        max_combination_size: 组合属性最大阶数。
        sampling_times: 联合 PIC 采样次数。
        theta: 高风险阈值。

    Returns:
        dict: 风险总览、批次号与 Top 风险组合。

    Raises:
        ValueError: 数据集、属性或样本数据不满足分析条件时抛出。
    """
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


def get_latest_implicit_risk_visualization(
    dataset_code: str,
    theta: float = 0.2,
    top_n: int = 20,
) -> dict:
    """构建数据集最新隐性风险批次的可视化数据。

    Args:
        dataset_code: 数据集编码。
        theta: 风险阈值，用于计算高风险标记。
        top_n: 图表和表格返回记录上限。

    Returns:
        dict: 前端可直接消费的可视化聚合结果。

    Raises:
        ValueError: 数据集不存在或尚无隐性分析结果时抛出。
    """
    dataset = _fetch_dataset(dataset_code)
    if dataset is None:
        raise ValueError(f"数据集不存在: {dataset_code}")
    dataset_id = int(dataset["id"])
    top_k = max(1, int(top_n))

    latest_batch_sql = """
    SELECT calc_batch_id
    FROM enterprise_kg_edge_implicit
    WHERE dataset_id = %(dataset_id)s AND calc_batch_id IS NOT NULL
    ORDER BY id DESC
    LIMIT 1
    """
    detail_sql = """
    SELECT
        e.id,
        e.metric_value,
        e.pic_value,
        e.risk_value,
        e.evidence_json,
        e.calc_batch_id,
        n.node_key AS combo_key
    FROM enterprise_kg_edge_implicit e
    INNER JOIN enterprise_kg_node n ON n.id = e.from_node_id
    WHERE e.dataset_id = %(dataset_id)s
      AND e.calc_batch_id = %(calc_batch_id)s
    ORDER BY e.risk_value DESC, e.id DESC
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(latest_batch_sql, {"dataset_id": dataset_id})
            latest_row = cursor.fetchone()
            if latest_row is None or not latest_row.get("calc_batch_id"):
                raise ValueError(f"数据集尚无隐性风险批次: {dataset_code}")
            calc_batch_id = latest_row["calc_batch_id"]
            cursor.execute(
                detail_sql,
                {
                    "dataset_id": dataset_id,
                    "calc_batch_id": calc_batch_id,
                },
            )
            rows = cursor.fetchall() or []

    if not rows:
        raise ValueError(f"批次未查询到隐性风险结果: {calc_batch_id}")

    table_rows: List[dict] = []
    for row in rows:
        evidence = _safe_json_load(row.get("evidence_json")) or {}
        combo_attrs = evidence.get("combo_attrs")
        if not combo_attrs:
            combo_attrs = str(row.get("combo_key", "")).split("|")
        sample_size = int(evidence.get("sample_size", 0) or 0)
        table_rows.append(
            {
                "combo_attrs": [str(item) for item in combo_attrs if str(item).strip()],
                "combo_label": " + ".join(
                    [str(item) for item in combo_attrs if str(item).strip()]
                ),
                "sample_size": sample_size,
                "lr": _to_float(row.get("metric_value")),
                "pic": _to_float(row.get("pic_value")),
                "risk": _to_float(row.get("risk_value")),
                "mutual_information": _to_float(evidence.get("mutual_information")),
                "entropy_sensitive": _to_float(evidence.get("entropy_sensitive")),
            }
        )

    table_rows.sort(key=lambda item: item["risk"], reverse=True)
    risk_final = max(item["risk"] for item in table_rows)
    threshold = float(theta)
    selected_rows = table_rows[:top_k]

    return {
        "dataset_code": dataset_code,
        "dataset_id": dataset_id,
        "calc_batch_id": rows[0]["calc_batch_id"],
        "cards": {
            "risk_final": risk_final,
            "theta": threshold,
            "is_high_risk": risk_final > threshold,
            "combo_count": len(table_rows),
        },
        "chart_series": {
            "risk_bar": [
                {
                    "combo_label": item["combo_label"],
                    "risk": item["risk"],
                }
                for item in selected_rows
            ],
            "lr_pic_scatter": [
                {
                    "combo_label": item["combo_label"],
                    "x_lr": item["lr"],
                    "y_pic": item["pic"],
                    "risk": item["risk"],
                    "sample_size": item["sample_size"],
                }
                for item in selected_rows
            ],
        },
        "table_rows": selected_rows,
    }


def _viz_output_dir(module_name: str) -> Path:
    """获取可视化输出目录并确保存在。

    Args:
        module_name: 模块子目录名称。

    Returns:
        Path: 可写入的输出目录路径。
    """
    output_dir = (settings.paths.output_dir / "visualization" / module_name).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_cache_key(payload: dict) -> str:
    """为绘图参数构建稳定缓存键。

    Args:
        payload: 绘图输入参数。

    Returns:
        str: SHA256 前缀缓存键。
    """
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def export_latest_implicit_risk_image(
    dataset_code: str,
    chart_type: str = "risk_bar",
    theta: float = 0.2,
    top_n: int = 20,
    dpi: int = 200,
    image_format: str = "png",
) -> dict:
    """导出最新隐性风险图像并返回文件元数据。

    Args:
        dataset_code: 数据集编码。
        chart_type: 图类型，支持 `risk_bar/lr_pic_scatter`。
        theta: 风险阈值。
        top_n: 展示组合上限。
        dpi: 图像分辨率。
        image_format: 图片格式，支持 `png/svg`。

    Returns:
        dict: 图像路径与图表元数据。
    """
    fmt = str(image_format).strip().lower()
    if fmt not in {"png", "svg"}:
        raise ValueError(f"不支持的图片格式: {image_format}")
    ctype = str(chart_type).strip().lower()
    if ctype not in {"risk_bar", "lr_pic_scatter"}:
        raise ValueError(f"不支持的图类型: {chart_type}")

    viz_payload = get_latest_implicit_risk_visualization(
        dataset_code=dataset_code,
        theta=theta,
        top_n=top_n,
    )
    chart_rows = viz_payload["chart_series"][ctype]
    cache_key = _build_cache_key(
        {
            "dataset_code": dataset_code,
            "calc_batch_id": viz_payload["calc_batch_id"],
            "chart_type": ctype,
            "theta": float(theta),
            "top_n": int(top_n),
            "dpi": int(dpi),
            "format": fmt,
            "row_count": len(chart_rows),
        }
    )
    output_dir = _viz_output_dir("implicit_risk")
    filename = f"{dataset_code}_{viz_payload['calc_batch_id']}_{ctype}_{cache_key}.{fmt}"
    file_path = (output_dir / filename).resolve()
    if not file_path.exists():
        sns.set_theme(style="whitegrid", context="talk")
        fig, ax = plt.subplots(figsize=(12, 7))
        if ctype == "risk_bar":
            labels = [item["combo_label"] for item in chart_rows]
            values = [item["risk"] for item in chart_rows]
            palette = sns.color_palette("Blues_r", n_colors=max(3, len(values)))
            sns.barplot(x=values, y=labels, ax=ax, palette=palette)
            ax.set_title("Implicit Risk Top Combinations")
            ax.set_xlabel("Risk Score")
            ax.set_ylabel("Attribute Combination")
            ax.axvline(float(theta), color="#D1495B", linestyle="--", linewidth=1.5, label=f"Theta={float(theta):.2f}")
            ax.legend(loc="lower right")
        else:
            x_vals = [item["x_lr"] for item in chart_rows]
            y_vals = [item["y_pic"] for item in chart_rows]
            risks = [item["risk"] for item in chart_rows]
            sizes = [max(40.0, item["sample_size"] * 1.2) for item in chart_rows]
            scatter = ax.scatter(
                x_vals,
                y_vals,
                s=sizes,
                c=risks,
                cmap="viridis",
                alpha=0.85,
                edgecolors="white",
                linewidths=0.6,
            )
            ax.set_title("LR-PIC Risk Scatter")
            ax.set_xlabel("LR")
            ax.set_ylabel("PIC")
            fig.colorbar(scatter, ax=ax, label="Risk")
        fig.tight_layout()
        fig.savefig(file_path, dpi=max(72, int(dpi)), format=fmt)
        plt.close(fig)

    return {
        "dataset_code": dataset_code,
        "calc_batch_id": viz_payload["calc_batch_id"],
        "chart_type": ctype,
        "image_format": fmt,
        "image_path": str(file_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "chart_meta": {
            "theta": float(theta),
            "top_n": int(top_n),
            "dpi": int(dpi),
            "row_count": len(chart_rows),
        },
    }
