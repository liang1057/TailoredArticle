"""
analyze.py - 文章分析模块
- 调用 Ollama 本地模型进行自动标签分类、摘要提取、关键词提取
- 支持单篇实时分析、批量历史文章补分析
- 分析结果写入 article_analysis 表，并更新 article_labels 关联表
"""

import os
import re
import json
import sqlite3
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path
import time
import requests


# ==================== 配置 ====================
# Ollama 服务地址
OLLAMA_URL = "http://localhost:11434/api/chat"


# payload = {
#     "model": "deepseek-r1:8b",
#     "messages": [{"role": "user", "content": "你好，请介绍一下自己"}],
#     "stream": False
# }
#
# time1 = time.time()
# response = requests.post(OLLAMA_URL, json=payload)
# print(response.json()["message"]["content"])
#
# print('运行用时间：', time.time() - time1)

# 使用的模型
MODEL_NAME = "deepseek-r1:8b"

# 数据库路径（与 collector 共用）
BASE_DIR = Path(__file__).parent
WORKSPACE = BASE_DIR / "采集库"
DB_PATH = WORKSPACE / "index.db"

# 标签体系（从数据库读取，缓存）
LABEL_SYSTEM = []

# 并发控制
MAX_CONCURRENT = 3


# ==================== 数据库操作 ====================
def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_analysis_table():
    """初始化分析结果表（如果不存在）"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS article_analysis (
            article_id INTEGER PRIMARY KEY,
            summary TEXT,
            keywords TEXT,
            sentiment TEXT,
            entities TEXT,
            analyzed_at TEXT,
            model TEXT,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    ''')
    conn.commit()
    conn.close()


def load_labels():
    """从数据库加载标签体系"""
    global LABEL_SYSTEM
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, label, level, parent_code FROM labels WHERE level = 1 ORDER BY code")
    LABEL_SYSTEM = [
        {"code": r["code"], "label": r["label"], "parent": r["parent_code"]}
        for r in c.fetchall()
    ]
    conn.close()
    return LABEL_SYSTEM


def get_article_content(article_id):
    """读取文章的 Markdown 内容"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT local_path, title FROM articles WHERE id = ?", (article_id,))
    row = c.fetchone()
    conn.close()

    if not row or not row["local_path"]:
        return None, None

    md_path = Path(row["local_path"]) / "article.md"
    if not md_path.exists():
        return row["title"], None

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return row["title"], content


