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

router = APIRouter(prefix="/api/v1/enterprise-data", tags=["enterprise-data"])


class CreateDatasetRequest(BaseModel):
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
    id: int
    dataset_code: str
    dataset_name: str
    domain_name: Optional[str] = None
    source_system: Optional[str] = None
    description: Optional[str] = None
    status: str


class AttributeItem(BaseModel):
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
    attributes: List[AttributeItem]


class BatchCountResponse(BaseModel):
    success_count: int


class SampleItem(BaseModel):
    sample_key: constr(strip_whitespace=True, min_length=1, max_length=128)
    sample_hash: Optional[constr(strip_whitespace=True, min_length=1, max_length=64)] = None
    source_trace: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=255)
    ] = None
    event_time: Optional[datetime] = None
    values: Dict[str, Any] = Field(default_factory=dict)


class BatchIngestSamplesRequest(BaseModel):
    samples: List[SampleItem]


class BatchIngestSamplesResponse(BaseModel):
    sample_count: int
    value_count: int


class ExplicitEdgeItem(BaseModel):
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
    edges: List[ExplicitEdgeItem]


@router.post(
    "/datasets",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建或更新企业数据集",
)
def create_dataset(req: CreateDatasetRequest) -> DatasetResponse:
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
