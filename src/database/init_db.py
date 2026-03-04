"""
数据库表结构脚本定义（手工执行版）。

说明：
- 本文件只维护建表 SQL 常量，不自动连接数据库执行。
- 由使用者手工在 MySQL 中执行，避免项目启动时自动初始化库表。
- 除现有数字指纹表外，新增企业数据集与关系知识图谱底座表。
"""

from __future__ import annotations

from typing import List


CREATE_TABLE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    file_path VARCHAR(512) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT UNSIGNED NOT NULL DEFAULT 0,
    encoding VARCHAR(64) DEFAULT NULL,
    full_md5 CHAR(32) DEFAULT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    extra JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_documents_path (file_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_TABLE_SEGMENTS = """
CREATE TABLE IF NOT EXISTS segments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT UNSIGNED NOT NULL,
    idx INT NOT NULL,
    start_offset INT NULL,
    end_offset INT NULL,
    text LONGTEXT NOT NULL,
    md5 CHAR(32) DEFAULT NULL,
    extra JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_segments_document
        FOREIGN KEY (document_id) REFERENCES documents(id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_segments_doc_idx (document_id, idx)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_TABLE_DIGITAL_FINGERPRINT_DOC = """
CREATE TABLE `digital_fingerprint_doc` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `doc_unique_id` varchar(64) NOT NULL COMMENT '文档唯一标识（如UUID）',
  `doc_name` varchar(255) NOT NULL COMMENT '文档名称',
  `doc_type` varchar(32) NOT NULL COMMENT '文档类型（pdf/word/txt等）',
  `doc_size` bigint DEFAULT NULL COMMENT '文档大小（字节）',
  `fingerprint_type` varchar(32) NOT NULL COMMENT '指纹类型（md5/sha256/simhash等）',
  `fingerprint_value` varchar(256) NOT NULL COMMENT '数字指纹值',
  `doc_shard_id` int DEFAULT NULL COMMENT '文档分片ID（用于大文档拆分）',
  `shard_fingerprint` varchar(256) DEFAULT NULL COMMENT '分片指纹值（大文档时非空）',
  `doc_source` varchar(128) DEFAULT NULL COMMENT '文档来源（如上传/系统导入）',
  `sensitive_level` tinyint DEFAULT '0' COMMENT '敏感等级（0-无，1-低，2-中，3-高）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) DEFAULT '0' COMMENT '逻辑删除标识（0-未删，1-已删）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_doc_unique_id_shard` (`doc_unique_id`,`doc_shard_id`),
  KEY `idx_fingerprint_value` (`fingerprint_value`),
  KEY `idx_doc_type` (`doc_type`),
  KEY `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数字指纹文档库主表（与DLP检测表隔离）';
"""


CREATE_TABLE_ENTERPRISE_DATASET = """
CREATE TABLE IF NOT EXISTS `enterprise_dataset` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `dataset_code` varchar(64) NOT NULL COMMENT '数据集编码（企业内唯一）',
  `dataset_name` varchar(255) NOT NULL COMMENT '数据集名称',
  `domain_name` varchar(128) DEFAULT NULL COMMENT '业务域（人资/财务/营销等）',
  `source_system` varchar(128) DEFAULT NULL COMMENT '来源系统标识',
  `description` varchar(1024) DEFAULT NULL COMMENT '描述信息',
  `status` varchar(32) NOT NULL DEFAULT 'active' COMMENT '状态：active/inactive',
  `version_no` int NOT NULL DEFAULT 1 COMMENT '当前版本号',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '逻辑删除标识',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dataset_code` (`dataset_code`),
  KEY `idx_domain_name` (`domain_name`),
  KEY `idx_source_system` (`source_system`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业数据集主表';
"""


CREATE_TABLE_ENTERPRISE_ATTRIBUTE = """
CREATE TABLE IF NOT EXISTS `enterprise_attribute` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `dataset_id` bigint NOT NULL COMMENT '所属数据集ID',
  `attr_code` varchar(64) NOT NULL COMMENT '属性编码（同数据集内唯一）',
  `attr_name` varchar(255) NOT NULL COMMENT '属性名称',
  `attr_type` varchar(32) NOT NULL COMMENT '属性类型：string/number/date/category等',
  `is_sensitive` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否敏感属性',
  `sensitivity_level` tinyint NOT NULL DEFAULT 0 COMMENT '敏感等级（0-3）',
  `is_identifier` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否为标识性属性（准标识符）',
  `nullable_flag` tinyint(1) NOT NULL DEFAULT 1 COMMENT '是否可空',
  `default_pic` decimal(8,6) DEFAULT NULL COMMENT '默认PIC值（可选）',
  `description` varchar(1024) DEFAULT NULL COMMENT '描述信息',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '逻辑删除标识',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dataset_attr_code` (`dataset_id`, `attr_code`),
  KEY `idx_dataset_sensitive` (`dataset_id`, `is_sensitive`),
  CONSTRAINT `fk_attr_dataset` FOREIGN KEY (`dataset_id`) REFERENCES `enterprise_dataset` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业数据集属性定义表';
"""


CREATE_TABLE_ENTERPRISE_SAMPLE = """
CREATE TABLE IF NOT EXISTS `enterprise_sample` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `dataset_id` bigint NOT NULL COMMENT '所属数据集ID',
  `sample_key` varchar(128) NOT NULL COMMENT '样本业务键（如订单号/员工号）',
  `sample_hash` varchar(64) DEFAULT NULL COMMENT '样本哈希摘要（可用于去重）',
  `source_trace` varchar(255) DEFAULT NULL COMMENT '来源追踪标识（批次/文件）',
  `event_time` datetime DEFAULT NULL COMMENT '样本业务时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '逻辑删除标识',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dataset_sample_key` (`dataset_id`, `sample_key`),
  KEY `idx_dataset_event_time` (`dataset_id`, `event_time`),
  CONSTRAINT `fk_sample_dataset` FOREIGN KEY (`dataset_id`) REFERENCES `enterprise_dataset` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业数据集样本主表';
"""


CREATE_TABLE_ENTERPRISE_SAMPLE_VALUE = """
CREATE TABLE IF NOT EXISTS `enterprise_sample_value` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `sample_id` bigint NOT NULL COMMENT '样本ID',
  `attribute_id` bigint NOT NULL COMMENT '属性ID',
  `raw_value` longtext COMMENT '原始值',
  `normalized_value` varchar(1024) DEFAULT NULL COMMENT '标准化值（用于统计与关系计算）',
  `masked_value` varchar(1024) DEFAULT NULL COMMENT '脱敏后展示值（可选）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '逻辑删除标识',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_sample_attribute` (`sample_id`, `attribute_id`),
  KEY `idx_attribute_normalized` (`attribute_id`, `normalized_value`),
  CONSTRAINT `fk_sample_value_sample` FOREIGN KEY (`sample_id`) REFERENCES `enterprise_sample` (`id`),
  CONSTRAINT `fk_sample_value_attribute` FOREIGN KEY (`attribute_id`) REFERENCES `enterprise_attribute` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业样本属性值表（EAV模型）';
"""


CREATE_TABLE_KG_NODE = """
CREATE TABLE IF NOT EXISTS `enterprise_kg_node` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `dataset_id` bigint NOT NULL COMMENT '所属数据集ID',
  `node_type` varchar(32) NOT NULL COMMENT '节点类型：attribute/value/group等',
  `node_key` varchar(128) NOT NULL COMMENT '节点业务键',
  `display_name` varchar(255) DEFAULT NULL COMMENT '展示名称',
  `metadata_json` json DEFAULT NULL COMMENT '节点扩展信息',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '逻辑删除标识',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dataset_node_key` (`dataset_id`, `node_type`, `node_key`),
  KEY `idx_dataset_node_type` (`dataset_id`, `node_type`),
  CONSTRAINT `fk_kg_node_dataset` FOREIGN KEY (`dataset_id`) REFERENCES `enterprise_dataset` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业知识图谱节点表';
"""


CREATE_TABLE_KG_EDGE_EXPLICIT = """
CREATE TABLE IF NOT EXISTS `enterprise_kg_edge_explicit` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `dataset_id` bigint NOT NULL COMMENT '所属数据集ID',
  `from_node_id` bigint NOT NULL COMMENT '起始节点ID',
  `to_node_id` bigint NOT NULL COMMENT '目标节点ID',
  `relation_type` varchar(64) NOT NULL COMMENT '关系类型：fk/map/business_rule等',
  `relation_desc` varchar(1024) DEFAULT NULL COMMENT '关系描述',
  `source_type` varchar(32) NOT NULL DEFAULT 'manual' COMMENT '来源：manual/schema/rule',
  `evidence_json` json DEFAULT NULL COMMENT '关系证据',
  `confidence` decimal(8,6) DEFAULT 1.000000 COMMENT '置信度',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_explicit_edge_unique` (`dataset_id`, `from_node_id`, `to_node_id`, `relation_type`),
  KEY `idx_dataset_relation_type` (`dataset_id`, `relation_type`),
  CONSTRAINT `fk_explicit_dataset` FOREIGN KEY (`dataset_id`) REFERENCES `enterprise_dataset` (`id`),
  CONSTRAINT `fk_explicit_from_node` FOREIGN KEY (`from_node_id`) REFERENCES `enterprise_kg_node` (`id`),
  CONSTRAINT `fk_explicit_to_node` FOREIGN KEY (`to_node_id`) REFERENCES `enterprise_kg_node` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业知识图谱显性关系边表';
"""


CREATE_TABLE_KG_EDGE_IMPLICIT = """
CREATE TABLE IF NOT EXISTS `enterprise_kg_edge_implicit` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `dataset_id` bigint NOT NULL COMMENT '所属数据集ID',
  `from_node_id` bigint NOT NULL COMMENT '起始节点ID',
  `to_node_id` bigint NOT NULL COMMENT '目标节点ID',
  `sensitive_attr_id` bigint DEFAULT NULL COMMENT '关联敏感属性ID（可选）',
  `metric_type` varchar(32) NOT NULL COMMENT '指标类型：mi/lr/risk等',
  `metric_value` decimal(16,8) NOT NULL COMMENT '指标值',
  `pic_value` decimal(8,6) DEFAULT NULL COMMENT 'PIC值',
  `risk_value` decimal(16,8) DEFAULT NULL COMMENT '风险值',
  `calc_batch_id` varchar(64) DEFAULT NULL COMMENT '计算批次ID',
  `source_type` varchar(32) NOT NULL DEFAULT 'calc' COMMENT '来源：calc/manual',
  `evidence_json` json DEFAULT NULL COMMENT '计算证据与参数',
  `confidence` decimal(8,6) DEFAULT 0.500000 COMMENT '置信度',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_implicit_dataset_metric` (`dataset_id`, `metric_type`),
  KEY `idx_implicit_batch` (`calc_batch_id`),
  KEY `idx_implicit_sensitive_attr` (`sensitive_attr_id`),
  CONSTRAINT `fk_implicit_dataset` FOREIGN KEY (`dataset_id`) REFERENCES `enterprise_dataset` (`id`),
  CONSTRAINT `fk_implicit_from_node` FOREIGN KEY (`from_node_id`) REFERENCES `enterprise_kg_node` (`id`),
  CONSTRAINT `fk_implicit_to_node` FOREIGN KEY (`to_node_id`) REFERENCES `enterprise_kg_node` (`id`),
  CONSTRAINT `fk_implicit_sensitive_attr` FOREIGN KEY (`sensitive_attr_id`) REFERENCES `enterprise_attribute` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业知识图谱隐性关系边表（MI/LR/Risk）';
"""


CREATE_TABLE_COBAN_MODEL_RUN = """
CREATE TABLE IF NOT EXISTS `coban_model_run` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` varchar(64) NOT NULL COMMENT '训练批次唯一ID',
  `run_name` varchar(255) DEFAULT NULL COMMENT '训练任务名称',
  `dataset_name` varchar(255) DEFAULT NULL COMMENT '数据集名称',
  `source_type` varchar(32) NOT NULL DEFAULT 'mixed' COMMENT '数据来源类型：real/mock/mixed',
  `train_doc_count` int NOT NULL DEFAULT 0 COMMENT '训练文档总数',
  `conf_doc_count` int NOT NULL DEFAULT 0 COMMENT '机密文档数',
  `non_conf_doc_count` int NOT NULL DEFAULT 0 COMMENT '非机密文档数',
  `params_json` json DEFAULT NULL COMMENT '训练参数快照',
  `metrics_json` json DEFAULT NULL COMMENT '评估指标快照',
  `model_artifact_path` varchar(1024) DEFAULT NULL COMMENT '模型产物路径',
  `status` varchar(32) NOT NULL DEFAULT 'created' COMMENT '状态：created/running/succeeded/failed',
  `start_time` datetime DEFAULT NULL COMMENT '训练开始时间',
  `end_time` datetime DEFAULT NULL COMMENT '训练结束时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0 COMMENT '逻辑删除标识',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coban_run_id` (`run_id`),
  KEY `idx_coban_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn训练批次主表';
"""


CREATE_TABLE_COBAN_CLUSTER = """
CREATE TABLE IF NOT EXISTS `coban_cluster` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` bigint NOT NULL COMMENT '所属训练批次ID',
  `cluster_code` varchar(64) NOT NULL COMMENT '聚类编号',
  `centroid_json` json DEFAULT NULL COMMENT '聚类中心向量',
  `cluster_size` int NOT NULL DEFAULT 0 COMMENT '聚类文档数量',
  `conf_doc_count` int NOT NULL DEFAULT 0 COMMENT '聚类内机密文档数',
  `non_conf_doc_count` int NOT NULL DEFAULT 0 COMMENT '聚类内非机密文档数',
  `similarity_threshold` decimal(8,6) DEFAULT NULL COMMENT '簇级判定阈值',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coban_run_cluster` (`run_id`, `cluster_code`),
  KEY `idx_coban_cluster_run` (`run_id`),
  CONSTRAINT `fk_coban_cluster_run` FOREIGN KEY (`run_id`) REFERENCES `coban_model_run` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn聚类信息表';
"""


CREATE_TABLE_COBAN_CORPUS_DOCUMENT = """
CREATE TABLE IF NOT EXISTS `coban_corpus_document` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` bigint NOT NULL COMMENT '所属训练批次ID',
  `doc_uid` varchar(64) NOT NULL COMMENT '文档唯一标识',
  `doc_name` varchar(255) DEFAULT NULL COMMENT '文档名称',
  `doc_path` varchar(1024) DEFAULT NULL COMMENT '文档路径',
  `raw_text` longtext COMMENT '原始文本',
  `preprocessed_text` longtext COMMENT '预处理文本',
  `source_type` varchar(32) NOT NULL DEFAULT 'real' COMMENT '来源：real/mock',
  `is_confidential` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否机密标签',
  `label` varchar(64) DEFAULT NULL COMMENT '业务标签（财务/技术/规划等）',
  `assigned_cluster_id` bigint DEFAULT NULL COMMENT '聚类分配ID',
  `metadata_json` json DEFAULT NULL COMMENT '扩展元数据',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coban_run_doc_uid` (`run_id`, `doc_uid`),
  KEY `idx_coban_doc_cluster` (`assigned_cluster_id`),
  KEY `idx_coban_doc_conf` (`run_id`, `is_confidential`),
  CONSTRAINT `fk_coban_doc_run` FOREIGN KEY (`run_id`) REFERENCES `coban_model_run` (`id`),
  CONSTRAINT `fk_coban_doc_cluster` FOREIGN KEY (`assigned_cluster_id`) REFERENCES `coban_cluster` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn训练/检测文档表';
"""


CREATE_TABLE_COBAN_TERM_CONFIDENTIAL = """
CREATE TABLE IF NOT EXISTS `coban_term_confidential` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` bigint NOT NULL COMMENT '所属训练批次ID',
  `cluster_id` bigint NOT NULL COMMENT '所属聚类ID',
  `term_value` varchar(255) NOT NULL COMMENT '机密术语',
  `term_score` decimal(16,8) NOT NULL COMMENT '术语得分',
  `conf_probability` decimal(16,8) DEFAULT NULL COMMENT '机密语料概率',
  `non_conf_probability` decimal(16,8) DEFAULT NULL COMMENT '非机密语料概率',
  `support_conf_docs` int NOT NULL DEFAULT 0 COMMENT '命中机密文档数',
  `support_non_conf_docs` int NOT NULL DEFAULT 0 COMMENT '命中非机密文档数',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coban_conf_term` (`cluster_id`, `term_value`),
  KEY `idx_coban_conf_term_run` (`run_id`, `cluster_id`),
  CONSTRAINT `fk_coban_conf_term_run` FOREIGN KEY (`run_id`) REFERENCES `coban_model_run` (`id`),
  CONSTRAINT `fk_coban_conf_term_cluster` FOREIGN KEY (`cluster_id`) REFERENCES `coban_cluster` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn机密术语表';
"""


CREATE_TABLE_COBAN_TERM_CONTEXT = """
CREATE TABLE IF NOT EXISTS `coban_term_context` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` bigint NOT NULL COMMENT '所属训练批次ID',
  `cluster_id` bigint NOT NULL COMMENT '所属聚类ID',
  `conf_term_id` bigint NOT NULL COMMENT '机密术语ID',
  `context_term` varchar(255) NOT NULL COMMENT '上下文术语',
  `context_score` decimal(16,8) NOT NULL COMMENT '上下文得分',
  `conf_probability` decimal(16,8) DEFAULT NULL COMMENT '机密上下文概率',
  `non_conf_probability` decimal(16,8) DEFAULT NULL COMMENT '非机密上下文概率',
  `support_conf_docs` int NOT NULL DEFAULT 0 COMMENT '命中机密文档数',
  `support_non_conf_docs` int NOT NULL DEFAULT 0 COMMENT '命中非机密文档数',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coban_context_term` (`conf_term_id`, `context_term`),
  KEY `idx_coban_context_run` (`run_id`, `cluster_id`),
  CONSTRAINT `fk_coban_context_run` FOREIGN KEY (`run_id`) REFERENCES `coban_model_run` (`id`),
  CONSTRAINT `fk_coban_context_cluster` FOREIGN KEY (`cluster_id`) REFERENCES `coban_cluster` (`id`),
  CONSTRAINT `fk_coban_context_conf_term` FOREIGN KEY (`conf_term_id`) REFERENCES `coban_term_confidential` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn上下文术语表';
"""


CREATE_TABLE_COBAN_GRAPH_EDGE = """
CREATE TABLE IF NOT EXISTS `coban_graph_edge` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` bigint NOT NULL COMMENT '所属训练批次ID',
  `cluster_id` bigint NOT NULL COMMENT '所属聚类ID',
  `conf_term_id` bigint NOT NULL COMMENT '机密术语ID',
  `context_term_id` bigint NOT NULL COMMENT '上下文术语ID',
  `edge_weight` decimal(16,8) NOT NULL COMMENT '边权重',
  `metadata_json` json DEFAULT NULL COMMENT '边扩展信息',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coban_graph_edge` (`cluster_id`, `conf_term_id`, `context_term_id`),
  KEY `idx_coban_graph_run` (`run_id`, `cluster_id`),
  CONSTRAINT `fk_coban_graph_run` FOREIGN KEY (`run_id`) REFERENCES `coban_model_run` (`id`),
  CONSTRAINT `fk_coban_graph_cluster` FOREIGN KEY (`cluster_id`) REFERENCES `coban_cluster` (`id`),
  CONSTRAINT `fk_coban_graph_conf_term` FOREIGN KEY (`conf_term_id`) REFERENCES `coban_term_confidential` (`id`),
  CONSTRAINT `fk_coban_graph_context_term` FOREIGN KEY (`context_term_id`) REFERENCES `coban_term_context` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn机密术语图边表';
"""


CREATE_TABLE_COBAN_DETECTION_RESULT = """
CREATE TABLE IF NOT EXISTS `coban_detection_result` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` bigint NOT NULL COMMENT '模型批次ID',
  `doc_uid` varchar(64) NOT NULL COMMENT '检测文档唯一标识',
  `doc_name` varchar(255) DEFAULT NULL COMMENT '文档名称',
  `doc_path` varchar(1024) DEFAULT NULL COMMENT '文档路径',
  `input_text` longtext COMMENT '检测输入文本',
  `matched_clusters_json` json DEFAULT NULL COMMENT '命中簇信息',
  `confidentiality_score` decimal(16,8) NOT NULL COMMENT '机密性总分',
  `threshold_value` decimal(16,8) NOT NULL COMMENT '判定阈值',
  `is_confidential` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否机密',
  `evidence_json` json DEFAULT NULL COMMENT '命中证据',
  `decision_reason` varchar(1024) DEFAULT NULL COMMENT '判定原因',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_coban_detect_run` (`run_id`),
  KEY `idx_coban_detect_conf` (`run_id`, `is_confidential`),
  CONSTRAINT `fk_coban_detect_run` FOREIGN KEY (`run_id`) REFERENCES `coban_model_run` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CoBAn检测结果表';
"""


ALL_CREATE_TABLE_SQL: List[str] = [
    CREATE_TABLE_DOCUMENTS,
    CREATE_TABLE_SEGMENTS,
    CREATE_TABLE_DIGITAL_FINGERPRINT_DOC,
    CREATE_TABLE_ENTERPRISE_DATASET,
    CREATE_TABLE_ENTERPRISE_ATTRIBUTE,
    CREATE_TABLE_ENTERPRISE_SAMPLE,
    CREATE_TABLE_ENTERPRISE_SAMPLE_VALUE,
    CREATE_TABLE_KG_NODE,
    CREATE_TABLE_KG_EDGE_EXPLICIT,
    CREATE_TABLE_KG_EDGE_IMPLICIT,
    CREATE_TABLE_COBAN_MODEL_RUN,
    CREATE_TABLE_COBAN_CLUSTER,
    CREATE_TABLE_COBAN_CORPUS_DOCUMENT,
    CREATE_TABLE_COBAN_TERM_CONFIDENTIAL,
    CREATE_TABLE_COBAN_TERM_CONTEXT,
    CREATE_TABLE_COBAN_GRAPH_EDGE,
    CREATE_TABLE_COBAN_DETECTION_RESULT,
]


def build_manual_init_sql() -> str:
    """生成手工初始化数据库所需 SQL 脚本。

    Returns:
        str: 按顺序拼接后的完整建表 SQL 文本。
    """
    return "\n\n".join(sql.strip() for sql in ALL_CREATE_TABLE_SQL) + "\n"

