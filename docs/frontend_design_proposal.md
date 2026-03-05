# DLP系统前端设计方案

## 一、项目概述

本系统是一个数据防泄漏（DLP）智能分析平台，包含三大核心功能模块：数字指纹管理、企业数据风险分析、CoBAn非结构化文本机密检测。

---

## 二、API接口汇总

### 2.1 数字指纹模块

| 端点 | 方法 | 功能描述 |
|------|------|----------|
| `/api/v1/fingerprints/from-file` | POST | 从本地txt文件生成数字指纹（文档级+分句级MD5） |

**请求参数**:
```json
{
  "file_path": "string",      // 本地文件绝对路径
  "dataset_code": "string"    // 所属数据集代码
}
```

**响应示例**:
```json
{
  "document_hash": "md5_string",
  "segment_hashes": ["hash1", "hash2", ...],
  "segment_count": 10
}
```

---

### 2.2 企业数据模块

| 端点 | 方法 | 功能描述 |
|------|------|----------|
| `/api/v1/enterprise-data/datasets` | POST | 创建/更新企业数据集 |
| `/api/v1/enterprise-data/datasets/{code}/attributes/batch` | POST | 批量注册属性元数据 |
| `/api/v1/enterprise-data/datasets/{code}/samples/batch` | POST | 批量导入样本值 |
| `/api/v1/enterprise-data/datasets/{code}/kg/edges/explicit/batch` | POST | 批量写入显性关系边 |
| `/api/v1/enterprise-data/datasets/{code}/analysis/implicit-risk` | POST | 触发隐性关系与泄露风险分析 |
| `/api/v1/enterprise-data/datasets/{code}/visualization/implicit-risk/latest` | GET | 获取最新隐性风险可视化数据（JSON） |
| `/api/v1/enterprise-data/datasets/{code}/visualization-images/implicit-risk` | GET | 导出隐性风险可视化图像（PNG/SVG） |

**查询参数说明**:
- `theta`: 风险阈值（默认0.2）
- `top_n`: 返回条数（默认20）
- `chart_type`: 图表类型（`risk_bar` / `lr_pic_scatter`）
- `dpi`: 图像清晰度（默认200）
- `image_format`: 图片格式（`png` / `svg`）

---

### 2.3 CoBAn模块

| 端点 | 方法 | 功能描述 |
|------|------|----------|
| `/api/v1/coban/train` | POST | 提交CoBAn训练任务 |
| `/api/v1/coban/detect` | POST | 提交CoBAn检测任务 |
| `/api/v1/coban/models/{run_id}` | GET | 查询训练批次详情 |
| `/api/v1/coban/detections/{doc_uid}` | GET | 查询检测记录详情 |
| `/api/v1/coban/visualization/run/{run_id}/overview` | GET | 获取批次可视化总览（JSON） |
| `/api/v1/coban/visualization/run/{run_id}/detections` | GET | 分页获取检测可视化数据（JSON） |
| `/api/v1/coban/visualization/detection/{doc_uid}/evidence-graph` | GET | 获取检测证据图数据（JSON） |
| `/api/v1/coban/visualization-images/run/{run_id}/overview` | GET | 导出批次总览图像 |
| `/api/v1/coban/visualization-images/run/{run_id}/detections` | GET | 导出检测统计图像 |

**CoBAn训练参数**:
```json
{
  "run_name": "string",
  "corpus_config": {
    "source_type": "folder",
    "folder_path": "string"
  },
  "params": {
    "ngram_range": [1, 3],
    "n_clusters": 3,
    "context_span": 20,
    "top_k_conf_terms": 120,
    "top_k_context_terms": 30
  }
}
```

**CoBAn检测参数**:
```json
{
  "run_id": "string",
  "documents": [
    {
      "doc_name": "string",
      "raw_text": "string"
    }
  ],
  "threshold": 0.8
}
```

---

## 三、前端设计方案

### 3.1 设计理念

**视觉风格**: 深色科技风 + 玻璃拟态（Glassmorphism）
- 深色背景降低眼部疲劳，契合安全类产品的专业感
- 玻璃拟态效果增强界面层次感和现代感
- 数据可视化使用霓虹色系突出关键信息

