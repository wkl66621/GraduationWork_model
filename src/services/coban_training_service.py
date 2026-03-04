"""
CoBAn 训练编排服务。

职责：
- 统一加载真实语料与 mock 语料；
- 编排预处理、聚类、术语打分、术语图构建；
- 持久化训练产物并写入 CoBAn 相关数据库表。
"""

from __future__ import annotations

import json
import pickle
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.config.settings import settings
from src.database.connection import get_connection
from src.processors.coban_clusterer import (
    assign_document_to_clusters,
    train_kmeans_clusters,
)
from src.processors.coban_graph_builder import build_conf_context_graph
from src.processors.coban_language_model import score_confidential_terms, score_context_terms
from src.processors.coban_text_preprocessor import (
    CobanCorpusDocument,
    load_documents_from_directory,
    load_stopwords,
)


@dataclass
class CobanTrainingRequest:
    """CoBAn 训练请求参数。"""

    run_name: Optional[str] = None
    dataset_name: Optional[str] = None
    source_type: str = "mock"
    real_confidential_dirs: List[str] = field(default_factory=list)
    real_non_confidential_dirs: List[str] = field(default_factory=list)
    use_mock: bool = True
    stopwords_path: Optional[str] = None
    ngram_range: Tuple[int, int] = (1, 3)
    n_clusters: int = 3
    random_state: int = 42
    max_iter: int = 300
    context_span: int = 20
    top_k_conf_terms: int = 120
    top_k_context_terms: int = 30
    min_edge_weight: float = 0.0
    cluster_similarity_threshold: float = 0.05
    detection_threshold: float = 0.8
    artifact_dir: Optional[str] = None


@dataclass
class CobanTrainingResult:
    """CoBAn 训练结果摘要。"""

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


def _mock_documents() -> List[dict]:
    """提供可直接跑通的 mock 文档样本。"""
    return [
        {
            "doc_name": "mock_fin_conf_01.txt",
            "source_type": "mock",
            "is_confidential": True,
            "label": "finance",
            "raw_text": (
                "财务预算草案包含利润率目标、并购估值区间与季度现金流预测。"
                "该文档为董事会审议前内部材料，禁止外传。"
            ),
        },
        {
            "doc_name": "mock_fin_conf_02.txt",
            "source_type": "mock",
            "is_confidential": True,
            "label": "finance",
            "raw_text": (
                "融资谈判纪要披露授信额度、抵押条款和银行授信利率。"
                "仅限财务总监及核心管理层阅读。"
            ),
        },
        {
            "doc_name": "mock_tech_conf_01.txt",
            "source_type": "mock",
            "is_confidential": True,
            "label": "tech",
            "raw_text": (
                "核心算法设计说明涉及检索排序参数、召回策略和反作弊规则。"
                "模型参数与训练细节均属于研发机密。"
            ),
        },
        {
            "doc_name": "mock_plan_conf_01.txt",
            "source_type": "mock",
            "is_confidential": True,
            "label": "planning",
            "raw_text": (
                "年度战略规划草稿披露市场进入时间窗、渠道预算和关键竞品对标。"
                "该版本仅供战略委员会内部讨论。"
            ),
        },
        {
            "doc_name": "mock_public_01.txt",
            "source_type": "mock",
            "is_confidential": False,
            "label": "public",
            "raw_text": (
                "本周例会纪要主要记录办公区改造计划和团建活动安排，"
                "内容面向全员公开。"
            ),
        },
        {
            "doc_name": "mock_public_02.txt",
            "source_type": "mock",
            "is_confidential": False,
            "label": "public",
            "raw_text": (
                "招聘宣传文案介绍公司文化、福利政策与岗位职责，"
                "用于外部社媒渠道发布。"
            ),
        },
        {
            "doc_name": "mock_public_03.txt",
            "source_type": "mock",
            "is_confidential": False,
            "label": "public",
            "raw_text": (
                "产品帮助中心文档说明基础功能操作步骤和常见问题排查流程，"
                "适合普通用户查阅。"
            ),
        },
    ]


