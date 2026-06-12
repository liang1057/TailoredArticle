"""
read 应用 - 文章阅读与标签管理 v2.0
- 三栏布局前端 + 标签OR查询 + 文章摘要详情
- 端口 5081，与 collector 的 5000 不冲突
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
    conn.row_factory = sqlite3.Row
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

    c.execute("SELECT id, code, level, parent_code, label FROM labels ORDER BY code")
    rows = c.fetchall()
    conn.close()

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
    获取文章列表（含摘要）
    参数：
        - ?tags=1,2,3  标签ID列表（多选，OR关系/并集）
        - ?q=关键词     标题模糊搜索
    返回：文章列表含标题、来源、路径、标签、摘要、关键词
    """
    conn = get_db()
    c = conn.cursor()

    # 解析参数
    tag_ids = request.args.get('tags', '')
    query = request.args.get('q', '').strip()

    if tag_ids:
        tag_ids = [int(x) for x in tag_ids.split(',') if x.isdigit()]
    else:
        tag_ids = []

    # 构建 WHERE 条件
    conditions = []
    params = []

    if tag_ids:
        # OR/并集查询：文章包含任一选中标签即可
        placeholders = ','.join('?' * len(tag_ids))
        conditions.append(f"""
            a.id IN (
                SELECT DISTINCT article_id FROM article_labels
                WHERE label_id IN ({placeholders})
            )
        """)
        params.extend(tag_ids)

    if query:
        conditions.append("a.title LIKE ?")
        params.append(f'%{query}%')

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
        SELECT a.id, a.url, a.title, a.local_path, a.created_at, a.source,
               aa.summary, aa.keywords
        FROM articles a
        LEFT JOIN article_analysis aa ON a.id = aa.article_id
        WHERE {where_clause}
        ORDER BY a.created_at DESC
    """

    c.execute(sql, params)
    rows = c.fetchall()

    articles = []
    for row in rows:
        article = {
            "id": row["id"],
            "url": row["url"],
            "title": row["title"] or "无标题",
            "local_path": row["local_path"],
            "created_at": row["created_at"],
            "source": row["source"],
            "summary": row["summary"] or "",
            "keywords": row["keywords"] or ""
        }

        c.execute("""
            SELECT l.code, l.label 
            FROM article_labels al 
            JOIN labels l ON al.label_id = l.id 
            WHERE al.article_id = ?
        """, (row["id"],))
        article["tags"] = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

        articles.append(article)

    conn.close()
    return jsonify(articles)


@app.route('/api/article/<int:article_id>')
def get_article(article_id):
    """
    获取单篇文章的 Markdown 内容（API接口）
    """
    conn = get_db()
    c = conn.cursor()

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

    c.execute("""
        SELECT l.code, l.label 
        FROM article_labels al 
        JOIN labels l ON al.label_id = l.id 
        WHERE al.article_id = ?
    """, (article_id,))
    article["tags"] = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

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
    """
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id, url, title, local_path, created_at, source FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "文章不存在", 404

    md_content = ""
    if row["local_path"]:
        md_path = os.path.join(row["local_path"], "article.md")
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

    c.execute("""
        SELECT l.code, l.label 
        FROM article_labels al 
        JOIN labels l ON al.label_id = l.id 
        WHERE al.article_id = ?
    """, (article_id,))
    tags = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

    conn.close()

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
    """
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT local_path FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    conn.close()

    if not row or not row["local_path"]:
        return "文件不存在", 404

    base_path = os.path.abspath(row["local_path"])
    target_path = os.path.abspath(os.path.join(base_path, filepath))

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

    c.execute("SELECT id, title FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "文章不存在"}), 404

    article_title = row["title"]

    c.execute("DELETE FROM article_labels WHERE article_id = ?", (article_id,))

    for code in new_tags:
        c.execute("SELECT id, label FROM labels WHERE code = ?", (code,))
        label_row = c.fetchone()
        if label_row:
            try:
                c.execute("""
                    INSERT INTO article_labels (article_id, label_id, article, label)
                    VALUES (?, ?, ?, ?)
                """, (article_id, label_row["id"], article_title, label_row["label"]))
            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5081, debug=False)