**色彩方案**:
```css
/* 主色调 */
--primary: #6366f1;        /* 靛蓝 - 主品牌色 */
--primary-dark: #4f46e5;   /* 深靛蓝 - 悬停状态 */
--accent-cyan: #06b6d4;    /* 青色 - 数据/图表 */
--accent-amber: #f59e0b;   /* 琥珀 - 警告/风险 */
--accent-rose: #f43f5e;    /* 玫瑰红 - 高危/机密 */

/* 背景色 */
--bg-primary: #0f172a;     /* 深蓝黑 - 主背景 */
--bg-secondary: #1e293b;   /*  slate-800 - 卡片背景 */
--bg-tertiary: #334155;    /*  slate-700 - 边框/分隔 */

/* 文字色 */
--text-primary: #f8fafc;   /*  slate-50 - 主要文字 */
--text-secondary: #94a3b8; /*  slate-400 - 次要文字 */
--text-muted: #64748b;     /*  slate-500 - 提示文字 */
```

---

### 3.2 页面架构

```
┌─────────────────────────────────────────────────────────────┐
│  Sidebar Navigation    │  Main Content Area                   │
│  ┌─────────────────┐   │  ┌───────────────────────────────┐  │
│  │  Logo           │   │  │  Header (Breadcrumb + User)    │  │
│  ├─────────────────┤   │  └───────────────────────────────┘  │
│  │ Dashboard       │   │  ┌───────────────────────────────┐  │
│  │ 数字指纹        │   │  │                               │  │
│  │ 企业数据        │   │  │     Page Content              │  │
│  │ CoBAn分析       │   │  │                               │  │
│  │ 可视化中心      │   │  │                               │  │
│  │ 系统设置        │   │  │                               │  │
│  └─────────────────┘   │  └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.3 页面设计详情

#### 3.3.1 Dashboard (数据总览)

**布局**: 网格卡片布局 (4列)

**核心组件**:
- 统计卡片（玻璃效果）：
  - 数据集总数
  - 风险分析次数
  - CoBAn训练批次
  - 机密检测文档数

- 实时监控面板：
  - 最近风险分析趋势图（折线图）
  - 机密检测状态分布（环形图）
  - 活跃数据集列表

**设计亮点**:
- 统计数字使用渐变色文字动画
- 图表带发光效果（box-shadow）
- 卡片悬停时轻微上浮 + 光晕扩散

---

#### 3.3.2 数字指纹管理

**布局**: 左右分栏（左：文件树，右：指纹详情）

**核心功能**:
- 文件上传区（拖拽上传 + 点击选择）
- 指纹生成按钮
- 指纹列表展示：
  - 文档指纹（MD5，可折叠查看）
  - 分句指纹列表
- 复制/导出功能

**交互设计**:
- 上传区带扫描动画效果
- 指纹值显示为短码 + 点击展开完整
- 相似度比对功能（比对两个指纹）

---

#### 3.3.3 企业数据管理

**布局**: 三栏布局（数据集列表 | 属性详情 | 样本数据）

**核心页面**:

**1. 数据集列表页**
- 卡片式展示所有数据集
- 每个卡片显示：
  - 数据集名称 + 代码
  - 状态标签（活跃/归档）
  - 属性数量 / 样本数量
  - 最后更新时间
- 新建数据集按钮（浮出表单）

**2. 数据集详情页**
- Tab切换：属性定义 | 样本数据 | 知识图谱 | 风险分析

**属性定义Tab**:
- 表格展示属性元数据
- 敏感字段高亮显示（玫瑰色边框）
- 批量导入按钮

**样本数据Tab**:
- 表格展示样本（分页）
- 敏感数据脱敏显示（*****）
- 点击查看详情弹窗

**知识图谱Tab**:
- 使用D3.js/ECharts渲染力导向图
- 节点：属性（方型）、样本值（圆形）
- 边：显性关系（实线）、隐性关系（虚线）
- 点击查看边详情（LR/PIC/Risk值）

**风险分析Tab**:
- 触发分析按钮 + 进度指示
- 风险排行榜（柱状图）
- LR/PIC散点图
- 风险阈值滑块控制

---

#### 3.3.4 CoBAn分析中心

**布局**: 标签页切换（训练管理 | 检测中心 | 可视化）

**训练管理页**:
- 训练批次列表（时间线样式）
- 每个批次卡片显示：
  - 批次ID、名称、状态
  - 文档数量（机密/非机密）
  - 聚类数量
  - 训练时间
  - 操作按钮（查看/导出/删除）
- 新建训练按钮（弹出配置向导）

**训练配置向导**（Stepper）:
1. 基本信息：名称、数据源类型
2. 语料配置：文件夹路径/手动输入
3. 参数调优：聚类数、阈值等（滑块控制）
4. 确认提交

**检测中心页**:
- 文本输入区（支持多文档批量）
- 选择检测模型（下拉选择训练批次）
- 检测按钮 + 实时进度
- 检测结果列表：
  - 文档名称
  - 机密性评分（进度条 + 数值）
  - 判定结果（徽章：机密/非机密）
  - 查看详情按钮

**检测结果详情弹窗**:
- 原文本高亮显示（机密术语标红）
- 匹配的聚类信息
- 证据链展示
- 置信度评分

**可视化页**:
- 批次总览图表：
  - 聚类分布（饼图）
  - 评分直方图
  - 检测趋势（折线图）
- 检测统计图表：
  - 分数箱线图
  - 状态分布（柱状图）
- 证据图（力导向图）

---

#### 3.3.5 可视化中心

**布局**: 画廊式网格布局

**功能**:
- 按模块筛选（企业数据/CoBAn）
- 图表预览卡片（缩略图）
- 点击放大查看
- 导出功能（PNG/SVG/JSON）
- 一键生成报告（组合多个图表）

---

### 3.4 组件设计规范

#### 3.4.1 通用组件

**玻璃卡片（GlassCard）**:
```css
.glass-card {
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 12px;
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
  transition: all 0.3s ease;
}

