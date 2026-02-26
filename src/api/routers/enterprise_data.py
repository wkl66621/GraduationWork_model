"""
企业数据集与知识图谱底座 API。

当前阶段：
- 支持企业数据集构建与关系写入
- 不提供数据比对能力
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, condecimal, conint, constr

from src.services.enterprise_dataset_service import (
    DatasetPayload,
    create_explicit_edges,
    create_or_update_dataset,
    ingest_samples,
    register_attributes,
)
from src.services.risk_analysis_service import analyze_dataset_risk

router = APIRouter(prefix="/api/v1/enterprise-data", tags=["enterprise-data"])


class CreateDatasetRequest(BaseModel):
    """创建或更新企业数据集的请求体。"""
    dataset_code: constr(strip_whitespace=True, min_length=1, max_length=64) = Field(
        ..., description="数据集编码（企业内唯一）"
    )
    dataset_name: constr(strip_whitespace=True, min_length=1, max_length=255) = Field(
        ..., description="数据集名称"
    )
    domain_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=128)] = (
        Field(None, description="业务域")
    )
    source_system: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=128)
    ] = Field(None, description="来源系统")
    description: Optional[constr(strip_whitespace=True, min_length=1, max_length=1024)] = (
        Field(None, description="描述")
    )
    status: constr(strip_whitespace=True, min_length=1, max_length=32) = Field(
        "active", description="状态：active/inactive"
    )


class DatasetResponse(BaseModel):
    """企业数据集基础信息响应体。"""
    id: int
    dataset_code: str
    dataset_name: str
    domain_name: Optional[str] = None
    source_system: Optional[str] = None
    description: Optional[str] = None
    status: str


class AttributeItem(BaseModel):
    """单个属性元数据定义。"""
    attr_code: constr(strip_whitespace=True, min_length=1, max_length=64)
    attr_name: constr(strip_whitespace=True, min_length=1, max_length=255)
    attr_type: constr(strip_whitespace=True, min_length=1, max_length=32)
    is_sensitive: conint(ge=0, le=1) = 0
    sensitivity_level: conint(ge=0, le=3) = 0
    is_identifier: conint(ge=0, le=1) = 0
    nullable_flag: conint(ge=0, le=1) = 1
    default_pic: Optional[condecimal(ge=0, le=1, max_digits=8, decimal_places=6)] = None
    description: Optional[constr(strip_whitespace=True, min_length=1, max_length=1024)] = (
        None
    )


class BatchRegisterAttributesRequest(BaseModel):
    """批量注册属性请求体。"""
    attributes: List[AttributeItem]


class BatchCountResponse(BaseModel):
    """返回批处理成功数量的通用响应体。"""
    success_count: int


class SampleItem(BaseModel):
    """单个样本及其属性值。"""
    sample_key: constr(strip_whitespace=True, min_length=1, max_length=128)
    sample_hash: Optional[constr(strip_whitespace=True, min_length=1, max_length=64)] = None
    source_trace: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=255)
    ] = None
    event_time: Optional[datetime] = None
    values: Dict[str, Any] = Field(default_factory=dict)


class BatchIngestSamplesRequest(BaseModel):
    """批量导入样本请求体。"""
    samples: List[SampleItem]


class BatchIngestSamplesResponse(BaseModel):
    """批量导入样本结果响应体。"""
    sample_count: int
    value_count: int


class ExplicitEdgeItem(BaseModel):
    """单条显性关系边定义。"""
    from_node_type: constr(strip_whitespace=True, min_length=1, max_length=32)
    from_node_key: constr(strip_whitespace=True, min_length=1, max_length=128)
    from_display_name: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=255)
    ] = None
    from_metadata: Optional[Dict[str, Any]] = None

    to_node_type: constr(strip_whitespace=True, min_length=1, max_length=32)
    to_node_key: constr(strip_whitespace=True, min_length=1, max_length=128)
    to_display_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=255)] = (
        None
    )
    to_metadata: Optional[Dict[str, Any]] = None

    relation_type: constr(strip_whitespace=True, min_length=1, max_length=64)
    relation_desc: Optional[constr(strip_whitespace=True, min_length=1, max_length=1024)] = (
        None
    )
    source_type: constr(strip_whitespace=True, min_length=1, max_length=32) = "manual"
    confidence: condecimal(ge=0, le=1, max_digits=8, decimal_places=6) = 1
    evidence: Optional[Dict[str, Any]] = None


class BatchCreateExplicitEdgesRequest(BaseModel):
    """批量写入显性关系边请求体。"""
    edges: List[ExplicitEdgeItem]


class AnalyzeImplicitRiskRequest(BaseModel):
    """隐性关系与泄露风险分析请求体。"""
    sensitive_attr_code: constr(strip_whitespace=True, min_length=1, max_length=64)
    candidate_attr_codes: Optional[List[constr(strip_whitespace=True, min_length=1, max_length=64)]] = (
        None
    )
    pic_defaults: Optional[Dict[str, condecimal(ge=0, le=1, max_digits=8, decimal_places=6)]] = (
        None
    )
    default_pic: condecimal(ge=0, le=1, max_digits=8, decimal_places=6) = 0.5
    max_combination_size: conint(ge=1, le=6) = 3
    sampling_times: conint(ge=1, le=2000) = 200
    theta: condecimal(ge=0, le=1, max_digits=8, decimal_places=6) = 0.2


class RiskComboResult(BaseModel):
    """单个属性组合的风险计算结果。"""
    combo_attrs: List[str]
    sample_size: int
    mutual_information: float
    lr: float
    pic: float
    risk: float


class AnalyzeImplicitRiskResponse(BaseModel):
    """隐性关系与泄露风险分析响应体。"""
    dataset_code: str
    dataset_id: int
    calc_batch_id: str
    risk_final: float
    theta: float
    is_high_risk: bool
    top_results: List[RiskComboResult]


@router.post(
    "/datasets",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建或更新企业数据集",
)
def create_dataset(req: CreateDatasetRequest) -> DatasetResponse:
    """创建或更新企业数据集。

    Args:
        req: 数据集基础元信息。

    Returns:
        DatasetResponse: 写入后的数据集信息。

    Raises:
        HTTPException: 当服务层抛错时返回 500。
    """
    try:
        dataset = create_or_update_dataset(
            DatasetPayload(
                dataset_code=req.dataset_code,
                dataset_name=req.dataset_name,
                domain_name=req.domain_name,
                source_system=req.source_system,
                description=req.description,
                status=req.status,
            )
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建数据集失败: {e}",
        ) from e
    return DatasetResponse(**dataset)


@router.post(
    "/datasets/{dataset_code}/attributes/batch",
    response_model=BatchCountResponse,
    summary="批量注册数据集属性",
)
def batch_register_attributes(
    dataset_code: str, req: BatchRegisterAttributesRequest
) -> BatchCountResponse:
    """为指定数据集批量注册属性。

    Args:
        dataset_code: 目标数据集编码。
        req: 待注册属性列表。

    Returns:
        BatchCountResponse: 成功写入或更新的属性数量。

    Raises:
        HTTPException: 参数/业务校验失败返回 400，内部错误返回 500。
    """
    try:
        count = register_attributes(
            dataset_code=dataset_code, attributes=[x.model_dump() for x in req.attributes]
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"注册属性失败: {e}",
        ) from e
    return BatchCountResponse(success_count=count)


@router.post(
    "/datasets/{dataset_code}/samples/batch",
    response_model=BatchIngestSamplesResponse,
    summary="批量导入样本及属性值",
)
def batch_ingest_samples(
    dataset_code: str, req: BatchIngestSamplesRequest
) -> BatchIngestSamplesResponse:
    """批量导入样本及属性值。

    Args:
        dataset_code: 目标数据集编码。
        req: 样本列表，请求中每个样本可包含多个属性值。

    Returns:
        BatchIngestSamplesResponse: 成功处理的样本数与属性值数。

    Raises:
        HTTPException: 参数/业务校验失败返回 400，内部错误返回 500。
    """
    try:
        result = ingest_samples(
            dataset_code=dataset_code, samples=[x.model_dump() for x in req.samples]
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入样本失败: {e}",
        ) from e
    return BatchIngestSamplesResponse(**result)


@router.post(
    "/datasets/{dataset_code}/kg/edges/explicit/batch",
    response_model=BatchCountResponse,
    summary="批量写入显性关系边",
)
def batch_create_explicit_edges(
    dataset_code: str, req: BatchCreateExplicitEdgesRequest
) -> BatchCountResponse:
    """批量写入显性关系边。

    Args:
        dataset_code: 目标数据集编码。
        req: 显性关系边列表。

    Returns:
        BatchCountResponse: 成功写入的关系边数量。

    Raises:
        HTTPException: 参数/业务校验失败返回 400，内部错误返回 500。
    """
    try:
        count = create_explicit_edges(
            dataset_code=dataset_code, edges=[x.model_dump() for x in req.edges]
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写入显性关系边失败: {e}",
        ) from e
    return BatchCountResponse(success_count=count)


@router.post(
    "/datasets/{dataset_code}/analysis/implicit-risk",
    response_model=AnalyzeImplicitRiskResponse,
    summary="执行隐性关系与泄露风险分析",
)
def analyze_implicit_risk(
    dataset_code: str, req: AnalyzeImplicitRiskRequest
) -> AnalyzeImplicitRiskResponse:
    """执行隐性关系与泄露风险计算。

    Args:
        dataset_code: 目标数据集编码。
        req: 计算参数，包括敏感属性、候选属性、PIC 默认值和阈值等。

    Returns:
        AnalyzeImplicitRiskResponse: 风险总览及高风险组合结果。

    Raises:
        HTTPException: 参数/业务校验失败返回 400，内部错误返回 500。
    """
    try:
        result = analyze_dataset_risk(
            dataset_code=dataset_code,
            sensitive_attr_code=req.sensitive_attr_code,
            candidate_attr_codes=req.candidate_attr_codes,
            pic_defaults=dict(req.pic_defaults) if req.pic_defaults else None,
            default_pic=float(req.default_pic),
            max_combination_size=req.max_combination_size,
            sampling_times=req.sampling_times,
            theta=float(req.theta),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"执行隐性关系分析失败: {e}",
        ) from e
    return AnalyzeImplicitRiskResponse(**result)
