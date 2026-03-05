# 后端可视化能力使用说明（JSON + Seaborn）

## 1. 依赖与安装

本项目的可视化静态图依赖已经在 `requirements.txt` 中声明：

- `matplotlib>=3.8.0`
- `seaborn>=0.13.0`

建议安装方式：

```bash
pip install -r requirements.txt
```

## 2. 能力说明

当前后端提供两类可视化能力：

- 交互数据接口（JSON）：供前端直接渲染图表。
- 静态图导出接口（Seaborn）：后端生成 PNG/SVG，适合汇报与文档。

静态图输出目录：

- `data/output/visualization/`

## 3. 隐性风险（enterprise-data）

### 3.1 JSON 可视化数据

- `GET /api/v1/enterprise-data/datasets/{dataset_code}/visualization/implicit-risk/latest`

常用查询参数：

- `theta`：风险阈值（默认 `0.2`）
- `top_n`：图表返回条数（默认 `20`）

### 3.2 静态图导出

- `GET /api/v1/enterprise-data/datasets/{dataset_code}/visualization-images/implicit-risk`

常用查询参数：

- `chart_type`：`risk_bar` / `lr_pic_scatter`
- `theta`：阈值
- `top_n`：展示数量
- `dpi`：图像清晰度，默认 `200`
- `image_format`：`png` / `svg`

## 4. CoBAn（coban）

### 4.1 JSON 可视化数据

- `GET /api/v1/coban/visualization/run/{run_id}/overview`
- `GET /api/v1/coban/visualization/run/{run_id}/detections`
- `GET /api/v1/coban/visualization/detection/{doc_uid}/evidence-graph`

### 4.2 静态图导出

- `GET /api/v1/coban/visualization-images/run/{run_id}/overview`
  - `chart_type`：`cluster_distribution` / `score_histogram` / `detection_trend`
- `GET /api/v1/coban/visualization-images/run/{run_id}/detections`
  - `chart_type`：`score_boxplot` / `status_bar` / `trend_line`

通用参数：

- `dpi`：默认 `200`
- `image_format`：`png` / `svg`
- `limit` / `offset` / `is_confidential`（detections 接口可选）

## 5. 返回字段（静态图接口）

静态图接口统一返回：

- `image_path`：服务器本地文件路径
- `generated_at`：生成时间
- `chart_type`：图类型
- `image_format`：图片格式
- `chart_meta`：图像参数与数据范围信息