.glass-card:hover {
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow: 0 8px 40px rgba(99, 102, 241, 0.15);
  transform: translateY(-2px);
}
```

**霓虹按钮（NeonButton）**:
```css
.neon-btn-primary {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  border: none;
  border-radius: 8px;
  color: white;
  padding: 10px 24px;
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.3);
  transition: all 0.3s ease;
}

.neon-btn-primary:hover {
  box-shadow: 0 0 30px rgba(99, 102, 241, 0.5);
  transform: translateY(-1px);
}
```

**数据徽章（DataBadge）**:
- 机密：玫瑰红背景 + 闪烁效果
- 高危：琥珀色背景
- 正常：青色背景
- 归档：灰色背景

**评分条（ScoreBar）**:
- 渐变色进度条（蓝 -> 黄 -> 红）
- 动态数值显示
- 阈值标记线

#### 3.4.2 图表组件

**风险趋势图**: 面积图 + 渐变填充
**聚类分布图**: 玫瑰图（Polar Bar）
**知识图谱**: 力导向图 + 节点发光效果
**证据链图**: 桑基图（Sankey）或 层级树图

---

### 3.5 交互设计

#### 3.5.1 动效规范

**页面过渡**:
- 路由切换：淡入淡出（200ms）
- 列表加载： staggered fade-in（每项延迟50ms）

**微交互**:
- 按钮悬停：scale(1.02) + 光晕扩散
- 卡片悬停：上浮 + 边框发光
- 加载状态：脉冲动画 + 骨架屏
- 成功提示：Toast从右侧滑入，带绿色勾图标

**数据更新**:
- 数字变化：滚动动画（count-up）
- 图表更新：平滑过渡（transition）
- 高风险警告：红色脉冲边框

#### 3.5.2 响应式设计

**断点**:
- Desktop: 1440px+（完整侧边栏）
- Laptop: 1024px-1439px（可折叠侧边栏）
- Tablet: 768px-1023px（汉堡菜单）
- Mobile: <768px（单列布局）

---

### 3.6 技术栈推荐

**框架**: React 18 + TypeScript
**构建工具**: Vite
**UI组件库**: Ant Design 5.x + 自定义主题
**状态管理**: Zustand
**图表库**: 
- ECharts（主要图表）
- D3.js（知识图谱/自定义可视化）
**样式**: Tailwind CSS + CSS Variables
**动画**: Framer Motion
**HTTP客户端**: Axios
**代码规范**: ESLint + Prettier

---

### 3.7 项目结构建议

```
frontend/
├── public/
│   └── assets/
├── src/
│   ├── api/                    # API接口封装
│   │   ├── client.ts            # Axios实例
│   │   ├── fingerprints.ts
│   │   ├── enterprise.ts
│   │   └── coban.ts
│   ├── components/             # 通用组件
│   │   ├── ui/                  # 基础UI组件
│   │   │   ├── GlassCard.tsx
│   │   │   ├── NeonButton.tsx
│   │   │   ├── DataBadge.tsx
│   │   │   └── ScoreBar.tsx
│   │   └── charts/              # 图表组件
│   │       ├── RiskChart.tsx
│   │       ├── KnowledgeGraph.tsx
│   │       └── EvidenceGraph.tsx
│   ├── pages/                  # 页面组件
│   │   ├── Dashboard/
│   │   ├── Fingerprints/
│   │   ├── EnterpriseData/
│   │   ├── CoBan/
│   │   └── Visualization/
│   ├── hooks/                  # 自定义Hooks
│   ├── store/                  # 状态管理
│   ├── styles/                 # 全局样式
│   │   ├── variables.css       # CSS变量
│   │   └── global.css
│   ├── utils/                  # 工具函数
│   └── types/                  # TypeScript类型
├── package.json
├── tailwind.config.js
├── tsconfig.json
└── vite.config.ts
```

---

### 3.8 核心页面原型描述

#### Dashboard页面
```
┌──────────────────────────────────────────────────────────────┐
│  DLP Security Platform                          [用户头像]  │
├──────────┬─────────────────────────────────────────────────┤
│          │  今日概览                                          │
│ [侧边栏]  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│ Dashboard│  │ 数据集   │ │ 风险分析 │ │ 训练批次 │ │ 检测数 │ │
│ 数字指纹  │  │   12     │ │   156    │ │    8     │ │  342   │ │
│ 企业数据  │  │   ↑ 3   │ │   ↑ 12% │ │   ↑ 2   │ │ ↑ 28% │ │
│ CoBAn分析 │  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
│ 可视化   │                                                  │
│ 设置    │  ┌─────────────────────┐ ┌─────────────────────┐   │
│         │  │   风险趋势图         │ │   检测状态分布       │   │
│         │  │                     │ │                     │   │
│         │  │    /\    /\        │ │    ┌─────┐          │   │
│         │  │   /  \  /  \       │ │   /       \         │   │
│         │  │  /    \/    \      │ │  /    ●    \        │   │
│         │  │ /              \    │ │ /             \     │   │
│         │  └─────────────────────┘ └─────────────────────┘   │
│         │                                                  │
│         │  ┌─────────────────────────────────────────────┐  │
│         │  │         最近活跃数据集                        │  │
│         │  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    │  │
│         │  │  [●] 客户信息表  ·  上次分析: 2小时前         │  │
│         │  │  [○] 财务数据    ·  上次分析: 1天前           │  │
│         │  └─────────────────────────────────────────────┘  │
└──────────┴─────────────────────────────────────────────────┘
```

#### CoBAn训练详情页
```
┌──────────────────────────────────────────────────────────────┐
│  CoBAn分析  /  训练批次  /  run_20240305_001                  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Run: run_20240305_001    [训练中...]                   │  │
│  │  语料: 1500文档 (800机密/700非机密)                     │  │
│  │  聚类: 3个    术语: 120个                              │  │
│  │  创建: 2024-03-05 14:32                               │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌───────────────────────┐  ┌─────────────────────────────┐  │
│  │    聚类分布            │  │      机密评分分布            │  │
│  │                       │  │                             │  │
│  │      ┌───┐            │  │  ████████████               │  │
│  │     /  A  \           │  │  ████████████████           │  │
│  │    /   │   \          │  │  ██████████████████         │  │
│  │   B────┼────C         │  │  ████████████████           │  │
│  │        │              │  │  ██████████                 │  │
│  │      [35%]            │  │                             │  │
│  │    A:450 B:380 C:670  │  │    0.2  0.4  0.6  0.8  1.0  │  │
│  └───────────────────────┘  └─────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  机密术语TOP10                                          │  │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  │
│  │  1. [███████░░░] 机密合同      0.92  ●●●●●            │  │
│  │  2. [██████░░░░] 财务数据      0.88  ●●●●○            │  │
│  │  3. [█████░░░░░] 客户信息      0.85  ●●●●○            │  │
│  │  ...                                                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 四、接口调用示例

