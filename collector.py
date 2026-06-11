"""
采集处理主程序（v2.0 - 适配新数据库结构）
- 从 db_schema_v1.0.json 读取建表 SQL 和标签体系
- 文章表：articles(url, title, local_path, created_at, source)
- 标签表：labels(code, level, parent_code, label, description)
- 关联表：article_labels(article_id, label_id, article, label)
- 采集完成后自动打"待分类"标签(H01)，后续接入AI自动分类
"""

import os  # 导入操作系统接口模块，用于文件和目录操作
import re  # 导入正则表达式模块，用于文本匹配和处理
import sqlite3  # 导入SQLite数据库接口模块
import time  # 导入时间处理模块
import uuid  # 导入UUID模块，用于生成唯一标识符
import hashlib  # 导入哈希模块，用于生成哈希值
import json  # 导入JSON处理模块
from datetime import datetime  # 导入日期时间模块
from urllib.parse import urlparse, urljoin  # 导入URL解析模块

import requests  # 导入HTTP请求模块
from playwright.sync_api import sync_playwright  # 导入Playwright同步API

from tools import *

# ==================== 全局配置 ====================
# 脚本所在目录，所有路径以此为基准
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 工作空间：存放 inbox 队列、output 输出、index.db 数据库
WORKSPACE = os.path.join(BASE_DIR, "采集库")

# URL 待处理队列文件路径
INBOX_FILE = os.path.join(WORKSPACE, "inbox", "urls_pending.txt")

# SQLite 数据库路径
DB_PATH = os.path.join(WORKSPACE, "index.db")

# 数据库 schema 配置文件路径（JSON格式，含建表SQL和标签数据）
SCHEMA_PATH = os.path.join(BASE_DIR, "data_base.json")
DB_SQL_PATH = os.path.join(BASE_DIR, "db_sql.txt")
DB_DATA_JSON_PATH = os.path.join(BASE_DIR, 'data_base.json')

# 首次测试建议改为 False，观察浏览器是否正常打开微信文章
# True = 后台静默运行，False = 弹出浏览器窗口（调试用）
HEADLESS = True


