"""
CoBAn API 路由模块。

职责：
- 提供 CoBAn 训练、检测与结果查询接口；
- 将 HTTP 请求转换为服务层请求对象；
- 统一处理参数校验与错误映射。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, conint, confloat, constr

from src.database.connection import get_connection
from src.services.coban_detection_service import (
    CobanDetectionRequest,
    CobanDetectionResult,
    detect_coban_confidentiality,
)
from src.services.coban_training_service import (
    CobanTrainingRequest,
    CobanTrainingResult,
    train_coban_model,
)


router = APIRouter(prefix="/api/v1/coban", tags=["coban"])


def _safe_json_load(value: Any) -> Any:
    """将数据库中的 JSON 字段转换为 Python 对象。

    Args:
        value: 数据库读取到的值，可能是 `dict/list/str/None`。

    Returns:
        Any: 解析后的对象；当解析失败时返回原值。
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


def _safe_datetime_to_iso(value: Any) -> Optional[str]:
    """将 datetime 字段转换为 ISO 字符串。"""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


class CobanTrainRequest(BaseModel):
    """CoBAn 训练请求体。"""

    run_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=255)] = None
    dataset_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=255)] = None
    source_type: constr(strip_whitespace=True, min_length=1, max_length=32) = "mixed"
    real_confidential_dirs: List[str] = Field(default_factory=list, description="真实机密语料目录列表。")
    real_non_confidential_dirs: List[str] = Field(
        default_factory=list, description="真实非机密语料目录列表。"
    )
    use_mock: bool = Field(True, description="是否启用内置 mock 语料。")
    stopwords_path: Optional[str] = Field(None, description="停用词文件路径。")
    ngram_range: Tuple[conint(ge=1), conint(ge=1)] = Field((1, 3), description="ngram 范围。")
    n_clusters: conint(ge=1, le=200) = 3
    random_state: int = 42
    max_iter: conint(ge=10, le=5000) = 300
    context_span: conint(ge=1, le=200) = 20
    top_k_conf_terms: conint(ge=1, le=5000) = 120
    top_k_context_terms: conint(ge=1, le=1000) = 30
    min_edge_weight: confloat(ge=0) = 0.0
    cluster_similarity_threshold: confloat(ge=0, le=1) = 0.05
    detection_threshold: confloat(ge=0, le=1) = 0.8
    artifact_dir: Optional[str] = None


class CobanTrainResponse(BaseModel):
    """CoBAn 训练结果响应体。"""

    run_id: str
    model_run_pk: int
    train_doc_count: int
    conf_doc_count: int
    non_conf_doc_count: int
    cluster_count: int
    confidential_term_count: int
    context_term_count: int
    graph_edge_count: int
    model_artifact_path: str
    metrics: Dict[str, float]


class CobanDetectRequest(BaseModel):
    """CoBAn 检测请求体。"""

    input_text: constr(strip_whitespace=True, min_length=1) = Field(..., description="待检测文本。")
    doc_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=255)] = None
    doc_path: Optional[str] = None
    run_id: Optional[constr(strip_whitespace=True, min_length=1, max_length=64)] = None
    top_k_clusters: conint(ge=1, le=20) = 3
    cluster_similarity_threshold: Optional[confloat(ge=0, le=1)] = None
    irregular_ratio_threshold: confloat(ge=1, le=1000) = 20.0
    detection_threshold: Optional[confloat(ge=0, le=1)] = None


class CobanDetectResponse(BaseModel):
    """CoBAn 检测响应体。"""

    run_id: str
    doc_uid: str
    confidentiality_score: float
    threshold_value: float
    is_confidential: bool
    matched_clusters: List[Dict[str, float]]
    evidence_terms: Dict[str, List[str]]
    decision_reason: str


class CobanModelDetailResponse(BaseModel):
    """CoBAn 模型批次详情响应体。"""

    id: int
    run_id: str
    run_name: Optional[str]
    dataset_name: Optional[str]
    source_type: str
    train_doc_count: int
    conf_doc_count: int
    non_conf_doc_count: int
    params: Dict[str, Any]
    metrics: Dict[str, Any]
    model_artifact_path: Optional[str]
    status: str
    start_time: Optional[str]
    end_time: Optional[str]
    create_time: Optional[str]
    update_time: Optional[str]


class CobanDetectionDetailResponse(BaseModel):
    """CoBAn 检测记录详情响应体。"""

    id: int
    run_id: str
    doc_uid: str
    doc_name: Optional[str]
    doc_path: Optional[str]
    confidentiality_score: float
    threshold_value: float
    is_confidential: bool
    matched_clusters: List[Dict[str, Any]]
    evidence: Dict[str, Any]
    decision_reason: Optional[str]
    create_time: Optional[str]
    update_time: Optional[str]