### 4.1 API Client封装

```typescript
// api/client.ts
import axios from 'axios';

const apiClient = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 可添加认证token
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 统一错误处理
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

export default apiClient;
```

### 4.2 企业数据API

```typescript
// api/enterprise.ts
import apiClient from './client';

export const enterpriseApi = {
  // 创建数据集
  createDataset: (data: DatasetCreateRequest) =>
    apiClient.post('/enterprise-data/datasets', data),

  // 批量注册属性
  registerAttributes: (code: string, data: AttributeBatchRequest) =>
    apiClient.post(`/enterprise-data/datasets/${code}/attributes/batch`, data),

  // 批量导入样本
  importSamples: (code: string, data: SampleBatchRequest) =>
    apiClient.post(`/enterprise-data/datasets/${code}/samples/batch`, data),

  // 触发风险分析
  analyzeRisk: (code: string) =>
    apiClient.post(`/enterprise-data/datasets/${code}/analysis/implicit-risk`),

  // 获取风险可视化数据
  getRiskVisualization: (code: string, params?: { theta?: number; top_n?: number }) =>
    apiClient.get(`/enterprise-data/datasets/${code}/visualization/implicit-risk/latest`, { params }),

  // 导出风险图像
  exportRiskImage: (code: string, params: ImageExportParams) =>
    apiClient.get(`/enterprise-data/datasets/${code}/visualization-images/implicit-risk`, {
      params,
      responseType: 'blob',
    }),
};
```

