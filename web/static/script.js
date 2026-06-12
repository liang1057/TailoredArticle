/**
 * read 应用前端逻辑 v2.0
 * - 三栏布局 + 可拖拽分割线
 * - 标签树渲染与多选（OR/并集查询）
 * - 文章列表：标题行 + 元信息行 + 操作行
 * - 右侧边栏：点击「摘要」按钮显示文章详情
 */

// ===== 状态 =====
let selectedTagIds = new Set();  // 当前选中的标签ID
let currentQuery = '';            // 当前搜索关键词
let allLabels = [];               // 缓存所有标签
let currentArticles = [];         // 缓存当前文章列表

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    loadLabels();
    loadArticles();
    bindEvents();
    initResizers();
});

// ===== 事件绑定 =====
function bindEvents() {
    // 清空标签
    document.getElementById('clear-tags').addEventListener('click', () => {
        selectedTagIds.clear();
        document.querySelectorAll('.label-checkbox input').forEach(cb => cb.checked = false);
        updateSelectedTags();
        loadArticles();
    });

    // 搜索框输入（防抖）
    let searchTimer;
    document.getElementById('search-input').addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            currentQuery = e.target.value.trim();
            loadArticles();
        }, 300);
    });
}

// ===== 拖拽分割线初始化 =====
function initResizers() {
    const app = document.getElementById('app');
    const sidebar = document.getElementById('sidebar');
    const main = document.getElementById('main');
    const sidebarRight = document.getElementById('sidebar-right');
    const resizerLeft = document.getElementById('resizer-left');
    const resizerRight = document.getElementById('resizer-right');

    // 左分割线：调整 sidebar 和 main
    initResizer(resizerLeft, sidebar, main, 'left');
    // 右分割线：调整 main 和 sidebarRight
    initResizer(resizerRight, main, sidebarRight, 'right');
}

