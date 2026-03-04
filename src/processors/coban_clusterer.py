"""
CoBAn 聚类模块。

职责：
- 将预处理文本向量化并执行 k-means 聚类；
- 提供文档到簇的相似度计算与候选簇分配能力；
- 输出训练阶段需要的簇中心与簇间相似度矩阵。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class ClusterTrainResult:
    """聚类训练结果。"""

    vectorizer: TfidfVectorizer
    model: KMeans
    labels: List[int]
    centroid_vectors: np.ndarray
    document_vectors: np.ndarray
    cluster_to_doc_indices: Dict[int, List[int]]
    cluster_similarity_matrix: np.ndarray


def train_kmeans_clusters(
    documents: Sequence[str],
    n_clusters: int,
    random_state: int = 42,
    max_iter: int = 300,
) -> ClusterTrainResult:
    """训练 k-means 并返回聚类核心产物。

    Args:
        documents: 预处理后的文档文本序列。
        n_clusters: 聚类簇数。
        random_state: 随机种子。
        max_iter: 最大迭代轮次。

    Returns:
        ClusterTrainResult: 聚类相关的模型与矩阵结果。

    Raises:
        ValueError: 输入文档为空时抛出。
    """

    if not documents:
        raise ValueError("聚类失败：输入文档为空。")
    cluster_count = max(1, min(n_clusters, len(documents)))
    vectorizer = TfidfVectorizer(
        lowercase=False,
        token_pattern=r"(?u)\b\w+\b",
        min_df=1,
    )
    sparse_vectors = vectorizer.fit_transform(documents)
    dense_vectors = sparse_vectors.toarray()
    model = KMeans(
        n_clusters=cluster_count,
        random_state=random_state,
        n_init="auto",
        max_iter=max_iter,
    )
    labels = model.fit_predict(sparse_vectors).tolist()
    centroids = model.cluster_centers_
    cluster_similarity = cosine_similarity(centroids, centroids)

    cluster_to_doc_indices: Dict[int, List[int]] = {idx: [] for idx in range(cluster_count)}
    for doc_idx, cluster_idx in enumerate(labels):
        cluster_to_doc_indices.setdefault(cluster_idx, []).append(doc_idx)

    return ClusterTrainResult(
        vectorizer=vectorizer,
        model=model,
        labels=labels,
        centroid_vectors=centroids,
        document_vectors=dense_vectors,
        cluster_to_doc_indices=cluster_to_doc_indices,
        cluster_similarity_matrix=cluster_similarity,
    )


def assign_document_to_clusters(
    text: str,
    vectorizer: TfidfVectorizer,
    centroid_vectors: np.ndarray,
    top_k: int = 3,
    similarity_threshold: float = 0.05,
) -> List[Tuple[int, float]]:
    """将单个文档分配到若干候选簇。

    Args:
        text: 已预处理文本。
        vectorizer: 训练阶段产出的 TF-IDF 向量器。
        centroid_vectors: 聚类中心矩阵。
        top_k: 返回最高相似度前 k 个簇。
        similarity_threshold: 最低相似度阈值。

    Returns:
        List[Tuple[int, float]]: `(cluster_idx, similarity)` 列表，按相似度降序。
    """

    if centroid_vectors.size == 0:
        return []
    vector = vectorizer.transform([text])
    scores = cosine_similarity(vector, centroid_vectors)[0]
    pairs = [(idx, float(score)) for idx, score in enumerate(scores)]
    pairs.sort(key=lambda item: item[1], reverse=True)

    filtered = [item for item in pairs if item[1] >= similarity_threshold]
    if not filtered:
        return pairs[: max(1, top_k)]
    return filtered[: max(1, top_k)]


def serialize_centroid_vector(centroid_vector: np.ndarray) -> List[float]:
    """将 numpy 向量转换为可序列化列表。"""

    return [float(item) for item in centroid_vector.tolist()]