@router.post(
    "/train",
    response_model=CobanTrainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交 CoBAn 训练任务",
)
def train_endpoint(req: CobanTrainRequest) -> CobanTrainResponse:
    """执行 CoBAn 训练任务。"""

    if req.ngram_range[1] < req.ngram_range[0]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ngram_range 必须满足 max_n >= min_n。",
        )
    request = CobanTrainingRequest(
        run_name=req.run_name,
        dataset_name=req.dataset_name,
        source_type=req.source_type,
        real_confidential_dirs=req.real_confidential_dirs,
        real_non_confidential_dirs=req.real_non_confidential_dirs,
        use_mock=req.use_mock,
        stopwords_path=req.stopwords_path,
        ngram_range=(int(req.ngram_range[0]), int(req.ngram_range[1])),
        n_clusters=req.n_clusters,
        random_state=req.random_state,
        max_iter=req.max_iter,
        context_span=req.context_span,
        top_k_conf_terms=req.top_k_conf_terms,
        top_k_context_terms=req.top_k_context_terms,
        min_edge_weight=float(req.min_edge_weight),
        cluster_similarity_threshold=float(req.cluster_similarity_threshold),
        detection_threshold=float(req.detection_threshold),
        artifact_dir=req.artifact_dir,
    )
    try:
        result: CobanTrainingResult = train_coban_model(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CoBAn 训练失败: {exc}",
        ) from exc
    return CobanTrainResponse(**result.__dict__)


@router.post(
    "/detect",
    response_model=CobanDetectResponse,
    summary="提交 CoBAn 检测任务",
)
def detect_endpoint(req: CobanDetectRequest) -> CobanDetectResponse:
    """执行 CoBAn 文本检测。"""

    request = CobanDetectionRequest(
        input_text=req.input_text,
        doc_name=req.doc_name,
        doc_path=req.doc_path,
        run_id=req.run_id,
        top_k_clusters=req.top_k_clusters,
        cluster_similarity_threshold=(
            float(req.cluster_similarity_threshold)
            if req.cluster_similarity_threshold is not None
            else None
        ),
        irregular_ratio_threshold=float(req.irregular_ratio_threshold),
        detection_threshold=(
            float(req.detection_threshold) if req.detection_threshold is not None else None
        ),
    )
    try:
        result: CobanDetectionResult = detect_coban_confidentiality(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CoBAn 检测失败: {exc}",
        ) from exc
    return CobanDetectResponse(**result.__dict__)


@router.get(
    "/models/{run_id}",
    response_model=CobanModelDetailResponse,
    summary="查询 CoBAn 训练批次详情",
)
def get_model_detail(run_id: str) -> CobanModelDetailResponse:
    """读取指定 run_id 的训练批次信息。"""

    sql = """
    SELECT
        id, run_id, run_name, dataset_name, source_type,
        train_doc_count, conf_doc_count, non_conf_doc_count,
        params_json, metrics_json, model_artifact_path,
        status, start_time, end_time, create_time, update_time
    FROM coban_model_run
    WHERE run_id = %(run_id)s AND is_deleted = 0
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"run_id": run_id})
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到训练批次: {run_id}",
        )
    return CobanModelDetailResponse(
        id=int(row["id"]),
        run_id=row["run_id"],
        run_name=row.get("run_name"),
        dataset_name=row.get("dataset_name"),
        source_type=row.get("source_type", "mixed"),
        train_doc_count=int(row.get("train_doc_count", 0)),
        conf_doc_count=int(row.get("conf_doc_count", 0)),
        non_conf_doc_count=int(row.get("non_conf_doc_count", 0)),
        params=_safe_json_load(row.get("params_json")) or {},
        metrics=_safe_json_load(row.get("metrics_json")) or {},
        model_artifact_path=row.get("model_artifact_path"),
        status=row.get("status", "unknown"),
        start_time=_safe_datetime_to_iso(row.get("start_time")),
        end_time=_safe_datetime_to_iso(row.get("end_time")),
        create_time=_safe_datetime_to_iso(row.get("create_time")),
        update_time=_safe_datetime_to_iso(row.get("update_time")),
    )


@router.get(
    "/detections/{doc_uid}",
    response_model=CobanDetectionDetailResponse,
    summary="查询 CoBAn 检测记录详情",
)
def get_detection_detail(doc_uid: str) -> CobanDetectionDetailResponse:
    """读取指定文档 UID 的检测结果。"""

    sql = """
    SELECT
        d.id,
        d.doc_uid,
        d.doc_name,
        d.doc_path,
        d.confidentiality_score,
        d.threshold_value,
        d.is_confidential,
        d.matched_clusters_json,
        d.evidence_json,
        d.decision_reason,
        d.create_time,
        d.update_time,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到检测记录: {doc_uid}",
        )
    return CobanDetectionDetailResponse(
        id=int(row["id"]),
        run_id=row["run_uid"],
        doc_uid=row["doc_uid"],
        doc_name=row.get("doc_name"),
        doc_path=row.get("doc_path"),
        confidentiality_score=float(row.get("confidentiality_score", 0.0)),
        threshold_value=float(row.get("threshold_value", 0.0)),
        is_confidential=bool(int(row.get("is_confidential", 0))),
        matched_clusters=_safe_json_load(row.get("matched_clusters_json")) or [],
        evidence=_safe_json_load(row.get("evidence_json")) or {},
        decision_reason=row.get("decision_reason"),
        create_time=_safe_datetime_to_iso(row.get("create_time")),
        update_time=_safe_datetime_to_iso(row.get("update_time")),
    )