function initResizer(resizer, panelBefore, panelAfter, side) {
    let isResizing = false;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        resizer.classList.add('resizing');

        const startX = e.clientX;
        const startWidthBefore = panelBefore.offsetWidth;
        const startWidthAfter = panelAfter.offsetWidth;
        const containerWidth = document.getElementById('app').offsetWidth;

        function onMouseMove(e) {
            if (!isResizing) return;
            const dx = e.clientX - startX;

            if (side === 'left') {
                // 左分割线：调整 sidebar 宽度，main 自适应
                let newWidth = startWidthBefore + dx;
                newWidth = Math.max(180, Math.min(newWidth, containerWidth * 0.4));
                panelBefore.style.width = newWidth + 'px';
                panelBefore.style.flex = 'none';
            } else {
                // 右分割线：调整 sidebarRight 宽度，main 自适应
                let newWidth = startWidthAfter - dx;
                newWidth = Math.max(180, Math.min(newWidth, containerWidth * 0.4));
                panelAfter.style.width = newWidth + 'px';
                panelAfter.style.flex = 'none';
            }
        }

        function onMouseUp() {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        }

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// ===== 加载标签树 =====
async function loadLabels() {
    try {
        const res = await fetch('/api/labels');
        allLabels = await res.json();
        renderLabelTree(allLabels);
    } catch (e) {
        console.error('加载标签失败:', e);
    }
}

// ===== 渲染标签树 =====
function renderLabelTree(labels) {
    const container = document.getElementById('label-tree');
    container.innerHTML = '';

    labels.forEach(group => {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'label-group';

        // 一级标签头部（可展开）
        const header = document.createElement('div');
        header.className = 'label-group-header';
        header.innerHTML = `
            <span class="toggle-icon">▶</span>
            <span>${group.label}</span>
        `;
        header.addEventListener('click', () => toggleGroup(header, childrenDiv));

        // 二级标签容器（默认隐藏）
        const childrenDiv = document.createElement('div');
        childrenDiv.className = 'label-children hidden';

        group.children.forEach(child => {
            const labelDiv = document.createElement('label');
            labelDiv.className = 'label-checkbox';
            labelDiv.innerHTML = `
                <input type="checkbox" value="${child.id}" data-code="${child.code}">
                <span>${child.label}</span>
            `;
            labelDiv.querySelector('input').addEventListener('change', (e) => {
                if (e.target.checked) {
                    selectedTagIds.add(parseInt(e.target.value));
                } else {
                    selectedTagIds.delete(parseInt(e.target.value));
                }
                updateSelectedTags();
                loadArticles();
            });
            childrenDiv.appendChild(labelDiv);
        });

        groupDiv.appendChild(header);
        groupDiv.appendChild(childrenDiv);
        container.appendChild(groupDiv);
    });
}

// ===== 展开/收起标签组 =====
function toggleGroup(header, childrenDiv) {
    const icon = header.querySelector('.toggle-icon');
    const isExpanded = icon.classList.contains('expanded');

    if (isExpanded) {
        icon.classList.remove('expanded');
        childrenDiv.classList.add('hidden');
    } else {
        icon.classList.add('expanded');
        childrenDiv.classList.remove('hidden');
    }
}

// ===== 更新已选标签显示 =====
function updateSelectedTags() {
    const container = document.getElementById('selected-tags');
    container.innerHTML = '';

    const selectedTags = [];
    allLabels.forEach(group => {
        group.children.forEach(child => {
            if (selectedTagIds.has(child.id)) {
                selectedTags.push(child);
            }
        });
    });

    selectedTags.forEach(tag => {
        const pill = document.createElement('span');
        pill.className = 'tag-pill';
        pill.innerHTML = `${tag.label} ✕`;
        pill.addEventListener('click', () => {
            selectedTagIds.delete(tag.id);
            const cb = document.querySelector(`.label-checkbox input[value="${tag.id}"]`);
            if (cb) cb.checked = false;
            updateSelectedTags();
            loadArticles();
        });
        container.appendChild(pill);
    });
}

// ===== 加载文章列表 =====
async function loadArticles() {
    try {
        const params = new URLSearchParams();
        if (selectedTagIds.size > 0) {
            params.append('tags', Array.from(selectedTagIds).join(','));
        }
        if (currentQuery) {
            params.append('q', currentQuery);
        }

        const url = params.toString() ? `/api/articles?${params}` : '/api/articles';
        const res = await fetch(url);
        const articles = await res.json();
        currentArticles = articles;

        document.getElementById('article-count').textContent = `共 ${articles.length} 篇`;

        const list = document.getElementById('article-list');
        list.innerHTML = '';

        if (articles.length === 0) {
            list.innerHTML = '<div style="text-align:center;color:#999;padding:40px;">暂无文章</div>';
            return;
        }

        articles.forEach(article => {
            const item = document.createElement('div');
            item.className = 'article-item';
            item.dataset.id = article.id;

            // 解析关键词（逗号分隔，最多显示5个）
            const keywords = (article.keywords || '').split(',').filter(k => k.trim()).slice(0, 5);

            // 构建文章控件 HTML
            item.innerHTML = `
                <div class="article-item-inner">
                    <!-- 第一行：标题 + 摘要按钮 -->
                    <div class="article-title-row">
                        <div class="article-title-text">${escapeHtml(article.title)}</div>
                        <button class="btn-summary" data-id="${article.id}">摘要</button>
                    </div>
                    <!-- 第二行：关键词(左) + 分类标签(右) -->
                    <div class="article-tags-row">
                        <div class="article-keywords-inline">
                            ${keywords.map(k => `<span class="keyword-tag-inline">${escapeHtml(k.trim())}</span>`).join('')}
                        </div>
                        <div class="article-cat-tags">
                            ${article.tags.map(t => `<span class="cat-tag">${t.label}</span>`).join('')}
                        </div>
                    </div>
                    <!-- 第三行：来源日期(左) + 原文链接(右) -->
                    <div class="article-meta-row-bottom">
                        <div class="article-meta-left">
                            <span class="article-source">来源: ${article.source || '未知'}</span>
                            <span class="article-date">${formatDate(article.created_at)}</span>
                        </div>
                        <a href="${article.url}" target="_blank" class="article-link" onclick="event.stopPropagation()">原文链接</a>
                    </div>
                </div>
            `;

            // 点击标题：在新窗口打开文章阅读页
            const titleEl = item.querySelector('.article-title-text');
            titleEl.addEventListener('click', (e) => {
                e.stopPropagation();
                window.open(`/article/${article.id}`, '_blank');
            });

            // 点击「摘要」按钮：在右侧边栏显示摘要
            const summaryBtn = item.querySelector('.btn-summary');
            summaryBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                showArticleDetail(article.id);
            });

            list.appendChild(item);
        });
    } catch (e) {
        console.error('加载文章失败:', e);
    }
}

// ===== 在右侧边栏显示文章详情 =====
function showArticleDetail(articleId) {
    const article = currentArticles.find(a => a.id === articleId);
    if (!article) return;

    const container = document.getElementById('article-detail');

    // 解析关键词
    const keywords = (article.keywords || '').split(',').filter(k => k.trim());

    container.innerHTML = `
        <div class="detail-content">
            <div class="detail-title">${escapeHtml(article.title)}</div>
            <div class="detail-meta">
                <span>来源: ${article.source || '未知'}</span>
                <span>${formatDate(article.created_at)}</span>
            </div>
            <div class="detail-keywords">
                ${keywords.map(k => `<span class="detail-keyword">${escapeHtml(k.trim())}</span>`).join('')}
            </div>
            <div class="detail-tags">
                ${article.tags.map(t => `<span class="detail-tag">${t.label}</span>`).join('')}
            </div>
            <div class="detail-summary">
                <div class="detail-summary-label">摘要</div>
                <div class="detail-summary-text">${escapeHtml(article.summary || '暂无摘要')}</div>
            </div>
            <div class="detail-actions">
                <a href="${article.url}" target="_blank" class="detail-link">查看原文 ↗</a>
                <a href="/article/${article.id}" target="_blank" class="detail-link">阅读全文 ↗</a>
            </div>
        </div>
    `;
}

// ===== 工具函数 =====
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    return `${d.getFullYear()}-${(d.getMonth()+1).toString().padStart(2,'0')}-${d.getDate().toString().padStart(2,'0')}`;
}