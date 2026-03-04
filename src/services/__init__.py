"""
服务层模块。

主要负责编排：
- 文件读取
- 分段/分句
- 指纹计算
- 写入数字指纹库（digital_fingerprint_doc）
"""

from src.services.coban_detection_service import (
    CobanDetectionRequest,
    CobanDetectionResult,
    detect_coban_confidentiality,
)
from src.services.coban_training_service import (
    CobanTrainingRequest,
    CobanTrainingResult,
    preview_cluster_assignment,
    train_coban_model,
)

__all__ = [
    "CobanTrainingRequest",
    "CobanTrainingResult",
    "train_coban_model",
    "preview_cluster_assignment",
    "CobanDetectionRequest",
    "CobanDetectionResult",
    "detect_coban_confidentiality",
]

