"""
CoBAn 训练入口脚本。

职责：
- 从命令行读取训练参数；
- 调用训练编排服务执行 CoBAn 训练；
- 打印结构化结果，便于本地快速验证。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import List, Optional, Tuple

from src.services.coban_training_service import CobanTrainingRequest, train_coban_model


def _parse_ngram_range(value: str) -> Tuple[int, int]:
    """解析 ngram 参数字符串。"""
    pieces = value.split(",")
    if len(pieces) != 2:
        raise argparse.ArgumentTypeError("ngram_range 格式必须是 min,max，例如 1,3")
    try:
        min_n = int(pieces[0].strip())
        max_n = int(pieces[1].strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ngram_range 需要两个整数") from exc
    if min_n < 1 or max_n < min_n:
        raise argparse.ArgumentTypeError("ngram_range 必须满足 1 <= min <= max")
    return min_n, max_n


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="CoBAn 训练入口脚本")
    parser.add_argument("--run-name", type=str, default=None, help="训练任务名称")
    parser.add_argument("--dataset-name", type=str, default=None, help="数据集名称")
    parser.add_argument(
        "--real-conf-dir",
        action="append",
        default=[],
        help="真实机密语料目录，可重复传入",
    )
    parser.add_argument(
        "--real-non-conf-dir",
        action="append",
        default=[],
        help="真实非机密语料目录，可重复传入",
    )
    parser.add_argument(
        "--disable-mock",
        action="store_true",
        help="禁用内置 mock 语料",
    )
    parser.add_argument(
        "--stopwords-path",
        type=str,
        default=None,
        help="停用词文件路径",
    )
    parser.add_argument(
        "--ngram-range",
        type=_parse_ngram_range,
        default=(1, 3),
        help="ngram 范围，格式 min,max，默认 1,3",
    )
    parser.add_argument("--n-clusters", type=int, default=3, help="聚类数")
    parser.add_argument("--random-state", type=int, default=42, help="随机种子")
    parser.add_argument("--max-iter", type=int, default=300, help="聚类最大迭代次数")
    parser.add_argument("--context-span", type=int, default=20, help="上下文窗口半径")
    parser.add_argument("--top-k-conf-terms", type=int, default=120, help="每簇机密术语上限")
    parser.add_argument("--top-k-context-terms", type=int, default=30, help="每术语上下文上限")
    parser.add_argument("--min-edge-weight", type=float, default=0.0, help="图边最小权重")
    parser.add_argument(
        "--cluster-similarity-threshold",
        type=float,
        default=0.05,
        help="检测阶段簇匹配相似度阈值",
    )
    parser.add_argument(
        "--detection-threshold",
        type=float,
        default=0.8,
        help="检测判定阈值",
    )
    parser.add_argument("--artifact-dir", type=str, default=None, help="模型产物输出目录")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """脚本主函数。"""
    parser = _build_parser()
    args = parser.parse_args(argv)

    request = CobanTrainingRequest(
        run_name=args.run_name,
        dataset_name=args.dataset_name,
        source_type="mixed",
        real_confidential_dirs=args.real_conf_dir,
        real_non_confidential_dirs=args.real_non_conf_dir,
        use_mock=not args.disable_mock,
        stopwords_path=args.stopwords_path,
        ngram_range=args.ngram_range,
        n_clusters=max(1, int(args.n_clusters)),
        random_state=args.random_state,
        max_iter=max(50, int(args.max_iter)),
        context_span=max(1, int(args.context_span)),
        top_k_conf_terms=max(10, int(args.top_k_conf_terms)),
        top_k_context_terms=max(5, int(args.top_k_context_terms)),
        min_edge_weight=max(0.0, float(args.min_edge_weight)),
        cluster_similarity_threshold=max(0.0, float(args.cluster_similarity_threshold)),
        detection_threshold=max(0.0, float(args.detection_threshold)),
        artifact_dir=args.artifact_dir,
    )

    result = train_coban_model(request=request)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