def _build_mock_corpus(
    stopwords: Optional[set[str]],
    ngram_range: Tuple[int, int],
) -> List[CobanCorpusDocument]:
    """构建 mock 语料文档对象。"""
    from src.processors.coban_text_preprocessor import build_corpus_document

    docs: List[CobanCorpusDocument] = []
    for item in _mock_documents():
        docs.append(
            build_corpus_document(
                raw_text=item["raw_text"],
                doc_name=item["doc_name"],
                doc_path=f"mock://{item['doc_name']}",
                source_type=item["source_type"],
                is_confidential=item["is_confidential"],
                label=item["label"],
                stopwords=stopwords,
                ngram_range=ngram_range,
            )
        )
    return docs


def _load_real_corpus(
    source_dirs: Iterable[str],
    source_type: str,
    is_confidential: bool,
    label: str,
    stopwords: Optional[set[str]],
    ngram_range: Tuple[int, int],
) -> List[CobanCorpusDocument]:
    """从目录列表加载真实语料。"""
    docs: List[CobanCorpusDocument] = []
    for directory in source_dirs:
        docs.extend(
            load_documents_from_directory(
                directory=directory,
                source_type=source_type,
                is_confidential=is_confidential,
                label=label,
                stopwords=stopwords,
                ngram_range=ngram_range,
            )
        )
    return docs


def _create_model_run_record(
    run_id: str,
    request: CobanTrainingRequest,
    source_type: str,
    train_doc_count: int,
    conf_doc_count: int,
    non_conf_doc_count: int,
) -> int:
    """创建训练批次记录并返回主键 ID。"""
    insert_sql = """
    INSERT INTO coban_model_run (
        run_id, run_name, dataset_name, source_type,
        train_doc_count, conf_doc_count, non_conf_doc_count,
        params_json, status, start_time, is_deleted
    ) VALUES (
        %(run_id)s, %(run_name)s, %(dataset_name)s, %(source_type)s,
        %(train_doc_count)s, %(conf_doc_count)s, %(non_conf_doc_count)s,
        %(params_json)s, 'running', %(start_time)s, 0
    )
    """
    query_sql = "SELECT id FROM coban_model_run WHERE run_id = %(run_id)s LIMIT 1"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                insert_sql,
                {
                    "run_id": run_id,
                    "run_name": request.run_name,
                    "dataset_name": request.dataset_name,
                    "source_type": source_type,
                    "train_doc_count": train_doc_count,
                    "conf_doc_count": conf_doc_count,
                    "non_conf_doc_count": non_conf_doc_count,
                    "params_json": json.dumps(asdict(request), ensure_ascii=False),
                    "start_time": datetime.now(),
                },
            )
            cursor.execute(query_sql, {"run_id": run_id})
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("训练批次创建成功但无法读取主键。")
            return int(row["id"])


