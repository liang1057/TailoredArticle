import re

# 在文件顶部添加配置（可扩展）
# 推荐区黑名单关键词（大小写不敏感）
PROMO_KEYWORDS = [
    '扫码', '关注', '加好友', '觉得好看', '点这里', '联系我们',
    '转载请联系', '来源：', '本期编辑', 'END', '历史文章',
    '推荐阅读', '相关文章', '精选内容', '点击在看', '分享朋友圈',
    '原文链接', '阅读原文', '加入群', '获取资料', '免费领取'
]

# 推荐区判定阈值
PROMO_MIN_LEN = 20          # 段落长度低于此值视为短段落
PROMO_LINK_RATIO = 0.5      # 链接占比超过此值视为推荐区
PROMO_WINDOW_SIZE = 3       # 滑动窗口大小（连续几个段落）
PROMO_KEYWORD_MATCH = 1     # 窗口内出现几个关键词即触发截断


def is_promo_block(text, html):
    """
    判断单个文本块是否属于推荐区
    返回：True=是推荐内容，False=可能是正文
    """
    if not text:
        return True  # 空块视为推荐区

    text_stripped = text.strip()

    # 1. 黑名单关键词匹配
    text_lower = text_stripped.lower()
    for kw in PROMO_KEYWORDS:
        if kw in text_lower:
            return True

    # 2. 超短段落（且包含链接或图片）
    if len(text_stripped) < PROMO_MIN_LEN:
        # 检查是否包含链接或图片标签
        has_link = '<a ' in (html or '') or 'href=' in (html or '')
        has_img = '<img' in (html or '')
        if has_link or has_img:
            return True

    # 3. 纯链接段落（文本就是链接文本）
    link_pattern = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or '', re.DOTALL)
    if link_pattern and len(text_stripped) < 50:
        # 如果段落全是链接，且链接文本占比高
        link_text_len = sum(len(t[1]) for t in link_pattern)
        if link_text_len / max(len(text_stripped), 1) > PROMO_LINK_RATIO:
            return True

    return False


def find_content_boundary(blocks):
    """
    从底部向上扫描，找到正文与推荐区的边界
    blocks: 列表，每个元素是 {tag, text, html, src}
    返回：截断索引（保留此索引之前的所有内容）
    """
    if not blocks:
        return 0

    n = len(blocks)
    # 从底部开始，维护滑动窗口
    for i in range(n - 1, -1, -1):
        # 检查从 i 到末尾的窗口
        window = blocks[i:min(i + PROMO_WINDOW_SIZE, n)]

        # 统计窗口内推荐特征
        promo_count = 0
        for block in window:
            if block.get('tag') == 'IMG':
                # 图片块：如果是二维码或动图（通过尺寸或文件名判断），视为推荐
                src = block.get('src', '')
                if 'qr' in src.lower() or 'qrcode' in src.lower() or 'gif' in src.lower():
                    promo_count += 1
            else:
                # 文本块
                if is_promo_block(block.get('text', ''), block.get('html', '')):
                    promo_count += 1

        # 窗口内大部分块都是推荐内容，且连续出现
        if promo_count >= PROMO_KEYWORD_MATCH and promo_count >= len(window) * 0.5:
            # 继续向上扩展，找到推荐区的起始边界
            boundary = i
            while boundary > 0:
                prev_block = blocks[boundary - 1]
                if prev_block.get('tag') == 'IMG':
                    src = prev_block.get('src', '')
                    if 'qr' in src.lower() or 'qrcode' in src.lower() or 'gif' in src.lower():
                        boundary -= 1
                        continue
                if is_promo_block(prev_block.get('text', ''), prev_block.get('html', '')):
                    boundary -= 1
                    continue
                break
            return boundary

    # 未找到推荐区，保留全部
    return n