# 文本数字指纹生成工具（Python 模块）

本项目用于离线生成文本类文档的数字指纹，作为 Java DLP 系统的指纹库数据源。

## 功能概述

- 从本地读取 txt 文档
- 对文本进行分段/分句
- 使用 MD5 计算：
  - 文档整体指纹
  - 每个分段/分句的指纹
- 将结果写入 MySQL 表 `digital_fingerprint_doc`

## 依赖安装

在项目根目录执行：

```bash
pip install -r requirements.txt
```

## 数据库初始化

1. 确保 MySQL 中存在数据库（默认：`graduation_work`，可在 `config/config.yaml` 中修改）。
2. 在项目根目录执行：

```bash
python main.py init-db
```

执行成功后，将创建以下表：

- `documents`
- `segments`
- `digital_fingerprint_doc`

其中 `digital_fingerprint_doc` 为 Java DLP 系统使用的**数字指纹文档库主表**。

## 导入 txt 文档指纹

```bash
python main.py ingest-file path/to/file.txt \
  --doc-source local_import \
  --sensitive-level 1
```

可选参数：

- `--doc-unique-id`：手动指定文档唯一 ID（不传则自动生成 UUID）。
- `--doc-source`：文档来源（默认 `local_import`）。
- `--sensitive-level`：敏感等级 `0-3`。
- `--max-sentence-length`：分句时的最大长度（默认 `500`）。

## 查看当前配置

```bash
python main.py show-config
```

会输出：

- 应用名称与环境
- 输入/输出/日志目录
- 数据库连接信息（隐藏密码）

## 扩展方向

- 支持更多指纹算法：SHA256、SimHash、向量指纹（基于 `sentence-transformers`）。
- 引入聚类与相似度分析（`scikit-learn`、`gensim` 等）。
- 提供批量导入目录、状态监控等高级功能。