def _persist_training_outputs(
    model_run_pk: int,
    run_id: str,
    docs: Sequence[CobanCorpusDocument],
    cluster_labels: Sequence[int],
    cluster_centroids: Sequence[Sequence[float]],
    cluster_similarity_threshold: float,
    confidential_term_rows: Sequence[dict],
    context_term_rows: Sequence[dict],
    graph_edge_rows: Sequence[dict],
) -> None:
    """写入聚类、文档、术语与图边表。"""
    insert_cluster_sql = """
    INSERT INTO coban_cluster (
        run_id, cluster_code, centroid_json, cluster_size,
        conf_doc_count, non_conf_doc_count, similarity_threshold
    ) VALUES (
        %(run_id)s, %(cluster_code)s, %(centroid_json)s, %(cluster_size)s,
        %(conf_doc_count)s, %(non_conf_doc_count)s, %(similarity_threshold)s
    )
    """
    query_cluster_sql = """
    SELECT id, cluster_code
    FROM coban_cluster
    WHERE run_id = %(run_id)s
    """
    insert_doc_sql = """
    INSERT INTO coban_corpus_document (
        run_id, doc_uid, doc_name, doc_path, raw_text, preprocessed_text,
        source_type, is_confidential, label, assigned_cluster_id, metadata_json
    ) VALUES (
        %(run_id)s, %(doc_uid)s, %(doc_name)s, %(doc_path)s, %(raw_text)s, %(preprocessed_text)s,
        %(source_type)s, %(is_confidential)s, %(label)s, %(assigned_cluster_id)s, %(metadata_json)s
    )
    """
    insert_conf_term_sql = """
    INSERT INTO coban_term_confidential (
        run_id, cluster_id, term_value, term_score,
        conf_probability, non_conf_probability, support_conf_docs, support_non_conf_docs
    ) VALUES (
        %(run_id)s, %(cluster_id)s, %(term_value)s, %(term_score)s,
        %(conf_probability)s, %(non_conf_probability)s, %(support_conf_docs)s, %(support_non_conf_docs)s
    )
    """
    query_conf_term_sql = """
    SELECT id, cluster_id, term_value
    FROM coban_term_confidential
    WHERE run_id = %(run_id)s
    """
    insert_context_sql = """
    INSERT INTO coban_term_context (
        run_id, cluster_id, conf_term_id, context_term, context_score,
        conf_probability, non_conf_probability, support_conf_docs, support_non_conf_docs
    ) VALUES (
        %(run_id)s, %(cluster_id)s, %(conf_term_id)s, %(context_term)s, %(context_score)s,
        %(conf_probability)s, %(non_conf_probability)s, %(support_conf_docs)s, %(support_non_conf_docs)s
    )
    """
    query_context_sql = """
    SELECT id, cluster_id, conf_term_id, context_term
    FROM coban_term_context
    WHERE run_id = %(run_id)s
    """
    insert_edge_sql = """
    INSERT INTO coban_graph_edge (
        run_id, cluster_id, conf_term_id, context_term_id, edge_weight, metadata_json
    ) VALUES (
        %(run_id)s, %(cluster_id)s, %(conf_term_id)s, %(context_term_id)s, %(edge_weight)s, %(metadata_json)s
    )
    """

    cluster_codes = sorted({int(label) for label in cluster_labels})
    cluster_to_docs: Dict[int, List[CobanCorpusDocument]] = {cid: [] for cid in cluster_codes}
    for idx, label in enumerate(cluster_labels):
        cluster_to_docs[int(label)].append(docs[idx])

    with get_connection() as conn:
        with conn.cursor() as cursor:
            for cluster_id in cluster_codes:
                cluster_docs = cluster_to_docs.get(cluster_id, [])
                conf_count = len([d for d in cluster_docs if d.is_confidential])
                non_conf_count = len(cluster_docs) - conf_count
                cursor.execute(
                    insert_cluster_sql,
                    {
                        "run_id": model_run_pk,
                        "cluster_code": f"cluster_{cluster_id}",
                        "centroid_json": json.dumps(
                            [float(x) for x in cluster_centroids[cluster_id]],
                            ensure_ascii=False,
                        ),
                        "cluster_size": len(cluster_docs),
                        "conf_doc_count": conf_count,
                        "non_conf_doc_count": non_conf_count,
                        "similarity_threshold": cluster_similarity_threshold,
                    },
                )

            cursor.execute(query_cluster_sql, {"run_id": model_run_pk})
            cluster_rows = cursor.fetchall() or []
            cluster_code_to_pk: Dict[str, int] = {
                row["cluster_code"]: int(row["id"]) for row in cluster_rows
            }
            cluster_idx_to_pk: Dict[int, int] = {
                int(code.split("_")[-1]): pk for code, pk in cluster_code_to_pk.items()
            }

            for idx, doc in enumerate(docs):
                cluster_pk = cluster_idx_to_pk.get(int(cluster_labels[idx]))
                cursor.execute(
                    insert_doc_sql,
                    {
                        "run_id": model_run_pk,
                        "doc_uid": doc.doc_uid,
                        "doc_name": doc.doc_name,
                        "doc_path": doc.doc_path,
                        "raw_text": doc.raw_text,
                        "preprocessed_text": doc.preprocessed_text,
                        "source_type": doc.source_type,
                        "is_confidential": int(doc.is_confidential),
                        "label": doc.label,
                        "assigned_cluster_id": cluster_pk,
                        "metadata_json": json.dumps(
                            {"token_count": len(doc.tokens), "term_count": len(doc.terms)},
                            ensure_ascii=False,
                        ),
                    },
                )

            for row in confidential_term_rows:
                cursor.execute(
                    insert_conf_term_sql,
                    {
                        "run_id": model_run_pk,
                        "cluster_id": cluster_idx_to_pk[row["cluster_id"]],
                        "term_value": row["term_value"],
                        "term_score": row["term_score"],
                        "conf_probability": row["conf_probability"],
                        "non_conf_probability": row["non_conf_probability"],
                        "support_conf_docs": row["support_conf_docs"],
                        "support_non_conf_docs": row["support_non_conf_docs"],
                    },
                )

            cursor.execute(query_conf_term_sql, {"run_id": model_run_pk})
            conf_term_rows = cursor.fetchall() or []
            conf_term_key_to_pk: Dict[Tuple[int, str], int] = {}
            for row in conf_term_rows:
                conf_term_key_to_pk[(int(row["cluster_id"]), row["term_value"])] = int(row["id"])

            for row in context_term_rows:
                cluster_pk = cluster_idx_to_pk[row["cluster_id"]]
                conf_term_pk = conf_term_key_to_pk[(cluster_pk, row["conf_term"])]
                cursor.execute(
                    insert_context_sql,
                    {
                        "run_id": model_run_pk,
                        "cluster_id": cluster_pk,
                        "conf_term_id": conf_term_pk,
                        "context_term": row["context_term"],
                        "context_score": row["context_score"],
                        "conf_probability": row["conf_probability"],
                        "non_conf_probability": row["non_conf_probability"],
                        "support_conf_docs": row["support_conf_docs"],
                        "support_non_conf_docs": row["support_non_conf_docs"],
                    },
                )

            cursor.execute(query_context_sql, {"run_id": model_run_pk})
            context_rows = cursor.fetchall() or []
            context_key_to_pk: Dict[Tuple[int, int, str], int] = {}
            for row in context_rows:
                context_key_to_pk[
                    (int(row["cluster_id"]), int(row["conf_term_id"]), row["context_term"])
                ] = int(row["id"])

            for row in graph_edge_rows:
                cluster_pk = cluster_idx_to_pk[row["cluster_id"]]
                conf_term_pk = conf_term_key_to_pk[(cluster_pk, row["conf_term"])]
                context_pk = context_key_to_pk[(cluster_pk, conf_term_pk, row["context_term"])]
                cursor.execute(
                    insert_edge_sql,
                    {
                        "run_id": model_run_pk,
                        "cluster_id": cluster_pk,
                        "conf_term_id": conf_term_pk,
                        "context_term_id": context_pk,
                        "edge_weight": row["edge_weight"],
                        "metadata_json": json.dumps(
                            {
                                "conf_score": row["conf_score"],
                                "context_score": row["context_score"],
                            },
                            ensure_ascii=False,
                        ),
                    },
                )