def get_unanalyzed_articles(limit=None):
    """获取未分析的文章列表"""
    conn = get_db()
    c = conn.cursor()
    sql = '''
        SELECT a.id, a.title, a.local_path
        FROM articles a
        LEFT JOIN article_analysis aa ON a.id = aa.article_id
        WHERE aa.article_id IS NULL
        ORDER BY a.created_at DESC
    '''
    if limit:
        sql += f' LIMIT {limit}'
    c.execute(sql)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_analysis(article_id, article_title, tags, summary, keywords, sentiment=None, entities=None):
    """保存分析结果到数据库"""
    conn = get_db()
    c = conn.cursor()

    # 1. 保存分析详情
    c.execute('''
        INSERT OR REPLACE INTO article_analysis 
        (article_id, summary, keywords, sentiment, entities, analyzed_at, model)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        article_id,
        summary,
        keywords,
        sentiment,
        json.dumps(entities, ensure_ascii=False) if entities else None,
        datetime.now().isoformat(),
        MODEL_NAME
    ))

    # 2. 删除旧标签（默认的 H01 待分类）
    c.execute("DELETE FROM article_labels WHERE article_id = ?", (article_id,))

    # 3. 插入新标签
    for code in tags:
        c.execute("SELECT id, label FROM labels WHERE code = ?", (code.strip(),))
        row = c.fetchone()
        if row:
            c.execute('''
                INSERT INTO article_labels (article_id, label_id, article, label)
                VALUES (?, ?, ?, ?)
            ''', (article_id, row["id"], article_title, row["label"]))

    conn.commit()
    conn.close()


# ==================== Ollama 调用 ====================
def ollama_generate(prompt, session, timeout=1200):
    """异步调用 Ollama 生成"""
    payload = {
        "model": MODEL_NAME,
        #"prompt": prompt,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0.3,  # 低温度，输出稳定
            "num_predict": 2500   # 限制输出长度
        }
    }
    try:
        # async with session.post(OLLAMA_URL, json=payload, timeout=timeout) as resp:
        #     if resp.status != 200:
        #         return None
        #     data = await resp.json()
        #     return data.get("response", "")
        resp = requests.post(OLLAMA_URL, json=payload)
        return resp.json()
    except Exception as e:
        print(f"  [Ollama错误] {e}")
        return None

    '''
    # Ollama 调用 deepseek-r1:8b 完整返回字段注解
    resp = {
        'model': 'deepseek-r1:8b',                 # 当前调用的模型名称及版本
        'created_at': '2026-06-11T04:48:24.7233854Z',  # 模型生成响应的UTC时间戳
        'message': {
            'role': 'assistant',                   # 消息角色：assistant=模型助手回复
            'content': '\nA01,A03',                # 模型最终输出的正式回答内容
            'thinking': '\n好的，我现在需要处理用户的这个所以最终选择A01和A03。\n'  # 模型内部思考过程（R1专属思维链内容）
        },
        'done': True,                              # 请求是否正常结束，True=完整执行完毕
        'done_reason': 'stop',                     # 终止原因：stop=正常触达结束符完成输出
        'total_duration': 21616938400,             # 本次请求总耗时，单位：纳秒(ns)
        'load_duration': 5109833700,               # 模型加载至内存/显存耗时，单位：纳秒(ns)
        'prompt_eval_count': 1586,                 # 输入Prompt+上下文总Token数量
        'prompt_eval_duration': 1138114000,        # 输入Prompt解析计算耗时，单位：纳秒(ns)
        'eval_count': 727,                         # 模型输出内容总Token数量（含thinking+content）
        'eval_duration': 15350444000               # 逐Token生成回复耗时，单位：纳秒(ns)
    }
    '''


# ==================== 分析任务 ====================
def analyze_single(article_id, title, content, session):
    """分析单篇文章"""
    time1 = time.time()
    print(f"[开始] ID={article_id} 标题={title}")

    if not content:
        print(f"  [跳过] ID={article_id} 无内容")
        return

    # 提取前2000字用于分析（控制token）
    content_preview = content # [:2000]

    # 1. 标签分类
    labels_desc = "\n".join([f"{l['code']}={l['label']}" for l in LABEL_SYSTEM])
    tag_prompt = f"""你是一个文章分类专家。请根据以下文章，从标签列表中选择最相关的1-3个标签。
要求：
1. 只输出标签代码，用逗号分隔
2. 不要输出任何解释
3. 如果没有匹配标签，输出 H01
4. 输出格式示例：A01,C04

可用标签：{labels_desc}                
文章标题：{title}
文章内容：{content_preview}"""

    # tag_raw = await ollama_generate(tag_prompt, session)
    resp = ollama_generate(tag_prompt, session)
    tag_raw = resp.get("message", {}).get("content", "")
    if not tag_raw:
        return

    # 解析标签：提取所有匹配的 code
    tags = []
    for l in LABEL_SYSTEM:
        if l['code'] in tag_raw:
            tags.append(l['code'])
    if not tags:
        tags = ['H01']  # 兜底

    # 2. 摘要提取
    summary_prompt = f"""请总结以下文章的核心观点，200字以内。只输出摘要，不要解释。
                    文章标题：{title}
                    文章内容：{content_preview}"""

    summary = ollama_generate(summary_prompt, session)["message"]["content"].strip()
    #summary = (summary or "").strip()[:300]

    # 3. 关键词提取
    kw_prompt = f"""提取5个关键词，用逗号分隔。只输出关键词，不要解释。

文章内容：{content_preview}"""

    keywords = ollama_generate(kw_prompt, session)["message"]["content"].strip()
    #keywords = (keywords or "").strip()

    # 4. 保存结果
    save_analysis(article_id, title, tags, summary, keywords)
    print(f"  [完成]")
    print(f"    >标签={','.join(tags)} 关键词={keywords} \n    >摘要={summary[:80]}...")
    print(f"    >用时：{(time.time() - time1):.1f}s")


def analyze_batch(articles):
    """批量分析，控制并发"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def bounded_analyze(article):
        async with semaphore:
            async with aiohttp.ClientSession() as session:
                title, content = get_article_content(article["id"])
                analyze_single(article["id"], title or article["title"], content, session)

    tasks = [bounded_analyze(a) for a in articles]
    asyncio.gather(*tasks, return_exceptions=True)


# ==================== 入口函数 ====================
def analyze_one(article_id):
    """分析单篇文章（同步接口，供外部调用）"""
    init_analysis_table()
    load_labels()

    title, content = get_article_content(article_id)
    if not content:
        print(f"[错误] ID={article_id} 无内容")
        return

    # async def run():
    #     async with aiohttp.ClientSession() as session:
    #         analyze_single(article_id, title, content, session)
    #
    # asyncio.run(run())
    analyze_single(article_id, title, content, None)


def analyze_all(limit=None):
    """批量分析所有未分析文章"""
    init_analysis_table()
    load_labels()

    articles = get_unanalyzed_articles(limit)
    if not articles:
        print("[信息] 没有待分析的文章")
        return

    # print(f"[批量分析] 共 {len(articles)} 篇文章，并发={MAX_CONCURRENT}")
    # asyncio.run(analyze_batch(articles))
    # print("[完成] 批量分析结束")

    # 遍历articles
    for article in articles:
        analyze_one(article["id"])




# ==================== 命令行入口 ====================
if __name__ == '__main__':

    '''
    # 测试代码
    # analyze_one(id = 1)
    # analyze_all()
    '''

    # 解析命令行参数， 生产代码
    import argparse

    # 首先添加一些自定义的命令
    parser = argparse.ArgumentParser(description="文章分析工具")
    parser.add_argument("-m", "--mode", choices=["all", "one", "loop"],
                        help="命令：all=分析所有未分析文章，one=分析指定ID文章, loop=循环分析所有文章",
                        default="all")
    parser.add_argument("-id", nargs="?", help="文章ID（仅当mode=one时有效）")
    parser.add_argument("-s", "--sleep", type=int, help="循环分析间隔秒数（仅当mode=loop时有效）")
    args = parser.parse_args()

    # 判断是从命令行调用还是直接运行
    if args.mode == "all":  # 分析所有未分析文章
        analyze_all()
    elif args.mode == "one": # 分析指定ID文章
        analyze_one(args.id)
    elif args.mode == "loop": # 循环分析所有文章
        while True:
            analyze_all()
            time.sleep(args.sleep or 3600)  # 默认1小时
    else: # 未知命令
        print("[错误] 未知命令")
        parser.print_help()
        exit(1)





