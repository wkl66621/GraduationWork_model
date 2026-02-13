"""
收集并导出所有 API 路由。
"""

from fastapi import APIRouter

from .fingerprint import router as fingerprint_router


api_router = APIRouter()
api_router.include_router(fingerprint_router)

__all__ = ["api_router"]