def _update_run_success(
    run_id: str,
    metrics: Dict[str, float],
    model_artifact_path: str,
) -> None:
    """更新训练成功状态。"""
    sql = """
    UPDATE coban_model_run
    SET status = 'succeeded',
        metrics_json = %(metrics_json)s,
        model_artifact_path = %(model_artifact_path)s,
        end_time = %(end_time)s
    WHERE run_id = %(run_id)s
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                {
                    "run_id": run_id,
                    "metrics_json": json.dumps(metrics, ensure_ascii=False),
                    "model_artifact_path": model_artifact_path,
                    "end_time": datetime.now(),
                },
            )


def _update_run_failed(run_id: str, message: str) -> None:
    """更新训练失败状态。"""
    sql = """
    UPDATE coban_model_run
    SET status = 'failed',
        metrics_json = %(metrics_json)s,
        end_time = %(end_time)s
    WHERE run_id = %(run_id)s
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                {
                    "run_id": run_id,
                    "metrics_json": json.dumps({"error": message}, ensure_ascii=False),
                    "end_time": datetime.now(),
                },
            )


def _resolve_artifact_dir(request: CobanTrainingRequest, run_id: str) -> Path:
    """解析模型产物目录。"""
    base_dir = (
        Path(request.artifact_dir).expanduser().resolve()
        if request.artifact_dir
        else (settings.paths.output_dir / "coban_models").resolve()
    )
    target_dir = (base_dir / run_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _detect_source_type(docs: Sequence[CobanCorpusDocument]) -> str:
    """推断训练数据来源类型。"""
    source_set = {doc.source_type for doc in docs}
    if source_set == {"mock"}:
        return "mock"
    if source_set == {"real"}:
        return "real"
    return "mixed"


def train_coban_model(request: CobanTrainingRequest) -> CobanTrainingResult:
    """执行 CoBAn 训练编排。

    Args:
        request: 训练请求参数。

    Returns:
        CobanTrainingResult: 训练结果摘要。

    Raises:
        ValueError: 训练语料为空时抛出。
        RuntimeError: 训练或持久化过程中失败时抛出。
    """
    stopwords = load_stopwords(request.stopwords_path)
    docs: List[CobanCorpusDocument] = []

    docs.extend(
        _load_real_corpus(
            source_dirs=request.real_confidential_dirs,
            source_type="real",
            is_confidential=True,
            label="real_confidential",
            stopwords=stopwords,
            ngram_range=request.ngram_range,
        )
    )
    docs.extend(
        _load_real_corpus(
            source_dirs=request.real_non_confidential_dirs,
            source_type="real",
            is_confidential=False,
            label="real_non_confidential",
            stopwords=stopwords,
            ngram_range=request.ngram_range,
        )
    )
    if request.use_mock:
        docs.extend(_build_mock_corpus(stopwords=stopwords, ngram_range=request.ngram_range))

    if not docs:
        raise ValueError("训练失败：未加载到任何语料文档。")

    run_id = f"coban_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    conf_doc_count = len([doc for doc in docs if doc.is_confidential])
    non_conf_doc_count = len(docs) - conf_doc_count
    source_type = _detect_source_type(docs)
    model_run_pk = _create_model_run_record(
        run_id=run_id,
        request=request,
        source_type=source_type,
        train_doc_count=len(docs),
        conf_doc_count=conf_doc_count,
        non_conf_doc_count=non_conf_doc_count,
    )

    try:
        train_result = train_kmeans_clusters(
            documents=[doc.preprocessed_text for doc in docs],
            n_clusters=request.n_clusters,
            random_state=request.random_state,
            max_iter=request.max_iter,
        )
        conf_scores = score_confidential_terms(
            documents=docs,
            cluster_labels=train_result.labels,
            top_k_per_cluster=request.top_k_conf_terms,
        )
        context_scores = score_context_terms(
            documents=docs,
            cluster_labels=train_result.labels,
            confidential_term_scores=conf_scores,
            context_span=request.context_span,
            top_k_per_term=request.top_k_context_terms,
        )
        graph_result = build_conf_context_graph(
            confidential_term_scores=conf_scores,
            context_term_scores=context_scores,
            min_edge_weight=request.min_edge_weight,
        )

        artifact_dir = _resolve_artifact_dir(request=request, run_id=run_id)
        model_path = artifact_dir / "model.pkl"
        metadata_path = artifact_dir / "metadata.json"

        cluster_doc_indices: Dict[int, List[int]] = {}
        for idx, cluster_idx in enumerate(train_result.labels):
            cluster_doc_indices.setdefault(int(cluster_idx), []).append(idx)

        confidential_term_rows: List[dict] = []
        for item in conf_scores:
            cluster_docs = cluster_doc_indices.get(item.cluster_id, [])
            conf_support = 0
            non_conf_support = 0
            for doc_idx in cluster_docs:
                doc_terms = set(docs[doc_idx].terms)
                if item.term in doc_terms:
                    if docs[doc_idx].is_confidential:
                        conf_support += 1
                    else:
                        non_conf_support += 1
            confidential_term_rows.append(
                {
                    "cluster_id": item.cluster_id,
                    "term_value": item.term,
                    "term_score": float(item.score),
                    "conf_probability": float(item.confidential_freq + 1),
                    "non_conf_probability": float(item.background_freq + 1),
                    "support_conf_docs": conf_support,
                    "support_non_conf_docs": non_conf_support,
                }
            )

        context_term_rows: List[dict] = []
        for item in context_scores:
            context_term_rows.append(
                {
                    "cluster_id": item.cluster_id,
                    "conf_term": item.conf_term,
                    "context_term": item.context_term,
                    "context_score": float(item.score),
                    "conf_probability": float(item.pair_freq + 1),
                    "non_conf_probability": float(item.context_background_freq + 1),
                    "support_conf_docs": int(item.pair_freq),
                    "support_non_conf_docs": int(item.context_background_freq),
                }
            )

        graph_edge_rows = [
            {
                "cluster_id": edge.cluster_id,
                "conf_term": edge.conf_term,
                "context_term": edge.context_term,
                "edge_weight": float(edge.weight),
                "conf_score": float(edge.conf_score),
                "context_score": float(edge.context_score),
            }
            for edge in graph_result.edges
        ]

        model_payload = {
            "run_id": run_id,
            "params": {
                "ngram_range": list(request.ngram_range),
                "context_span": request.context_span,
                "cluster_similarity_threshold": request.cluster_similarity_threshold,
                "detection_threshold": request.detection_threshold,
            },
            "vectorizer": train_result.vectorizer,
            "centroid_vectors": train_result.centroid_vectors,
            "cluster_similarity_matrix": train_result.cluster_similarity_matrix,
            "confidential_terms": confidential_term_rows,
            "context_terms": context_term_rows,
            "graph_edges": graph_edge_rows,
        }
        with model_path.open("wb") as f:
            pickle.dump(model_payload, f)

        metadata = {
            "run_id": run_id,
            "cluster_count": len(train_result.cluster_to_doc_indices),
            "train_doc_count": len(docs),
            "conf_doc_count": conf_doc_count,
            "non_conf_doc_count": non_conf_doc_count,
            "model_path": str(model_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _persist_training_outputs(
            model_run_pk=model_run_pk,
            run_id=run_id,
            docs=docs,
            cluster_labels=train_result.labels,
            cluster_centroids=train_result.centroid_vectors,
            cluster_similarity_threshold=request.cluster_similarity_threshold,
            confidential_term_rows=confidential_term_rows,
            context_term_rows=context_term_rows,
            graph_edge_rows=graph_edge_rows,
        )

        metrics = {
            "cluster_count": float(len(train_result.cluster_to_doc_indices)),
            "confidential_term_count": float(len(confidential_term_rows)),
            "context_term_count": float(len(context_term_rows)),
            "graph_edge_count": float(len(graph_edge_rows)),
            "avg_cluster_similarity": float(train_result.cluster_similarity_matrix.mean()),
        }
        _update_run_success(
            run_id=run_id,
            metrics=metrics,
            model_artifact_path=str(model_path),
        )

        return CobanTrainingResult(
            run_id=run_id,
            model_run_pk=model_run_pk,
            train_doc_count=len(docs),
            conf_doc_count=conf_doc_count,
            non_conf_doc_count=non_conf_doc_count,
            cluster_count=len(train_result.cluster_to_doc_indices),
            confidential_term_count=len(confidential_term_rows),
            context_term_count=len(context_term_rows),
            graph_edge_count=len(graph_edge_rows),
            model_artifact_path=str(model_path),
            metrics=metrics,
        )
    except Exception as exc:  # noqa: BLE001
        _update_run_failed(run_id=run_id, message=str(exc))
        raise RuntimeError(f"CoBAn 训练失败: {exc}") from exc


def preview_cluster_assignment(run_id: str, text: str, top_k: int = 3) -> List[Tuple[int, float]]:
    """基于训练产物预览文档簇分配效果。"""
    sql = """
    SELECT model_artifact_path, params_json
    FROM coban_model_run
    WHERE run_id = %(run_id)s AND status = 'succeeded' AND is_deleted = 0
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"run_id": run_id})
            row = cursor.fetchone()
    if row is None:
        raise ValueError(f"训练批次不存在或尚未成功: {run_id}")

    model_path = Path(row["model_artifact_path"]).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"模型产物不存在: {model_path}")
    with model_path.open("rb") as f:
        payload = pickle.load(f)

    params_json = row.get("params_json") or {}
    if isinstance(params_json, str):
        params_json = json.loads(params_json)
    ngram_range = tuple(params_json.get("ngram_range", [1, 3]))
    stopwords = load_stopwords(params_json.get("stopwords_path"))
    from src.processors.coban_text_preprocessor import preprocess_text

    _, _, normalized = preprocess_text(text=text, stopwords=stopwords, ngram_range=ngram_range)
    return assign_document_to_clusters(
        text=normalized,
        vectorizer=payload["vectorizer"],
        centroid_vectors=payload["centroid_vectors"],
        top_k=top_k,
        similarity_threshold=float(payload["params"]["cluster_similarity_threshold"]),
    )