### 4.3 CoBAn API

```typescript
// api/coban.ts
import apiClient from './client';

export const cobanApi = {
  // 提交训练任务
  train: (data: TrainRequest) =>
    apiClient.post('/coban/train', data),

  // 提交检测任务
  detect: (data: DetectRequest) =>
    apiClient.post('/coban/detect', data),

  // 获取训练详情
  getModel: (runId: string) =>
    apiClient.get(`/coban/models/${runId}`),

  // 获取检测详情
  getDetection: (docUid: string) =>
    apiClient.get(`/coban/detections/${docUid}`),

  // 获取可视化数据
  getOverview: (runId: string) =>
    apiClient.get(`/coban/visualization/run/${runId}/overview`),

  getDetections: (runId: string, params?: PaginationParams) =>
    apiClient.get(`/coban/visualization/run/${runId}/detections`, { params }),

  getEvidenceGraph: (docUid: string) =>
    apiClient.get(`/coban/visualization/detection/${docUid}/evidence-graph`),
};
```

---

## 五、实施建议

### 5.1 开发优先级

**第一阶段（MVP）**:
1. 项目脚手架搭建 + 主题配置
2. Dashboard页面（静态数据）
3. 企业数据模块（数据集CRUD）
4. CoBAn训练/检测基本流程

**第二阶段**:
1. 可视化图表集成
2. 知识图谱展示
3. 数字指纹模块
4. 移动端适配

**第三阶段**:
1. 实时数据更新（WebSocket）
2. 高级搜索/筛选
3. 报告导出功能
4. 性能优化

### 5.2 注意事项

1. **数据安全**: 敏感数据在传输和展示时需要脱敏处理
2. **大文件处理**: 数字指纹生成和CoBAn训练涉及大文件，需要进度指示和断点续传考虑
3. **图表性能**: 知识图谱节点过多时需要虚拟化或分层加载
4. **错误处理**: API可能返回大量数据或长时间处理，需要完善的错误边界和超时处理

---

## 六、参考资源

- **后端Swagger文档**: `http://localhost:8000/docs`
- **设计灵感**:
  - [Dribbble - Dashboard Design](https://dribbble.com/search/dashboard)
  - [Glassmorphism Generator](https://hype4.academy/tools/glassmorphism-generator)
- **图表库文档**:
  - [ECharts Examples](https://echarts.apache.org/examples/)
  - [D3.js Gallery](https://observablehq.com/@d3/gallery)

---

*文档版本: 1.0*
*创建日期: 2026-03-05*
*作者: AI Assistant*
