"""
read 应用 - 文章阅读与标签管理 v3.0
- 三栏布局 + 标签OR查询 + 文章摘要详情
- share_id 反爬 + token 认证 + 删除功能
- 端口 5081
"""

import os
import json
import sqlite3
import uuid
from flask import Flask, render_template, jsonify, send_file, request

app = Flask(__name__)

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(BASE_DIR, "..", "采集库")
DB_PATH = os.path.join(WORKSPACE, "index.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def get_db():
    """获取数据库连接，并确保表结构最新"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn):
    """确保数据库表结构包含最新字段"""
    c = conn.cursor()

    # 创建 articles 表（含 share_id 和 status）
    c.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            local_path TEXT,
            created_at TEXT,
            source TEXT,
            status INTEGER DEFAULT 1,
            share_id TEXT UNIQUE
        )
    """)

    # 为已有数据生成 share_id
    c.execute("SELECT id FROM articles WHERE share_id IS NULL OR share_id = ''")
    for row in c.fetchall():
        short_id = uuid.uuid4().hex[:8]
        c.execute("UPDATE articles SET share_id = ? WHERE id = ?", (short_id, row[0]))

    conn.commit()


def _load_tokens():
    """从本地 JSON 加载 token"""
    if not os.path.exists(CONFIG_PATH):
        default_token = uuid.uuid4().hex[:8]
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({"token": default_token}, f, ensure_ascii=False, indent=2)
        return default_token
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f).get("token", ['AN3M-Q8U2'])


# ===== Token 认证装饰器 =====
def token_required(func):
    """检查 URL 参数 token 是否匹配 config.json"""
    def wrapper(*args, **kwargs):
        expected = _load_tokens()                    # ① 从配置读取合法 Token
        provided = request.args.get('token', '')     # ② 从 URL 参数读取 Token
        if provided not in expected:                     # ③ 不匹配则返回 403
            return f"Unauthorized: [{provided}] is invalid or missing token", 403
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


@app.route('/')
@token_required
def index():
    """主页面（需 token）"""
    return render_template('index.html')


@app.route('/api/labels')
@token_required
def get_labels():
    """获取标签树"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, code, level, parent_code, label FROM labels ORDER BY code")
    rows = c.fetchall()
    conn.close()

    tree = []
    children_map = {}
    for row in rows:
        item = {"id": row["id"], "code": row["code"], "label": row["label"], "level": row["level"], "children": []}
        if row["level"] == 0:
            tree.append(item)
            children_map[row["code"]] = item
        else:
            parent = children_map.get(row["parent_code"])
            if parent:
                parent["children"].append({"id": row["id"], "code": row["code"], "label": row["label"]})
    return jsonify(tree)


@app.route('/api/articles')
@token_required
def get_articles():
    """获取文章列表（含摘要），标签 OR/并集查询"""
    conn = get_db()
    c = conn.cursor()

    tag_ids = request.args.get('tags', '')
    query = request.args.get('q', '').strip()
    tag_ids = [int(x) for x in tag_ids.split(',') if x.isdigit()] if tag_ids else []

    conditions = []
    params = []

    if tag_ids:
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
               a.share_id, a.status, aa.summary, aa.keywords
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
            "share_id": row["share_id"],
            "status": row["status"],
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
@token_required
def get_article(article_id):
    """获取单篇文章 Markdown 内容（API）"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, url, title, local_path, created_at, source, share_id FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "文章不存在"}), 404

    article = {
        "id": row["id"], "url": row["url"], "title": row["title"] or "无标题",
        "local_path": row["local_path"], "created_at": row["created_at"],
        "source": row["source"], "share_id": row["share_id"]
    }
    c.execute("""
        SELECT l.code, l.label FROM article_labels al 
        JOIN labels l ON al.label_id = l.id WHERE al.article_id = ?
    """, (article_id,))
    article["tags"] = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

    md_content = ""
    if row["local_path"]:
        md_path = os.path.join(row["local_path"], "article.md")
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

    conn.close()
    return jsonify({"article": article, "markdown": md_content})


@app.route('/article/<share_id>')
def article_page(share_id):
    """独立文章阅读页面（通过 share_id 打开，无需 token）"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, url, title, local_path, created_at, source, share_id FROM articles WHERE share_id = ?", (share_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "文章不存在", 404

    md_content = ""
    if row["local_path"]:
        md_path = os.path.join(row["local_path"], "article.md")
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                full_md = f.read()
            # 从 "采集时间" 行的下一行开始截取正文
            md_content = _extract_body(full_md)

    c.execute("""
        SELECT l.code, l.label FROM article_labels al 
        JOIN labels l ON al.label_id = l.id WHERE al.article_id = ?
    """, (row["id"],))
    tags = [{"code": r["code"], "label": r["label"]} for r in c.fetchall()]

    conn.close()

    processed_md = md_content.replace('](images/', f'](/api/file/{row["id"]}/images/')

    return render_template('article.html',
        article=row,
        tags=tags,
        markdown=processed_md
    )


def _extract_body(full_md):
    """从 markdown 中提取正文：找到'采集时间'行，从它的下一行开始"""
    lines = full_md.split('\n')
    for i, line in enumerate(lines):
        if '采集时间' in line or 'created_at' in line.lower():
            # 从采集时间行的下一行开始
            start = i + 1
            # 跳过可能的空行和分隔线
            while start < len(lines) and (lines[start].strip() == '' or lines[start].strip().startswith('---')):
                start += 1
            return '\n'.join(lines[start:])
    # 找不到采集时间行，返回全部内容
    return full_md


@app.route('/api/file/<int:article_id>/<path:filepath>')
def get_file(article_id, filepath):
    """读取文章目录下的文件（图片等）"""
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
@token_required
def update_tags(article_id):
    """更新文章标签"""
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


@app.route('/api/article/<int:article_id>', methods=['DELETE'])
@token_required
def delete_article(article_id):
    """删除文章及相关记录，同时删除本地文件夹"""
    conn = get_db()
    c = conn.cursor()

    # 查询文章路径
    c.execute("SELECT local_path FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "文章不存在"}), 404

    local_path = row["local_path"]

    # 删除关联记录
    c.execute("DELETE FROM article_labels WHERE article_id = ?", (article_id,))
    c.execute("DELETE FROM article_analysis WHERE article_id = ?", (article_id,))
    c.execute("DELETE FROM articles WHERE id = ?", (article_id,))

    conn.commit()
    conn.close()

    # 删除本地文件夹
    if local_path and os.path.exists(local_path):
        import shutil
        try:
            shutil.rmtree(local_path)
        except Exception as e:
            print(f"删除文件夹失败: {e}")

    return jsonify({"status": "ok"})


if __name__ == '__main__':
    # 启动时确保 token 文件存在
    _load_tokens()

    # 如果命令行输入参数 --port , 则port按照输入参数进行设置
    import sys
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])  # 配置文件中是5080，用于持久化运行
    else:
        port = 4080  # 默认端口号，用于调试
    app.run(host='0.0.0.0', port=port, debug=False)
