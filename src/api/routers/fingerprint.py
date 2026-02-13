"""
数字指纹相关 API。

当前提供：
- 根据本地 txt 文件路径生成数字指纹，并写入 digital_fingerprint_doc。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, constr, conint

from src.services.fingerprint_service import ingest_text_file


router = APIRouter(prefix="/api/v1/fingerprints", tags=["fingerprints"])


class IngestFromFileRequest(BaseModel):
    """
    从本地 txt 文件导入数字指纹的请求体。
    """

    file_path: str = Field(
        ...,
        description="本地 txt 文件的绝对路径或相对路径（相对项目根目录）。",
        example="data/input/example.txt",
    )
    doc_unique_id: Optional[constr(strip_whitespace=True, min_length=1)] = Field(
        None, description="可选，指定文档唯一ID；不传则自动生成 UUID。"
    )
    doc_source: constr(strip_whitespace=True, min_length=1) = Field(
        "local_import", description="文档来源（如 upload/system_import 等）。"
    )
    sensitive_level: conint(ge=0, le=3) = Field(
        0, description="敏感等级（0-无，1-低，2-中，3-高）。"
    )
    max_sentence_length: conint(gt=0, le=5000) = Field(
        500, description="分句时的最大长度，过长句子会再切分。"
    )


class IngestResponse(BaseModel):
    """
    导入指纹后的响应体。
    """

    doc_unique_id: str = Field(..., description="实际使用的文档唯一ID。")


@router.post(
    "/from-file",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="从本地 txt 文件生成数字指纹",
    response_description="返回文档唯一ID。",
)
def ingest_from_file(req: IngestFromFileRequest) -> IngestResponse:
    """
    从本地 txt 文件生成数字指纹并写入 `digital_fingerprint_doc`。

    注意：
    - 仅在服务器本机运行（不适合作为对外互联网接口暴露文件路径）。
    - 如果文件路径不存在，将返回 400 错误。
    """
    try:
        doc_id = ingest_text_file(
            file_path=req.file_path,
            doc_unique_id=req.doc_unique_id,
            doc_source=req.doc_source,
            sensitive_level=req.sensitive_level,
            max_sentence_length=req.max_sentence_length,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        # 这里不暴露内部细节，只返回泛化错误信息，详细错误可通过日志查看
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成数字指纹时发生内部错误。",
        ) from e

    return IngestResponse(doc_unique_id=doc_id)

