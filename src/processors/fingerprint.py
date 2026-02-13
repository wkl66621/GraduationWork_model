"""
指纹计算模块。

当前仅提供 MD5 计算，后续可以在此扩展为：
- SHA256
- SimHash
- 向量化指纹（embedding 等）
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union


def md5_text(text: str) -> str:
    """
    对字符串内容计算 MD5，返回 32 位十六进制字符串。
    """
    m = hashlib.md5()
    # 明确指定 utf-8，避免平台差异
    m.update(text.encode("utf-8"))
    return m.hexdigest()


def md5_file(path: Union[str, Path], chunk_size: int = 8192) -> str:
    """
    对文件内容计算 MD5，采用分块读取以支持大文件。
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {p}")

    m = hashlib.md5()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            m.update(chunk)
    return m.hexdigest()

