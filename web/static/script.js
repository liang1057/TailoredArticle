/**
 * read 应用前端逻辑 v3.0
 * - 三栏布局 + 可拖拽分割线
 * - 标签树渲染与多选（OR/并集查询）
 * - 文章列表：标题行 + 元信息行 + 操作行
 * - 右侧边栏：点击「摘要」按钮显示文章详情
 * - 删除功能
 */

// ===== 状态 =====
let selectedTagIds = new Set();
let currentQuery = '';
let allLabels = [];
let currentArticles = [];
let authToken = '';  // 从 URL 提取的 token

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    // 从 URL 提取 token，后续所有请求都带上
    const urlParams = new URLSearchParams(window.location.search);
    authToken = urlParams.get('token') || '';

    loadLabels();
    loadArticles();
    bindEvents();
    initResizers();
});

// ===== 事件绑定 =====
function bindEvents() {
    document.getElementById('clear-tags').addEventListener('click', () => {
        selectedTagIds.clear();
        document.querySelectorAll('.label-checkbox input').forEach(cb => cb.checked = false);
        updateSelectedTags();
        loadArticles();
    });

    let searchTimer;
    document.getElementById('search-input').addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            currentQuery = e.target.value.trim();
            loadArticles();
        }, 300);
    });
}

// ===== 带 token 的 fetch 封装 =====
function fetchWithToken(url, options = {}) {
    const sep = url.includes('?') ? '&' : '?';
    const fullUrl = `${url}${sep}token=${encodeURIComponent(authToken)}`;
    return fetch(fullUrl, options);
}

// ===== 拖拽分割线 =====
function initResizers() {
    const app = document.getElementById('app');
    const sidebar = document.getElementById('sidebar');
    const main = document.getElementById('main');
    const sidebarRight = document.getElementById('sidebar-right');
    const resizerLeft = document.getElementById('resizer-left');
    const resizerRight = document.getElementById('resizer-right');

    initResizer(resizerLeft, sidebar, main, 'left');
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
                let newWidth = startWidthBefore + dx;
                newWidth = Math.max(180, Math.min(newWidth, containerWidth * 0.4));
                panelBefore.style.width = newWidth + 'px';
                panelBefore.style.flex = 'none';
            } else {
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
        const res = await fetchWithToken('/api/labels');
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

        const header = document.createElement('div');
        header.className = 'label-group-header';
        header.innerHTML = `
            <span class="toggle-icon">▶</span>
            <span>${group.label}</span>
        `;
        header.addEventListener('click', () => toggleGroup(header, childrenDiv));

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
        const res = await fetchWithToken(url);
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

            const keywords = (article.keywords || '').split(',').filter(k => k.trim()).slice(0, 5);
            const shareId = article.share_id || '';

            item.innerHTML = `
                <div class="article-item-inner">
                    <div class="article-title-row">
                        <div class="article-title-text" data-share-id="${shareId}">${escapeHtml(article.title)}</div>
                        <button class="btn-summary" data-id="${article.id}">摘要</button>
                    </div>
                    <div class="article-tags-row">
                        <div class="article-keywords-inline">
                            ${keywords.map(k => `<span class="keyword-tag-inline">${escapeHtml(k.trim())}</span>`).join('')}
                        </div>
                        <div class="article-cat-tags">
                            ${article.tags.map(t => `<span class="cat-tag">${t.label}</span>`).join('')}
                        </div>
                    </div>
                    <div class="article-meta-row-bottom">
                        <div class="article-meta-left">
                            <span class="article-source">来源: ${article.source || '未知'}</span>
                            <span class="article-date">${formatDate(article.created_at)}</span>
                        </div>
                        <div class="article-actions">
                            <a href="${article.url}" target="_blank" class="article-link" onclick="event.stopPropagation()">原文链接</a>
                            <button class="btn-delete" data-id="${article.id}" onclick="event.stopPropagation()">删除</button>
                        </div>
                    </div>
                </div>
            `;

            // 点击标题：通过 share_id 打开文章阅读页
            const titleEl = item.querySelector('.article-title-text');
            titleEl.addEventListener('click', (e) => {
                e.stopPropagation();
                const sid = titleEl.dataset.shareId;
                if (sid) {
                    window.open(`/article/${sid}`, '_blank');
                }
            });

            // 点击「摘要」按钮
            const summaryBtn = item.querySelector('.btn-summary');
            summaryBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                showArticleDetail(article.id);
            });

            // 点击「删除」按钮
            const deleteBtn = item.querySelector('.btn-delete');
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteArticle(article.id, article.title);
            });

            list.appendChild(item);
        });
    } catch (e) {
        console.error('加载文章失败:', e);
    }
}

// ===== 删除文章 =====
async function deleteArticle(articleId, title) {
    if (!confirm(`确定删除文章「${title || '未命名'}」？\n将同时删除本地文件和关联记录。`)) {
        return;
    }
    try {
        const res = await fetchWithToken(`/api/article/${articleId}`, { method: 'DELETE' });
        if (res.ok) {
            // 从右侧边栏移除（如果当前显示的是这篇文章）
            const detail = document.getElementById('article-detail');
            if (detail.querySelector('.detail-content')) {
                const detailTitle = detail.querySelector('.detail-title');
                if (detailTitle && currentArticles.find(a => a.id === articleId)?.title === detailTitle.textContent) {
                    detail.innerHTML = '<div class="detail-placeholder">点击文章右侧「摘要」按钮查看详情</div>';
                }
            }
            loadArticles();
        } else {
            alert('删除失败');
        }
    } catch (e) {
        console.error('删除失败:', e);
        alert('删除失败');
    }
}

// ===== 在右侧边栏显示文章详情 =====
function showArticleDetail(articleId) {
    const article = currentArticles.find(a => a.id === articleId);
    if (!article) return;

    const container = document.getElementById('article-detail');
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
                <a href="/article/${article.share_id}" target="_blank" class="detail-link">阅读全文 ↗</a>
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