# ==================== 数据库初始化 ====================
def init_storage():
    """
    从 JSON 配置文件读取建表 SQL 和标签体系，初始化数据库
    - 首次运行：创建三表 + 插入57条标签数据
    - 后续运行：检测到标签已存在则跳过
    """
    # 确保工作目录存在
    os.makedirs(os.path.join(WORKSPACE, "inbox"), exist_ok=True)
    os.makedirs(os.path.join(WORKSPACE, "output"), exist_ok=True)

    # 检查 schema 配置文件是否存在
    if not os.path.exists(DB_SQL_PATH):
        raise FileNotFoundError(f"找不到数据库配置文件: {DB_SQL_PATH}")

    # 读取文件中的sql
    with open(DB_SQL_PATH, "r", encoding='utf-8') as f:
        txt_sql = f.read()
        create_sql = txt_sql

    with open(DB_DATA_JSON_PATH, "r", encoding='utf-8') as f:
        tmp = json.load(f)
        sql_data = tmp["sql_v1.0"]
        labels_data = sql_data["label"]  # 标签列表

    # 读取 JSON 的数据
    # with open(DB_DATA_JSON_PATH, 'r', encoding='utf-8') as f:
    #     tmp = json.load(f)
    #
    # sql_data = tmp["sql_v1.0"]
    # create_sql = sql_data["sql"]  # 建表 SQL 字符串
    # labels_data = sql_data["label"]  # 标签列表（57条）

    # 连接数据库，执行建表
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript(create_sql)  # 执行三表创建 + 索引

    # 首次运行：初始化标签数据（仅当 labels 表为空时插入）
    c.execute("SELECT COUNT(*) FROM labels")
    if c.fetchone()[0] == 0:
        for item in labels_data:
            c.execute('''
                INSERT INTO labels (code, level, parent_code, label, description)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                item["code"],
                item["level"],
                item["parent_code"] if item["parent_code"] != -1 else None,
                item["label"],
                None  # description 预留，当前 JSON 中未定义
            ))
        print(f"[初始化] 已插入 {len(labels_data)} 条标签数据")
    else:
        print("[初始化] 标签数据已存在，跳过")

    conn.commit()
    conn.close()


# ==================== URL 来源识别 ====================
def classify_url(url):
    """
    根据域名识别文章来源类型
    返回：weixin / csdn / zhihu / unknown
    """
    host = urlparse(url).netloc.lower()
    if 'mp.weixin.qq.com' in host:
        return 'weixin'
    if 'blog.csdn.net' in host or 'csdn.net' in host:
        return 'csdn'
    if 'zhihu.com' in host:
        return 'zhihu'
    return 'unknown'


# ==================== 图片下载 ====================
# def download_image(url, save_path, headers=None):
#     """
#     通用图片下载，支持自定义请求头（如微信防盗链Referer）
#     返回：True=成功，False=失败
#     """
#     try:
#         h = {'User-Agent': 'Mozilla/5.0'}
#         if headers:
#             h.update(headers)
#         r = requests.get(url, headers=h, timeout=30)
#         if r.status_code == 200:
#             with open(save_path, 'wb') as f:
#                 f.write(r.content)
#             return True
#     except Exception as e:
#         print(f"  [图片失败] {url[:60]}... 原因: {e}")
#     return False
def download_image(url, save_path, headers=None):
    try:
        h = {'User-Agent': 'Mozilla/5.0'}
        if headers:
            h.update(headers)
        # 禁用代理，避免 Windows 系统代理干扰
        r = requests.get(url, headers=h, timeout=30, proxies={"http": None, "https": None})
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"  [图片失败] {url[:60]}... 原因: {e}")
    return False

# ==================== 微信文章下载 ====================
def download_weixin(page, url, save_dir):
    """
    微信公众号文章下载（格式保留版）
    修复：JS 代码转义冲突导致的 SyntaxError
    策略：先用 JS 提取原始块数据，再用 Python 处理为 Markdown
    """
    # 打开页面，等待渲染
    page.goto(url, wait_until='domcontentloaded')
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)
    try:
        page.wait_for_selector('#js_content', timeout=15000)
    except:
        pass
    page.wait_for_timeout(2000)

    # 提取标题
    title = page.evaluate("""() => {
        const s = ['h2.rich_media_title','h1.rich_media_title','#activity-name','.rich_media_title','h1'];
        for (const x of s) {
            const el = document.querySelector(x);
            if (el && el.innerText.trim()) return el.innerText.trim();
        }
        return document.title !== '微信公众平台' ? document.title : '';
    }""")
    title = re.sub(r'[\\/*?:"<>|]', '', title).strip()[:80] if title else ''

    # 第一步：JS 提取所有块级元素的 tag + innerText + 图片src
    # 不处理内联格式，避免转义冲突
    blocks_raw = page.evaluate("""() => {
        const content = document.getElementById('js_content');
        if (!content) return [];
        const skip = ['SCRIPT','STYLE','svg','path','NOSCRIPT','IFRAME'];
        const result = [];
        for (const child of content.children) {
            if (skip.includes(child.tagName)) continue;
            // 图片特殊处理：提取 data-src
            if (child.tagName === 'IMG') {
                result.push({
                    tag: 'IMG',
                    src: child.getAttribute('data-src') || child.getAttribute('src') || ''
                });
                continue;
            }
            // 容器内有图片：提取所有图片
            const imgs = child.querySelectorAll('img');
            for (const img of imgs) {
                result.push({
                    tag: 'IMG',
                    src: img.getAttribute('data-src') || img.getAttribute('src') || ''
                });
            }
            // 文本内容
            const text = child.innerText.trim();
            if (text) {
                result.push({
                    tag: child.tagName,
                    text: text,
                    html: child.innerHTML
                });
            }
        }
        return result;
    }""")

    # 找到正文边界，截断推荐区
    boundary = find_content_boundary(blocks_raw)
    content_blocks = blocks_raw[:boundary]
    promo_blocks = blocks_raw[boundary:]  # 丢弃

    if promo_blocks:
        print(f"  [截断] 丢弃推荐区 {len(promo_blocks)} 个块")

    # 第二步：Python 处理每个块，转换为 Markdown
    md_lines = []
    img_count = 0
    images_dir = os.path.join(save_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    for block in blocks_raw:
        tag = block.get('tag', '')

        # 图片块
        if tag == 'IMG':
            src = block.get('src', '')
            if not src or src.startswith('data:'):
                continue
            img_count += 1
            ext = 'jpg'
            if '.png' in src.lower(): ext = 'png'
            elif '.gif' in src.lower(): ext = 'gif'
            img_name = f"{img_count:03d}.{ext}"
            img_path = os.path.join(images_dir, img_name)

            ok = download_image(src, img_path, headers={'Referer': 'https://mp.weixin.qq.com/'})
            if ok:
                md_lines.append(f"![{img_name}](images/{img_name})")
            else:
                md_lines.append(f"![image]({src})")
            continue

        # 文本块
        text = block.get('text', '')
        html = block.get('html', '')
        if not text:
            continue

        # 标题
        if tag in ('H1', 'H2', 'H3', 'H4'):
            level = int(tag[1])
            md_lines.append(f"{'#' * level} {text}")

        # 引用
        elif tag == 'BLOCKQUOTE':
            for line in text.split('\n'):
                line = line.strip()
                if line:
                    md_lines.append(f"> {line}")

        # 代码块
        elif tag == 'PRE':
            md_lines.append("```")
            md_lines.append(text)
            md_lines.append("```")

        # 分割线
        elif tag == 'HR':
            md_lines.append("---")

        # 段落/列表/其他容器：处理内联格式
        else:
            md_text = _html_to_md_inline(html) if html else text
            md_lines.append(md_text)

    # 保存调试（如果无内容）
    if not title or not md_lines:
        debug_path = os.path.join(save_dir, "debug.html")
        os.makedirs(save_dir, exist_ok=True)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(page.content())
        print(f"  [调试] 提取失败，已保存: {debug_path}")

    # 组装 Markdown
    safe_title = title or 'untitled'
    header = f"# {safe_title}\n\n来源：{url}\n采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    md_content = header + '\n\n'.join(md_lines)
    md_content = re.sub(r'\n{3,}', '\n\n', md_content)  #  使用正则表达式将连续三个或更多的换行符替换为连续两个换行符，确保Markdown文本格式规范

    md_path = os.path.join(save_dir, "article.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    return safe_title, md_path, img_count


def _html_to_md_inline(html):
    """
    将内联 HTML 转换为 Markdown 格式
    处理：加粗、斜体、链接、代码、换行
    """
    if not html:
        return ''

    # 保护 code 标签内容（避免被其他替换干扰）
    code_map = {}
    code_idx = 0

    def save_code(m):
        nonlocal code_idx
        key = f"__CODE_{code_idx}__"
        code_idx += 1
        code_map[key] = m.group(1)
        return key

    # 1. 先提取 <code> 内容
    # 使用正则表达式替换HTML中的<code>标签内容
    # re.sub函数用于替换字符串中匹配正则表达式的部分
    # r'<code[^>]*>(.*?)</code>' 是正则表达式模式，匹配<code>标签及其内容
    #   - <code 匹配开始标签
    #   - [^>]* 匹配除>外的任意字符，即标签属性
    #   - (.*?) 匹配标签内容，非贪婪模式
    #   - </code> 匹配结束标签
    # save_code 是替换函数，处理匹配到的代码内容
    # html 是原始HTML字符串
    # flags=re.DOTALL 使.匹配包括换行符在内的所有字符
    html = re.sub(r'<code[^>]*>(.*?)</code>', save_code, html, flags=re.DOTALL) #

    # 2. 替换其他内联标签
    # 使用正则表达式将HTML中的<strong>或<b>标签转换为Markdown的**粗体**格式
    # re.sub用于替换字符串，r'<(strong|b)[^>]*>(.*?)</\1>'匹配开始标签和结束标签
    # r'**\2**'将匹配到的内容用**包围，\2表示第二个捕获组(.*?)的内容
    html = re.sub(r'<(strong)[^>]*>(.*?)</\1>', r'**\2**', html, flags=re.DOTALL)
    html = re.sub(r'<(b)[^>]*>(.*?)</\1>', r'**\2**', html, flags=re.DOTALL)
    # 使用正则表达式将HTML中的<em>或<i>标签转换为Markdown的*斜体*格式
    # r'<(em|i)[^>]*>(.*?)</\1>'匹配开始标签和结束标签
    # r'*\2*'将匹配到的内容用*包围，\2表示第二个捕获组(.*?)的内容
    html = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', html, flags=re.DOTALL)
    # 使用正则表达式将HTML中的<a>标签转换为Markdown的[链接文本](URL)格式
    # r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'匹配href属性和链接文本
    # r'[\2](\1)'将链接文本和URL转换为Markdown格式，\1是URL，\2是链接文本
    html = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r'[\2](\1)', html, flags=re.DOTALL)
    # 使用正则表达式将HTML中的<br>或<br/>标签换行符转换为\n
    # r'<br\s*/?>'匹配<br>或<br/>，\s*匹配可能的空格，?/?>匹配可选的/和>
    # '\n'将匹配到的内容替换为换行符
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)

    # 3. 去除所有剩余标签
    html = re.sub(r'<[^>]+>', '', html)

    # 4. 还原 code 内容
    for key, val in code_map.items():
        html = html.replace(key, f'`{val}`')

    # 5. 清理空白
    lines = [line.strip() for line in html.split('\n') if line.strip()]
    return ' '.join(lines) if len(lines) == 1 else '\n\n'.join(lines)   # markdown 中以两个换行为换行标识
''''''
# def download_weixin(page, url, save_dir):
#     """
#     微信公众号文章下载
#     - 模拟 iPhone 微信浏览器环境
#     - 注入反检测脚本，隐藏 webdriver 标记
#     - 多层等待确保 JS 渲染完成
#     - 按 DOM 顺序提取文本和图片
#     - 失败时保存 debug.html 供排查
#     """
#     # 打开页面，先等基础 DOM 加载
#     page.goto(url, wait_until='domcontentloaded')
#
#     # 注入反检测脚本：隐藏 navigator.webdriver，伪造 chrome 对象
#     page.add_init_script('''
#         Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
#         Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
#         window.chrome = { runtime: {} };
#     ''')
#
#     # 等待标题元素出现（最多15秒）
#     try:
#         page.wait_for_selector(
#             'h2.rich_media_title, h1.rich_media_title, #activity-name, .rich_media_title',
#             timeout=15000
#         )
#     except Exception:
#         print("  [警告] 等待标题元素超时，尝试继续...")
#
#     # 等待正文容器出现
#     try:
#         page.wait_for_selector('#js_content', timeout=15000)
#     except Exception:
#         print("  [警告] 等待正文元素超时，尝试继续...")
#
#     # 等待网络空闲，确保 JS 渲染完成
#     try:
#         page.wait_for_load_state('networkidle', timeout=10000)
#     except Exception:
#         pass
#
#     # 额外强制等待2秒（微信有时懒加载）
#     page.wait_for_timeout(2000)
#
#     # 提取标题：多种选择器 fallback
#     title = page.evaluate('''() => {
#         const selectors = [
#             'h2.rich_media_title',
#             'h1.rich_media_title',
#             '#activity-name',
#             '.rich_media_title',
#             '#js_activity_name',
#             'h1'
#         ];
#         for (const s of selectors) {
#             const el = document.querySelector(s);
#             if (el && el.innerText && el.innerText.trim().length > 0) {
#                 return el.innerText.trim();
#             }
#         }
#         // 兜底：document.title
#         const t = document.title;
#         if (t && t !== '微信公众平台' && t !== '微信') return t;
#         return '';
#     }''')
#
#     title = re.sub(r'[\\/*?:"<>|]', '', title).strip()[:80] if title else ''
#
#     # 提取正文：按 DOM 顺序遍历 #js_content
#     items = page.evaluate('''() => {
#         const content = document.getElementById('js_content');
#         if (!content) return [];
#
#         // 检查是否有实质内容
#         const innerText = content.innerText || '';
#         if (innerText.trim().length < 5) return [];
#
#         const items = [];
#         const skipTags = ['SCRIPT', 'STYLE', 'svg', 'path', 'NOSCRIPT'];
#
#         const walk = (node) => {
#             if (node.nodeType === 3) { // TEXT_NODE
#                 const text = node.textContent.trim();
#                 if (text) items.push({type: 'text', content: text});
#             } else if (node.nodeType === 1 && node.tagName === 'IMG') {
#                 const src = node.getAttribute('data-src') || node.getAttribute('src');
#                 if (src && !src.startsWith('data:')) {
#                     items.push({type: 'image', src: src});
#                 }
#             } else if (node.nodeType === 1 && !skipTags.includes(node.tagName)) {
#                 for (const child of node.childNodes) walk(child);
#             }
#         };
#         walk(content);
#         return items;
#     }''')
#
#     # 如果标题或正文为空，保存调试快照
#     if not title or not items:
#         debug_path = os.path.join(save_dir, "debug.html")
#         os.makedirs(save_dir, exist_ok=True)
#         html = page.content()
#         with open(debug_path, 'w', encoding='utf-8') as f:
#             f.write(html)
#         print(f"  [调试] 提取失败，已保存页面快照: {debug_path}")
#         print(f"  [调试] 标题='{title}', 正文条目数={len(items)}")
#
#     # 生成 Markdown 文件
#     safe_title = title or 'untitled'
#     md_lines = [
#         f"# {safe_title}",
#         f"\n来源：{url}",
#         f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
#     ]
#
#     img_count = 0
#     images_dir = os.path.join(save_dir, "images")
#     os.makedirs(images_dir, exist_ok=True)
#
#     for item in items:
#         if item['type'] == 'text':
#             md_lines.append(item['content'])
#         elif item['type'] == 'image':
#             src = item['src']
#             img_count += 1
#             ext = 'jpg'
#             if '.png' in src.lower():
#                 ext = 'png'
#             elif '.gif' in src.lower():
#                 ext = 'gif'
#             elif '.jpeg' in src.lower():
#                 ext = 'jpeg'
#             img_name = f"{img_count:03d}.{ext}"
#             img_path = os.path.join(images_dir, img_name)
#
#             # 微信图片必须带 Referer 防盗链
#             ok = download_image(src, img_path, headers={'Referer': 'https://mp.weixin.qq.com/'})
#             if ok:
#                 md_lines.append(f"\n![{img_name}](images/{img_name})\n")
#             else:
#                 md_lines.append(f"\n![image]({src})\n")
#
#     md_content = '\n'.join(md_lines)
#     md_content = re.sub(r'\n{3,}', '\n\n', md_content)
#
#     md_path = os.path.join(save_dir, "article.md")
#     with open(md_path, 'w', encoding='utf-8') as f:
#         f.write(md_content)
#
#     return safe_title, md_path, img_count



# def download_weixin(page, url, save_dir):
#     """
#     微信公众号文章下载（格式保留版）
#     - 模拟 iPhone 微信浏览器环境
#     - 注入反检测脚本
#     - 多层等待确保 JS 渲染完成
#     - 保留原文格式：段落、标题、列表、引用、加粗、链接、代码块
#     """
#     # 打开页面，先等基础 DOM 加载
#     page.goto(url, wait_until='domcontentloaded')
#
#     # 注入反检测脚本
#     page.add_init_script('''
#         Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
#         Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
#         window.chrome = { runtime: {} };
#     ''')
#
#     # 等待标题元素出现（最多15秒）
#     try:
#         page.wait_for_selector(
#             'h2.rich_media_title, h1.rich_media_title, #activity-name, .rich_media_title',
#             timeout=15000
#         )
#     except Exception:
#         print("  [警告] 等待标题元素超时，尝试继续...")
#
#     # 等待正文容器出现
#     try:
#         page.wait_for_selector('#js_content', timeout=15000)
#     except Exception:
#         print("  [警告] 等待正文元素超时，尝试继续...")
#
#     # 等待网络空闲
#     try:
#         page.wait_for_load_state('networkidle', timeout=10000)
#     except Exception:
#         pass
#
#     # 额外强制等待2秒
#     page.wait_for_timeout(2000)
#
#     # 提取标题
#     title = page.evaluate('''() => {
#         const selectors = [
#             'h2.rich_media_title',
#             'h1.rich_media_title',
#             '#activity-name',
#             '.rich_media_title',
#             '#js_activity_name',
#             'h1'
#         ];
#         for (const s of selectors) {
#             const el = document.querySelector(s);
#             if (el && el.innerText && el.innerText.trim().length > 0) {
#                 return el.innerText.trim();
#             }
#         }
#         const t = document.title;
#         if (t && t !== '微信公众平台' && t !== '微信') return t;
#         return '';
#     }''')
#
#     title = re.sub(r'[\\/*?:"<>|]', '', title).strip()[:80] if title else ''
#
#     # 提取正文：保留格式的结构化遍历
#     # 返回的是 Markdown 行列表，每个元素是 {type, content}
#     blocks = page.evaluate('''() => {
#         const content = document.getElementById('js_content');
#         if (!content) return [];
#
#         const innerText = content.innerText || '';
#         if (innerText.trim().length < 5) return [];
#
#         const blocks = [];
#         const skipTags = ['SCRIPT', 'STYLE', 'svg', 'path', 'NOSCRIPT', 'IFRAME'];
#
#         // 处理内联样式（加粗、斜体、链接、代码）
#         const processInline = (node) => {
#             let result = '';
#             for (const child of node.childNodes) {
#                 if (child.nodeType === 3) {
#                     result += child.textContent;
#                 } else if (child.nodeType === 1) {
#                     const tag = child.tagName;
#                     const text = processInline(child);
#                     if (tag === 'STRONG' || tag === 'B') {
#                         result += '**' + text + '**';
#                     } else if (tag === 'EM' || tag === 'I') {
#                         result += '*' + text + '*';
#                     } else if (tag === 'A') {
#                         const href = child.getAttribute('href') || '';
#                         result += '[' + text + '](' + href + ')';
#                     } else if (tag === 'CODE') {
#                         result += '`' + text + '`';
#                     } else if (tag === 'BR') {
#                         result += '\n';
#                     } else if (tag === 'SPAN' || tag === 'LABEL') {
#                         result += text;
#                     } else {
#                         result += text;
#                     }
#                 }
#             }
#             return result;
#         };
#
#         // 处理块级元素
#         const processBlock = (node, listLevel = 0) => {
#             if (node.nodeType === 3) {
#                 const text = node.textContent.trim();
#                 if (text) {
#                     blocks.push({type: 'text', content: text});
#                 }
#                 return;
#             }
#
#             if (node.nodeType !== 1) return;
#             const tag = node.tagName;
#
#             if (skipTags.includes(tag)) return;
#
#             // 标题
#             if (tag === 'H1' || tag === 'H2' || tag === 'H3' || tag === 'H4') {
#                 const level = parseInt(tag[1]);
#                 const text = processInline(node).trim();
#                 if (text) {
#                     blocks.push({type: 'heading', level: level, content: text});
#                 }
#                 return;
#             }
#
#             // 段落
#             if (tag === 'P') {
#                 const text = processInline(node).trim();
#                 if (text) {
#                     blocks.push({type: 'paragraph', content: text});
#                 }
#                 return;
#             }
#
#             // 引用块
#             if (tag === 'BLOCKQUOTE') {
#                 const text = processInline(node).trim();
#                 if (text) {
#                     // 引用块内的内容按行处理，每行前加 >
#                     const lines = text.split('\\n').filter(l => l.trim());
#                     for (const line of lines) {
#                         blocks.push({type: 'quote', content: line.trim()});
#                     }
#                 }
#                 return;
#             }
#
#             // 无序列表
#             if (tag === 'UL') {
#                 for (const li of node.querySelectorAll(':scope > li')) {
#                     const text = processInline(li).trim();
#                     if (text) {
#                         blocks.push({type: 'ul_item', content: text});
#                     }
#                 }
#                 return;
#             }
#
#             // 有序列表
#             if (tag === 'OL') {
#                 let num = 1;
#                 for (const li of node.querySelectorAll(':scope > li')) {
#                     const text = processInline(li).trim();
#                     if (text) {
#                         blocks.push({type: 'ol_item', num: num++, content: text});
#                     }
#                 }
#                 return;
#             }
#
#             // 代码块
#             if (tag === 'PRE') {
#                 const code = node.querySelector('code');
#                 const text = code ? code.innerText : node.innerText;
#                 if (text.trim()) {
#                     blocks.push({type: 'code', content: text.trim()});
#                 }
#                 return;
#             }
#
#             // 分割线
#             if (tag === 'HR') {
#                 blocks.push({type: 'hr'});
#                 return;
#             }
#
#             // 图片
#             if (tag === 'IMG') {
#                 const src = node.getAttribute('data-src') || node.getAttribute('src');
#                 if (src && !src.startsWith('data:')) {
#                     blocks.push({type: 'image', src: src});
#                 }
#                 return;
#             }
#
#             // section/div 等容器：递归处理子元素
#             for (const child of node.children) {
#                 processBlock(child, listLevel);
#             }
#         };
#
#         // 从 #js_content 的直接子元素开始处理
#         for (const child of content.children) {
#             processBlock(child);
#         }
#
#         return blocks;
#     }''')
#
#     # 如果提取失败，保存调试 HTML
#     if not title or not blocks:
#         debug_path = os.path.join(save_dir, "debug.html")
#         os.makedirs(save_dir, exist_ok=True)
#         html = page.content()
#         with open(debug_path, 'w', encoding='utf-8') as f:
#             f.write(html)
#         print(f"  [调试] 提取失败，已保存页面快照: {debug_path}")
#         print(f"  [调试] 标题='{title}', 正文块数={len(blocks)}")
#
#     # 生成 Markdown
#     safe_title = title or 'untitled'
#     md_lines = [
#         f"# {safe_title}",
#         f"\n来源：{url}",
#         f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
#     ]
#
#     img_count = 0
#     images_dir = os.path.join(save_dir, "images")
#     os.makedirs(images_dir, exist_ok=True)
#
#     for block in blocks:
#         btype = block['type']
#
#         if btype == 'heading':
#             md_lines.append(f"\n{'#' * block['level']} {block['content']}\n")
#
#         elif btype == 'paragraph':
#             md_lines.append(f"\n{block['content']}\n")
#
#         elif btype == 'quote':
#             md_lines.append(f"\n> {block['content']}\n")
#
#         elif btype == 'ul_item':
#             md_lines.append(f"\n- {block['content']}\n")
#
#         elif btype == 'ol_item':
#             md_lines.append(f"\n{block['num']}. {block['content']}\n")
#
#         elif btype == 'code':
#             md_lines.append(f"\n```\n{block['content']}\n```\n")
#
#         elif btype == 'hr':
#             md_lines.append(f"\n---\n")
#
#         elif btype == 'image':
#             src = block['src']
#             img_count += 1
#             ext = 'jpg'
#             if '.png' in src.lower():
#                 ext = 'png'
#             elif '.gif' in src.lower():
#                 ext = 'gif'
#             elif '.jpeg' in src.lower():
#                 ext = 'jpeg'
#             img_name = f"{img_count:03d}.{ext}"
#             img_path = os.path.join(images_dir, img_name)
#
#             ok = download_image(src, img_path, headers={'Referer': 'https://mp.weixin.qq.com/'})
#             if ok:
#                 md_lines.append(f"\n![{img_name}](images/{img_name})\n")
#             else:
#                 md_lines.append(f"\n![image]({src})\n")
#
#         elif btype == 'text':
#             # 兜底文本块
#             md_lines.append(f"\n{block['content']}\n")
#
#     # 清理多余空行
#     md_content = '\n'.join(md_lines)
#     md_content = re.sub(r'\n{3,}', '\n\n', md_content)
#
#     md_path = os.path.join(save_dir, "article.md")
#     with open(md_path, 'w', encoding='utf-8') as f:
#         f.write(md_content)
#
#     return safe_title, md_path, img_count
''''''
# ==================== 通用网页下载 ====================
def download_generic(page, url, save_dir):
    """
    CSDN、知乎等通用网页下载函数
    该函数用于从网页中提取标题和正文内容，并下载相关图片，最终生成Markdown格式的文章
    参数:
        page: Playwright页面对象，用于操作浏览器
        url: 要下载的网页URL
        save_dir: 文章保存的目录路径
    返回:
        tuple: 包含(标题, Markdown文件路径, 图片数量)的元组
    功能特点:
    - 优先提取 article / .post-content / .blog-content-box 等正文区域
    - 回退到 body 全内容
    - 图片处理相对路径和绝对路径
    """
    page.goto(url, wait_until='networkidle')

    # 提取标题
    title = page.evaluate('''() => {
        const h1 = document.querySelector('h1');
        return h1 ? h1.innerText.trim() : document.title;
    }''')
    title = re.sub(r'[\\/*?:"<>|]', '', title).strip()[:80] or 'untitled'

    # 提取正文：按优先级选择容器
    items = page.evaluate('''() => {
        const selectors = [
            'article', '.post-content', '.blog-content-box',
            '#content_views', '.article-content', 'main'
        ];
        let node = null;
        for (const s of selectors) {
            node = document.querySelector(s);
            if (node) break;
        }
        if (!node) node = document.body;

        const items = [];
        const skipTags = ['SCRIPT','STYLE','NAV','HEADER','FOOTER','ASIDE','svg'];
        const walk = (n) => {
            if (n.nodeType === 3) {
                const text = n.textContent.trim();
                if (text) items.push({type: 'text', content: text});
            } else if (n.nodeType === 1 && n.tagName === 'IMG') {
                let src = n.getAttribute('data-src') || n.getAttribute('src');
                if (src && !src.startsWith('data:')) items.push({type: 'image', src: src});
            } else if (n.nodeType === 1 && !skipTags.includes(n.tagName)) {
                for (const c of n.childNodes) walk(c);
            }
        };
        walk(node);
        return items;
    }''')

    md_lines = [f"# {title}", f"\n来源：{url}", f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    img_count = 0
    os.makedirs(os.path.join(save_dir, "images"), exist_ok=True)

    for item in items:
        if item['type'] == 'text':
            md_lines.append(item['content'])
        elif item['type'] == 'image':
            src = item['src']
            # 处理协议相对路径和根相对路径
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = urljoin(url, src)
            img_count += 1
            ext = 'jpg'
            if '.png' in src.lower():
                ext = 'png'
            elif '.gif' in src.lower():
                ext = 'gif'
            img_name = f"{img_count:03d}.{ext}"
            img_path = os.path.join(save_dir, "images", img_name)
            ok = download_image(src, img_path)
            if ok:
                md_lines.append(f"\n![{img_name}](images/{img_name})\n")
            else:
                md_lines.append(f"\n![image]({src})\n")

    md_content = '\n'.join(md_lines)
    md_content = re.sub(r'\n{3,}', '\n\n', md_content)

    md_path = os.path.join(save_dir, "article.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    return title, md_path, img_count


# ==================== 自动打标签 ====================
def auto_tag_article(conn, article_id, article_title, label_code='H01'):
    """
    为文章自动打标签
    - 默认打 H01（待分类），后续接入 AI 分类替换此逻辑
    - 同步写入冗余字段 article 和 label，加速查询
    """
    c = conn.cursor()

    # 查询标签 ID 和名称
    c.execute("SELECT id, label FROM labels WHERE code = ?", (label_code,))
    row = c.fetchone()
    if not row:
        print(f"  [标签] 标签 {label_code} 不存在，跳过")
        return

    label_id, label_name = row

    # 插入关联记录（UNIQUE约束防止重复）
    try:
        c.execute('''
            INSERT INTO article_labels (article_id, label_id, article, label)
            VALUES (?, ?, ?, ?)
        ''', (article_id, label_id, article_title, label_name))
        print(f"  [标签] 已打标签: {label_code} ({label_name})")
    except sqlite3.IntegrityError:
        # 重复关联，忽略
        pass

    conn.commit()


# ==================== 单条 URL 处理主流程 ====================
def process_single_url(url, browser):
    """
    处理单个 URL 的完整流程：
    1. 检查是否已收录（URL 唯一约束）
    2. 插入文章记录（获取 article_id）
    3. 调用对应下载器（微信/通用）
    4. 更新文章标题和本地路径
    5. 自动打标签（默认 H01 待分类）
    """
    conn = sqlite3.connect(DB_PATH)

    # 检查是否已收录
    c = conn.cursor()
    c.execute("SELECT id FROM articles WHERE url = ? and status = 1", (url,))   #已经下载成功的
    row = c.fetchone()
    if row:
        print(f"[跳过] 已收录: {url[:60]}...")
        conn.close()
        return

    tmp_status = -1   # -1 无记录， 0 下载失败， 1，下载成功
    c.execute("SELECT id FROM articles WHERE url = ?", (url,))   #下载失败的
    row = c.fetchone()
    if row:
        tmp_status = 0
        print(f"【提示】之前有记录但是下载失败，重新下载")
        article_id = row[0]
        # print(f"[跳过] 已收录: {url[:60]}...")
        # conn.close()
        # return


    # 插入文章记录，获取自增 ID
    now = datetime.now().isoformat()
    if tmp_status == -1:
        c.execute('''
            INSERT INTO articles (url, title, local_path, created_at, source, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (url, None, None, now, classify_url(url), 0))  # 开始的记录为零
        article_id = c.lastrowid  # 将最后插入行的ID赋值给article_id变量
    elif tmp_status == 0:
        c.execute('''
            UPDATE articles 
            SET title=?, local_path=?, created_at=?, source=?, status=? 
            WHERE id=?
        ''', (None, None, now, classify_url(url), 0, article_id))

    conn.commit()
    # 获取最后插入行的ID

    # 准备本地保存目录
    date_dir = datetime.now().strftime('%Y-%m-%d')
    source = classify_url(url)
    output_base = os.path.join(WORKSPACE, "output", source, date_dir)
    os.makedirs(output_base, exist_ok=True)

    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    temp_dir = os.path.join(output_base, f"tmp_{url_hash}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # 根据来源选择下载器
        if source == 'weixin':
            page = browser.new_page(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
                           'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                           'Mobile/15E148 MicroMessenger/8.0.38(0x18002628) '
                           'NetType/WIFI Language/zh_CN',
                viewport={'width': 375, 'height': 812}
            )
            title, md_path, img_count = download_weixin(page, url, temp_dir)
            page.close()
        else:
            page = browser.new_page()
            title, md_path, img_count = download_generic(page, url, temp_dir)
            page.close()

        # 重命名临时目录为文章标题
        safe_title = re.sub(r'[\\/*?:"<>|]', '', title).strip()[:60]
        final_dir = os.path.join(output_base, safe_title)
        if os.path.exists(final_dir) and final_dir != temp_dir:
            final_dir = f"{final_dir}_{url_hash}"
        if final_dir != temp_dir:
            os.rename(temp_dir, final_dir)

        # 更新文章记录：标题和本地路径
        c.execute('''
            UPDATE articles SET title = ?, local_path = ?, status = ? WHERE id = ?
        ''', (title, final_dir, 1, article_id))
        conn.commit()

        # 自动打标签（默认 H01 待分类）
        auto_tag_article(conn, article_id, title, 'H01')

        print(f"[完成] {title} ({img_count}张图片) -> {final_dir}")

    except Exception as e:
        err_msg = str(e)
        print(f"[失败] {url[:60]}... 原因: {err_msg}")
        # 失败时保留记录，但 title 和 local_path 为空，可后续重试
    finally:
        conn.close()


# ==================== 主循环 ====================
def main_loop():
    """
    程序入口：初始化数据库，启动浏览器，循环扫描 inbox 队列
    """
    init_storage()
    print("=" * 50)
    print("采集处理程序已启动（v2.0）")
    print(f"工作目录: {WORKSPACE}")
    print(f"扫描间隔: 30 秒")
    print("=" * 50)

    with sync_playwright() as p:
        # 启动 Chromium，添加反检测参数
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-dev-shm-usage'
            ]
        )

        try:
            while True:
                # 检查队列文件是否有内容
                if os.path.exists(INBOX_FILE) and os.path.getsize(INBOX_FILE) > 0:
                    # 原子移动：避免与 server.py 写入冲突
                    processing = f"{INBOX_FILE}.{uuid.uuid4().hex[:8]}.tmp"
                    try:
                        os.rename(INBOX_FILE, processing)
                    except Exception as e:
                        print(f"读取队列文件失败: {e}")
                        time.sleep(60)
                        continue

                    # 读取所有 URL
                    with open(processing, 'r', encoding='utf-8') as f:
                        lines = f.readlines()

                    # 删除临时文件
                    try:
                        os.remove(processing)
                    except:
                        pass

                    # 逐条处理
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split(' | ', 1)
                        url = parts[1] if len(parts) > 1 else line
                        if url.startswith('http'):
                            print(f"\n[处理] {url}")
                            process_single_url(url, browser)

                # 等待下一轮扫描
                time.sleep(30)

        except KeyboardInterrupt:
            print("\n用户中断，正在关闭浏览器...")
        finally:
            browser.close()
            print("已退出")


if __name__ == '__main__':
    main_loop()