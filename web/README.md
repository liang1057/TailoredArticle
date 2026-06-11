好的，我来设计一个 `read` 显示应用。这是一个**本地 Web 界面**，用 Flask 提供后端 API，前端用纯 HTML/JS 实现。

## 总体设计

```
read/
├── app.py              # Flask 后端服务
├── static/
│   ├── style.css       # 样式
│   └── script.js       # 前端交互
├── templates/
│   └── index.html      # 主页面
└── db_schema_v1.0.json # 复用标签配置
```

---

## 后端 API 设计（Flask）

| 接口 | 方法 | 功能 |
|:---|:---|:---|
| `/api/labels` | GET | 获取所有标签（树形结构） |
| `/api/articles` | GET | 按标签筛选获取文章列表 |
| `/api/article/<id>` | GET | 获取单篇文章的 Markdown 内容 |
| `/api/article/<id>/tags` | POST | 给文章打标签/修改标签 |

---

## 页面布局

```
┌─────────────────────────────────────────────────────┐
│  左侧边栏 (25%)          │  右侧主区域 (75%)         │
│                          │                           │
│  [标签筛选]               │  [文章标题列表]            │
│  □ 人工智能 ▼            │  ┌─────────────────┐     │
│    □ 大模型技术           │  │ 1. 文章标题A      │     │
│    □ AI Agent架构        │  │    来源: 微信      │     │
│    □ AIGC应用            │  │    标签: A01, C04 │     │
│  □ 编程技术 ▼            │  ├─────────────────┤     │
│    □ Python进阶          │  │ 2. 文章标题B      │     │
│  □ 投资理财 ▼            │  │    ...           │     │
│                          │  └─────────────────┘     │
│  [已选: A01, C04]        │                           │
│  [清空筛选]               │                           │
└─────────────────────────────────────────────────────┘
```

---

## 点击标题后的新页面

```
┌────────────────────────────────────────────┐
│  < 返回列表                                  │
│                                             │
│  # 文章标题                                  │
│                                             │
│  来源：https://mp.weixin.qq.com/s/...        │
│  采集时间：2026-06-08 14:15:37               │
│  标签：[大模型技术] [AI与机器人赛道] [编辑]   │
│                                             │
│  ────────────────────────────────────────   │
│                                             │
│  正文段落文字...                             │
│                                             │
│  [图片]                                     │
│  图片描述或原图                              │
│                                             │
│  更多段落...                                │
│                                             │
└────────────────────────────────────────────┘
```

**Markdown 渲染**：前端用 `marked.js` 将 `article.md` 转为 HTML，图片路径是相对路径，需要拼接 `local_path` 前缀。

---

## 关键实现细节

### 1. 标签多选逻辑

- 左侧标签树，点击复选框选中/取消
- 一级标签展开/收起二级
- 多选为 **OR** 关系：选 `A01` + `C04`，显示同时打这两个标签之一的文章（即标签交集）
- 已选标签在底部显示为蓝色药丸，可点击删除

### 2. 文章列表查询 SQL

```sql
-- 多标签筛选：article_id 同时存在于所有选中标签的关联记录中
SELECT a.id, a.url, a.title, a.local_path, a.created_at, a.source
FROM articles a
WHERE a.id IN (
    SELECT article_id FROM article_labels
    WHERE label_id IN (?, ?)  -- 选中的标签ID列表
    GROUP BY article_id
    HAVING COUNT(DISTINCT label_id) = 2  -- 必须同时满足所有选中标签
)
ORDER BY a.created_at DESC;
```

### 3. Markdown 图片路径处理

`article.md` 中的图片引用是：
```markdown
![001.jpg](images/001.jpg)
```

前端渲染时，需要把 `images/001.jpg` 转换为可访问的 URL：
```
/api/file/<article_id>/images/001.jpg
```

后端提供文件读取接口，从 `local_path` 下读取图片返回。

---

## 技术栈

| 层级 | 技术 | 理由 |
|:---|:---|:---|
| 后端 | Flask + SQLite | 你已熟悉，轻量 |
| 前端 | 原生 HTML + CSS + JS | 无需构建工具，直接运行 |
| Markdown 渲染 | marked.js (CDN) | 成熟稳定，支持图片 |
| 标签树 | 原生 JS 递归渲染 | 数据量小（57条），无需复杂框架 |

---

## 文件结构

```
read/
├── app.py                  # Flask 服务
├── templates/
│   └── index.html          # 单页应用（标签筛选 + 文章列表 + 阅读器）
├── static/
│   ├── style.css           # 布局样式
│   └── script.js           # 前端逻辑
└── db_schema_v1.0.json     # 复用（可选，用于初始化标签树）
```

---

## 启动方式

```bash
cd read
python app.py
```

访问 `http://localhost:8080`

---

需要我现在开始写完整代码吗？包含：
1. `app.py`（后端 API）
2. `index.html`（单页应用，含标签树、文章列表、Markdown 阅读器）
3. `style.css`（响应式布局）
4. `script.js`（多选逻辑、Markdown 渲染、页面切换）