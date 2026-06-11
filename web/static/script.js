/**
 * read 应用前端逻辑
 * - 标签树渲染与多选
 * - 文章列表加载与筛选（支持标签 + 搜索）
 * - 点击标题在新窗口打开独立阅读页面
 */

// ===== 状态 =====
let selectedTagIds = new Set();  // 当前选中的标签ID
let currentQuery = '';            // 当前搜索关键词
let allLabels = [];               // 缓存所有标签

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    loadLabels();
    loadArticles();
    bindEvents();
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

    // 根据ID找到对应的标签信息
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
            // 同步取消复选框
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
        // 构建请求参数
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
            item.innerHTML = `
                <div class="article-title">${escapeHtml(article.title)}</div>
                <div class="article-meta">
                    <span>来源: ${article.source || '未知'}</span>
                    <span>${formatDate(article.created_at)}</span>
                </div>
                <div class="article-tags">
                    ${article.tags.map(t => `<span class="article-tag">${t.label}</span>`).join('')}
                </div>
            `;
            // 点击标题：在新窗口打开独立阅读页面
            item.addEventListener('click', () => {
                window.open(`/article/${article.id}`, '_blank');
            });
            list.appendChild(item);
        });
    } catch (e) {
        console.error('加载文章失败:', e);
    }
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