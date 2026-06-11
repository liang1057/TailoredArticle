"""
read 应用 - 文章阅读与标签管理
- 提供文章列表、标签筛选、搜索、Markdown 阅读、文件读取 API
- 端口 8080，与 collector 的 5000 不冲突
"""

import os
import sqlite3
from flask import Flask, render_template, jsonify, send_file, request

app = Flask(__name__)

# 路径配置（与 collector 共用采集库）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(BASE_DIR, "..", "采集库")
DB_PATH = os.path.join(WORKSPACE, "index.db")


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 使结果可用字典方式访问
    return conn


@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')


@app.route('/api/labels')
def get_labels():
    """
    获取标签树
    返回：一级标签列表，每个包含 children 二级标签
    """
    conn = get_db()
    c = conn.cursor()

    # 查询所有标签
    c.execute("SELECT id, code, level, parent_code, label FROM labels ORDER BY code")
    rows = c.fetchall()
    conn.close()

    # 构建树形结构
    tree = []
    children_map = {}

    for row in rows:
        item = {
            "id": row["id"],
            "code": row["code"],
            "label": row["label"],
            "level": row["level"],
            "children": []
        }
        if row["level"] == 0:
            tree.append(item)
            children_map[row["code"]] = item
        else:
            parent = children_map.get(row["parent_code"])
            if parent:
                parent["children"].append({
                    "id": row["id"],
                    "code": row["code"],
                    "label": row["label"]
                })

    return jsonify(tree)


@app.route('/api/articles')
def get_articles():
    """
    获取文章列表
    参数：
        - ?tags=1,2,3  标签ID列表（多选，AND关系）
        - ?q=关键词     标题模糊搜索
    返回：文章列表含标题、来源、路径、标签
    """
    conn = get_db()
    c = conn.cursor()

    # 解析参数
    tag_ids = request.args.get('tags', '')
    query = request.args.get('q', '').strip()  # 搜索关键词

    if tag_ids:
        tag_ids = [int(x) for x in tag_ids.split(',') if x.isdigit()]
    else:
        tag_ids = []

    # 构建 WHERE 条件
    conditions = []
    params = []

    if tag_ids:
        # 多标签筛选：文章必须同时包含所有选中标签
        placeholders = ','.join('?' * len(tag_ids))
        conditions.append(f'''
            a.id IN (
                SELECT article_id FROM article_labels
                WHERE label_id IN ({placeholders})
                GROUP BY article_id
                HAVING COUNT(DISTINCT label_id) = ?
            )
        ''')
        params.extend(tag_ids)
        params.append(len(tag_ids))

    if query:
        # 标题模糊搜索
        conditions.append("a.title LIKE ?")
        params.append(f'%{query}%')

    # 组装 SQL
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = f'''
        SELECT a.id, a.url, a.title, a.local_path, a.created_at, a.source
        FROM articles a
        WHERE {where_clause}
        ORDER BY a.created_at DESC
    '''

    c.execute(sql, params)
    rows = c.fetchall()

    # 查询每篇文章的标签
    articles = []
    for row in rows:
        article = {
            "id": row["id"],
            "url": row["url"],
            "title": row["title"] or "无标题",
            "local_path": row["local_path"],
            "created_at": row["created_at"],
            "source": row["source"]
        }

        # 查询该文章的标签
        c.execute('''
            SELECT l.code, l.label 
            FROM article_labels al 
            JOIN labels l ON al.label_id = l.id 
            WHERE al.article_id = ?
        ''', (row["id"],))
        article["tags"] = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

        articles.append(article)

    conn.close()
    return jsonify(articles)


@app.route('/api/article/<int:article_id>')
def get_article(article_id):
    """
    获取单篇文章的 Markdown 内容（API接口，供前端调用）
    返回：Markdown 文本 + 基础信息
    """
    conn = get_db()
    c = conn.cursor()

    # 查询文章信息
    c.execute("SELECT id, url, title, local_path, created_at, source FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "文章不存在"}), 404

    article = {
        "id": row["id"],
        "url": row["url"],
        "title": row["title"] or "无标题",
        "local_path": row["local_path"],
        "created_at": row["created_at"],
        "source": row["source"]
    }

    # 查询标签
    c.execute('''
        SELECT l.code, l.label 
        FROM article_labels al 
        JOIN labels l ON al.label_id = l.id 
        WHERE al.article_id = ?
    ''', (article_id,))
    article["tags"] = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

    # 读取 Markdown 文件
    md_content = ""
    if row["local_path"]:
        md_path = os.path.join(row["local_path"], "article.md")
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

    conn.close()
    return jsonify({
        "article": article,
        "markdown": md_content
    })


@app.route('/article/<int:article_id>')
def article_page(article_id):
    """
    独立文章阅读页面（新窗口打开）
    直接渲染完整 HTML，不需要左侧标签栏
    """
    conn = get_db()
    c = conn.cursor()

    # 查询文章信息
    c.execute("SELECT id, url, title, local_path, created_at, source FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "文章不存在", 404

    # 读取 Markdown 文件
    md_content = ""
    if row["local_path"]:
        md_path = os.path.join(row["local_path"], "article.md")
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

    # 查询标签
    c.execute('''
        SELECT l.code, l.label 
        FROM article_labels al 
        JOIN labels l ON al.label_id = l.id 
        WHERE al.article_id = ?
    ''', (article_id,))
    tags = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

    conn.close()

    # 处理图片路径（相对路径 → 绝对 URL）
    processed_md = md_content.replace(
        '](images/',
        f'](/api/file/{article_id}/images/'
    )

    return render_template('article.html',
        article=row,
        tags=tags,
        markdown=processed_md
    )


@app.route('/api/file/<int:article_id>/<path:filepath>')
def get_file(article_id, filepath):
    """
    读取文章目录下的文件（图片等）
    路径：/api/file/<id>/images/001.jpg
    """
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT local_path FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    conn.close()

    if not row or not row["local_path"]:
        return "文件不存在", 404

    # 拼接完整路径，并安全检查（防止目录遍历）
    base_path = os.path.abspath(row["local_path"])
    target_path = os.path.abspath(os.path.join(base_path, filepath))

    # 确保目标路径在 base_path 下
    if not target_path.startswith(base_path):
        return "非法路径", 403

    if not os.path.exists(target_path):
        return "文件不存在", 404

    return send_file(target_path)


@app.route('/api/article/<int:article_id>/tags', methods=['POST'])
def update_tags(article_id):
    """
    更新文章标签
    接收：{"tags": ["A01", "C04"]}
    """
    data = request.get_json() or {}
    new_tags = data.get('tags', [])

    conn = get_db()
    c = conn.cursor()

    # 验证文章存在
    c.execute("SELECT id, title FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "文章不存在"}), 404

    article_title = row["title"]

    # 删除旧标签
    c.execute("DELETE FROM article_labels WHERE article_id = ?", (article_id,))

    # 插入新标签
    for code in new_tags:
        c.execute("SELECT id, label FROM labels WHERE code = ?", (code,))
        label_row = c.fetchone()
        if label_row:
            try:
                c.execute('''
                    INSERT INTO article_labels (article_id, label_id, article, label)
                    VALUES (?, ?, ?, ?)
                ''', (article_id, label_row["id"], article_title, label_row["label"]))
            except sqlite3.IntegrityError:
                pass  # 重复，忽略

    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    # 端口 8080，与 collector 的 5000 不冲突
    app.run(host='0.0.0.0', port=5081, debug=False)