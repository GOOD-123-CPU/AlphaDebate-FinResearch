let selectedCompanyId = '';
let selectedCompanyName = '';
let selectedFunction = '';
let reportGenerated = false;
let currentRequest = null;
let reportStream = null;
let conversationHistory = [];

document.addEventListener('DOMContentLoaded', function() {
    // 保存默认股票列表快照（供全市场搜索后恢复）
    const companyList = document.getElementById('companyList');
    if (companyList) window.__defaultCompanyListHTML = companyList.innerHTML;
    initSelectors();
    initTabs();
    initTopSearch();
    initDownloadMenu();
    populateQuickStocks();
    bindDefaultCompanyList();
    initStockSearch();
    updateGenerateButtonState();
    appendLog('页面初始化完成，请选择股票和功能后生成报告');
});

function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const navButtons = document.querySelectorAll('.nav-chip[data-nav-target]');

    function activateTab(tabId) {
        document.querySelectorAll('.tab-panel').forEach(panel => {
            panel.classList.toggle('is-active', panel.id === tabId);
        });
        tabButtons.forEach(btn => btn.classList.toggle('is-active', btn.dataset.tabTarget === tabId));
        navButtons.forEach(btn => btn.classList.toggle('is-active', btn.dataset.navTarget === tabId));
    }

    tabButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            activateTab(this.dataset.tabTarget);
        });
    });

    navButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            activateTab(this.dataset.navTarget);
        });
    });

    window.activateMainTab = activateTab;
}

function initTopSearch() {
    const topSearchInput = document.getElementById('topSearchInput');
    const topSearchBtn = document.getElementById('topSearchBtn');
    const companySearchBox = document.getElementById('companySearchBox');
    const companyDropdown = document.getElementById('companyDropdown');

    function syncSearch() {
        const value = topSearchInput.value.trim();
        companySearchBox.value = value;
        filterCompanies(value);
        companyDropdown.classList.add('active');
        activateMainTab('overviewTab');
        companySearchBox.focus();
    }

    topSearchBtn.addEventListener('click', syncSearch);
    topSearchInput.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            syncSearch();
        }
    });
}

function initDownloadMenu() {
    document.addEventListener('click', function(event) {
        const menu = document.getElementById('downloadOptions');
        const wrapper = document.querySelector('.download-menu');
        if (!menu || !wrapper) return;
        if (!wrapper.contains(event.target)) {
            menu.classList.remove('is-open');
        }
    });
}

function toggleDownloadMenu(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const menu = document.getElementById('downloadOptions');
    if (menu) {
        menu.classList.toggle('is-open');
    }
}

function initSelectors() {
    const companySearchBox = document.getElementById('companySearchBox');
    const companyDropdown = document.getElementById('companyDropdown');
    const companyListItems = document.querySelectorAll('#companyList li');
    const functionSelectBox = document.getElementById('functionSelectBox');
    const functionDropdown = document.getElementById('functionDropdown');
    const functionListItems = document.querySelectorAll('#functionList li');

    companySearchBox.addEventListener('focus', function() {
        companyDropdown.classList.add('active');
    });

    companySearchBox.addEventListener('click', function() {
        companyDropdown.classList.toggle('active');
    });

    companySearchBox.addEventListener('input', function() {
        filterCompanies(this.value);
        document.getElementById('topSearchInput').value = this.value;
    });

    companyListItems.forEach(function(item) {
        item.addEventListener('click', function() {
            selectedCompanyId = this.getAttribute('data-code');
            selectedCompanyName = this.getAttribute('data-name');
            companySearchBox.value = this.textContent;
            document.getElementById('topSearchInput').value = this.textContent;
            companyDropdown.classList.remove('active');
            highlightSelected('#companyList li', this);
            updateGenerateButtonState();
            appendLog(`已选择股票：${selectedCompanyName}（${selectedCompanyId}）`);
            updateStatus(`已选择 ${selectedCompanyName}，等待生成报告`, 'green');
        });
    });

    functionSelectBox.addEventListener('click', function() {
        functionDropdown.classList.toggle('active');
    });

    functionListItems.forEach(item => {
        item.addEventListener('click', function() {
            const value = this.dataset.value;
            selectedFunction = value;
            functionSelectBox.textContent = value;
            functionDropdown.classList.remove('active');
            highlightSelected('#functionList li', this);
            updateGenerateButtonState();
            appendLog(`已选择分析功能：${selectedFunction}`);
        });
    });

    document.addEventListener('click', function(event) {
        if (!document.getElementById('companySelector').contains(event.target)) {
            companyDropdown.classList.remove('active');
        }
        if (!document.getElementById('functionSelector').contains(event.target)) {
            functionDropdown.classList.remove('active');
        }
    });
}

function highlightSelected(selector, current) {
    document.querySelectorAll(selector).forEach(item => item.classList.remove('selected'));
    current.classList.add('selected');
}

function populateQuickStocks() {
    const quickStockList = document.getElementById('quickStockList');
    const items = Array.from(document.querySelectorAll('#companyList li')).slice(0, 8);
    quickStockList.innerHTML = '';
    items.forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `<span class="dot"></span><span>${item.textContent}</span>`;
        li.addEventListener('click', function() { item.click(); });
        quickStockList.appendChild(li);
    });
}

function filterCompanies(query) {
    const items = document.querySelectorAll('#companyList li');
    const noResults = document.getElementById('companyNoResults');
    let hasResults = false;
    Array.from(items).forEach(function(item) {
        const text = item.textContent.toLowerCase();
        if (text.includes(query.toLowerCase())) {
            item.style.display = 'block';
            hasResults = true;
        } else {
            item.style.display = 'none';
        }
    });
    noResults.style.display = hasResults ? 'none' : 'block';
}

function updateGenerateButtonState() {
    const generateBtn = document.getElementById('generateBtn');
    generateBtn.disabled = !(selectedCompanyId && selectedFunction);
}

function getReportSlug(reportType) {
    const mapping = {
        '股票分析报告': 'stock_analysis',
        '前景分析': 'prospect_analysis',
        '风险预测': 'risk_forecast',
        '行业市场分析': 'industry_market'
    };
    return mapping[reportType] || 'stock_analysis';
}

function getCurrentReportFilename() {
    return `${selectedCompanyId}_${selectedCompanyName}_${getReportSlug(selectedFunction)}.md`;
}

function cleanText(raw) {
    return String(raw || '').replace(/\s+/g, ' ').trim();
}

function stripMarkdown(raw) {
    return cleanText(
        String(raw || '')
            .replace(/```[\s\S]*?```/g, ' ')
            .replace(/`([^`]*)`/g, '$1')
            .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
            .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
            .replace(/<[^>]+>/g, ' ')
            .replace(/^\s{0,3}#{1,6}\s*/gm, '')
            .replace(/^\s{0,3}[-*+]\s+/gm, '')
            .replace(/^\s{0,3}\d+\.\s+/gm, '')
            .replace(/[>*_~#-]/g, ' ')
            .replace(/\|/g, ' ')
            .replace(/\n+/g, ' ')
    );
}

function truncateText(text, maxLength = 120) {
    const value = cleanText(text);
    if (!value) return '';
    return value.length > maxLength ? `${value.slice(0, maxLength).trim()}…` : value;
}

function splitSentences(raw) {
    return stripMarkdown(raw)
        .split(/(?<=[。！？!?；;])/)
        .map(s => s.trim())
        .filter(Boolean);
}

function extractConclusion(raw) {
    const plain = stripMarkdown(raw);
    const hit = plain.match(/(结论|投资建议|核心观点|总体判断)[：: ]?([^。；;\n]{8,90})/);
    if (hit && hit[2]) return truncateText(hit[2], 58);
    return truncateText(splitSentences(plain)[0] || '报告生成后，这里会显示自动提炼的核心观点。', 58);
}

function extractRisk(raw) {
    const plain = stripMarkdown(raw);
    const hit = plain.match(/(风险提示|主要风险|风险)[：: ]?([^。；;\n]{8,90})/);
    if (hit && hit[2]) return truncateText(hit[2], 44);
    return '需结合原始报告与实时行情进一步确认。';
}

function extractSummary(raw) {
    const plain = stripMarkdown(raw);
    const sentences = splitSentences(plain).slice(0, 2);
    const merged = sentences.join(' ');
    return truncateText(merged || plain || '欢迎使用智能分析平台，请先在左侧选择股票与分析功能。', 110);
}

function updateSummaryCards(fullText, statusText) {
    document.getElementById('summaryAbstract').textContent = extractSummary(fullText);
    document.getElementById('summaryConclusion').textContent = extractConclusion(fullText);
    document.getElementById('summaryRisk').textContent = extractRisk(fullText);
    document.getElementById('summaryStatus').textContent = statusText || '报告已生成';
}

function updateOverview(fullText) {
    const overview = document.getElementById('overviewContent');
    const sentences = splitSentences(fullText).slice(0, 4);
    if (!sentences.length) {
        overview.innerHTML = '<p>报告已生成，可在全文标签查看完整内容。</p>';
        return;
    }
    overview.innerHTML = sentences.map(s => `<p>${escapeHtml(s)}</p>`).join('');
}

function updateStatus(text, tone = 'green') {
    const statusTone = document.getElementById('statusTone');
    const statusText = document.getElementById('statusText');
    const summaryStatus = document.getElementById('summaryStatus');
    statusTone.className = `mini-tag is-${tone}`;
    statusTone.textContent = '轻量状态';
    statusText.textContent = text;
    summaryStatus.textContent = text;
}

function appendLog(message) {
    const log = document.getElementById('detailLogContent');
    const time = new Date().toLocaleTimeString();
    log.textContent += `\n[${time}] ${message}`;
    log.scrollTop = log.scrollHeight;
}

function escapeHtml(str) {
    return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function generateReport(forceRegenerate = false) {
    if (!selectedCompanyId || !selectedCompanyName) {
        alert('请先选择股票');
        return;
    }
    if (!selectedFunction) {
        alert('请选择分析功能');
        return;
    }

    document.getElementById('loaderContainer').style.display = 'flex';
    updateLoadingStatus(`正在${forceRegenerate ? '重新生成' : '生成'} ${selectedCompanyName} ${selectedFunction}...`);
    updateStatus(`正在生成 ${selectedCompanyName} ${selectedFunction}`, 'yellow');
    appendLog(`开始${forceRegenerate ? '重新生成' : '生成'}报告：${selectedCompanyName} / ${selectedFunction}`);
    addChatMessage('user', `请${forceRegenerate ? '重新生成' : '生成'}${selectedCompanyName}(${selectedCompanyId})的${selectedFunction}`);
    addChatMessage('ai', `正在优先调用智谱大模型生成${selectedFunction}，如失败将自动回退到结构化报告，请稍候...`);
    activateMainTab('overviewTab');

    const streamUrl = `/generate_report_stream?stock_code=${encodeURIComponent(normalizeSelectedCode(selectedCompanyId))}&company_name=${encodeURIComponent(selectedCompanyName)}&report_type=${encodeURIComponent(selectedFunction)}`;
    if (reportStream) {
        reportStream.close();
    }

    let streamedReport = '';
    reportStream = new EventSource(streamUrl);
    currentRequest = reportStream;

    reportStream.onmessage = function(event) {
        const data = JSON.parse(event.data || '{}');
        if (data.event === 'status') {
            const message = data.message || '正在生成中';
            updateLoadingStatus(message);
            updateStatus(message, 'yellow');
            appendLog(message);
            return;
        }

        if (data.event === 'draft_chunk') {
            const sourceText = data.source ? `（${data.source}）` : '';
            const message = `正在生成草稿${sourceText}`;
            updateLoadingStatus(message);
            updateStatus(message, 'yellow');
            return;
        }

        if (data.event === 'report_chunk') {
            streamedReport += data.chunk || '';
            renderStreamingReport(streamedReport);
            updateSummaryCards(streamedReport, `正在生成 ${selectedCompanyName} ${selectedFunction}`);
            updateOverview(streamedReport);
            activateMainTab('fulltextTab');
            return;
        }

        if (data.event === 'complete') {
            appendLog(`报告生成完成：${data.filename || ''}`);
            return;
        }

        if (data.event === 'result') {
            if (reportStream) {
                reportStream.close();
                reportStream = null;
            }
            currentRequest = null;
            document.getElementById('loaderContainer').style.display = 'none';
            const finalReport = data.report || streamedReport;
            displayStreamedReport(finalReport, data);
            // 深度升级：渲染辩论透明化面板 + 自动刷新行情图
            try { renderDebatePanel(data); } catch (e) { console.error('辩论面板渲染失败', e); }
            try { loadChart(); } catch (e) { console.error('行情图刷新失败', e); }
            updateStatus(`${selectedCompanyName} ${selectedFunction} 已生成完成`, 'green');
            addChatMessage('ai', `${selectedCompanyName}的${selectedFunction}已生成完成。您现在既可以继续追问报告内容，也可以直接发起通用问答。`);
            activateMainTab('overviewTab');
            return;
        }

        if (data.event === 'error') {
            if (reportStream) {
                reportStream.close();
                reportStream = null;
            }
            currentRequest = null;
            document.getElementById('loaderContainer').style.display = 'none';
            updateStatus(`报告生成失败：${data.error || '未知错误'}`, 'red');
            appendLog(`流式生成失败：${data.error || '未知错误'}`);
            addChatMessage('ai', `报告生成失败: ${data.error || '未知错误'}`);
        }
    };

    reportStream.onerror = function() {
        if (reportStream) {
            reportStream.close();
            reportStream = null;
        }
        currentRequest = null;
        document.getElementById('loaderContainer').style.display = 'none';
        updateStatus('流式连接中断，请稍后重试', 'red');
        appendLog('流式连接中断');
    };
}

function checkReportStatus(taskId) {
    let checkCount = 0;
    const maxChecks = 30;
    const checkInterval = 2000;

    const statusChecker = setInterval(() => {
        checkCount++;
        fetch(`/report_status/${taskId}`)
        .then(res => res.json())
        .then(data => {
            const waitingText = `正在生成 ${selectedCompanyName} ${selectedFunction}，已等待 ${checkCount * 2} 秒`;
            updateLoadingStatus(waitingText);
            updateStatus(waitingText, 'yellow');

            if (data.status === '完成') {
                clearInterval(statusChecker);
                appendLog('报告生成完成，正在读取报告文件');
                const result = data.result || {};
                const filename = result.filename || getCurrentReportFilename();
                fetch(`/read_report/${filename}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`无法读取报告文件: ${response.status}`);
                    }
                    return response.json();
                })
                .then(reportData => {
                    document.getElementById('loaderContainer').style.display = 'none';
                    displayReport(reportData);
                    updateStatus(`${selectedCompanyName} ${selectedFunction} 已生成完成`, 'green');
                    appendLog('报告读取成功并已渲染到页面');
                    addChatMessage('ai', `${selectedCompanyName}的${selectedFunction}已生成完成。您现在既可以继续追问报告内容，也可以直接发起通用问答。`);
                    activateMainTab('overviewTab');
                })
                .catch(error => {
                    document.getElementById('loaderContainer').style.display = 'none';
                    updateStatus(`报告生成完成但读取失败：${error.message}`, 'red');
                    appendLog(`报告读取失败：${error.message}`);
                    addChatMessage('ai', `${selectedFunction}生成完成，但读取失败: ${error.message}。请尝试重新生成。`);
                });
            } else if (data.status === '失败') {
                clearInterval(statusChecker);
                document.getElementById('loaderContainer').style.display = 'none';
                const errorMessage = (data.result && data.result.error) || data.error || '未知错误';
                updateStatus(`${selectedFunction}生成失败：${errorMessage}`, 'red');
                appendLog(`任务失败：${errorMessage}`);
                addChatMessage('ai', `${selectedFunction}生成失败: ${errorMessage}。请尝试重新生成。`);
            }

            if (checkCount >= maxChecks) {
                clearInterval(statusChecker);
                document.getElementById('loaderContainer').style.display = 'none';
                updateStatus(`${selectedFunction}生成超时，请稍后重试`, 'red');
                appendLog('任务检查超时');
                addChatMessage('ai', `${selectedFunction}生成超时，请稍后重试`);
            }
        })
        .catch(error => {
            console.error(`检查任务状态出错: ${error.message}`);
            appendLog(`检查任务状态出错：${error.message}`);
        });
    }, checkInterval);
}

function renderStreamingReport(fullText) {
    const reportContent = document.getElementById('reportContent');
    reportContent.innerHTML = '';
    document.getElementById('reportSubTitle').textContent = `当前查看：${selectedCompanyName}（${selectedCompanyId}） / ${selectedFunction} / 流式生成中`;
    const container = document.createElement('div');
    container.className = 'report-container';

    const title = document.createElement('h2');
    title.className = 'report-title';
    title.textContent = `${selectedCompanyName}(${selectedCompanyId})${selectedFunction}`;
    container.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'report-meta';
    meta.innerHTML = `
        <span>股票代码: ${escapeHtml(selectedCompanyId)}</span>
        <span>股票名称: ${escapeHtml(selectedCompanyName)}</span>
        <span>生成时间: ${escapeHtml(new Date().toLocaleString())}</span>
        <span>分析类型: ${escapeHtml(selectedFunction)}</span>
    `;
    container.appendChild(meta);

    const content = document.createElement('div');
    content.className = 'report-content-body markdown-body';
    if (typeof marked !== 'undefined' && fullText) {
        content.innerHTML = safeRenderMarkdown(fullText);
    } else {
        content.innerHTML = (fullText || '正在生成报告内容...').replace(/\n/g, '<br>');
    }
    container.appendChild(content);
    reportContent.appendChild(container);

    document.getElementById('reportTitle').textContent = `${selectedCompanyName}${selectedFunction}`;
    document.getElementById('reportSubTitle').textContent = `当前查看：${selectedCompanyName}（${selectedCompanyId}） / ${selectedFunction} / 流式生成中`;
}

function displayStreamedReport(fullText, meta = {}) {
    displayReport({
        title: meta.title || `${selectedCompanyName}(${selectedCompanyId})${selectedFunction}`,
        full_content: fullText,
        creation_time: new Date().toLocaleString()
    });
}

function displayReport(data) {
    const reportContent = document.getElementById('reportContent');
    const fullText = data.full_content || '';

    reportContent.innerHTML = '';

    const container = document.createElement('div');
    container.className = 'report-container';

    const title = document.createElement('h2');
    title.className = 'report-title';
    title.textContent = data.title || `${selectedCompanyName}(${selectedCompanyId})${selectedFunction}`;
    container.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'report-meta';
    meta.innerHTML = `
        <span>股票代码: ${escapeHtml(selectedCompanyId)}</span>
        <span>股票名称: ${escapeHtml(selectedCompanyName)}</span>
        <span>生成时间: ${escapeHtml(data.creation_time || new Date().toLocaleString())}</span>
        <span>分析类型: ${escapeHtml(selectedFunction)}</span>
    `;
    container.appendChild(meta);

    const content = document.createElement('div');
    content.className = 'report-content-body markdown-body';
    if (typeof marked !== 'undefined' && fullText) {
        content.innerHTML = safeRenderMarkdown(fullText);
    } else {
        content.innerHTML = (fullText || '报告内容加载失败').replace(/\n/g, '<br>');
    }
    container.appendChild(content);
    reportContent.appendChild(container);

    setTimeout(() => {
        if (content.querySelectorAll) {
            content.querySelectorAll('pre code').forEach((block) => {
                if (hljs && hljs.highlightBlock) {
                    hljs.highlightBlock(block);
                }
            });
        }
    }, 80);

    document.getElementById('reportTitle').textContent = data.title || `${selectedCompanyName}${selectedFunction}`;
    document.getElementById('reportSubTitle').textContent = `当前查看：${selectedCompanyName}（${selectedCompanyId}） / ${selectedFunction}`;

    updateSummaryCards(fullText, `${selectedCompanyName} ${selectedFunction} 已完成`);
    updateOverview(fullText);

    conversationHistory = [];
    if (fullText) {
        conversationHistory.push({
            role: 'system',
            content: `以下是${selectedCompanyName}(${selectedCompanyId})的${selectedFunction}。后续回答可优先参考这份报告，但如果用户问题超出报告范围，也请正常进行通用问答：\n\n${fullText}`
        });
    }

    const questionInput = document.getElementById('questionInput');
    const submitBtn = document.getElementById('submitBtn');
    questionInput.disabled = false;
    submitBtn.disabled = false;
    reportGenerated = true;
}

function updateLoadingStatus(text) {
    const loadingText = document.querySelector('.loader-text');
    if (loadingText) loadingText.textContent = text;
}

function addChatMessage(sender, message, isTemporary = false, isMarkdown = false) {
    const chatBox = document.getElementById('chatBox');
    const messageDiv = document.createElement('div');
    const messageId = `msg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    messageDiv.className = `chat-bubble ${sender}`;
    messageDiv.id = messageId;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.dataset.rawMessage = message || '';

    if (sender === 'ai' && isMarkdown) {
        renderAiMarkdownContent(contentDiv, message);
    } else {
        contentDiv.textContent = message;
    }

    messageDiv.appendChild(contentDiv);
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
    return messageId;
}

function renderAiMarkdownContent(contentDiv, message) {
    contentDiv.innerHTML = '';
    contentDiv.dataset.rawMessage = message || '';
    const thinkMatch = /(.*?)<\/think>/s.exec(message || '');
    let thinkContent = '';
    let mainContent = message || '';
    if (thinkMatch) {
        thinkContent = thinkMatch[1].trim();
        mainContent = String(message || '').replace(/.*?<\/think>/s, '').trim();
    }
    if (thinkContent) {
        const thinkingDiv = document.createElement('div');
        thinkingDiv.className = 'thinking-process';
        thinkingDiv.innerHTML = `
            <div style="display:flex;align-items:center;margin-bottom:4px;">
                <span style="color:#666;font-size:14px;margin-right:8px;">🤔 思考过程</span>
            </div>
            <div style="color:#666;font-size:13px;line-height:1.5;">${escapeHtml(thinkContent)}</div>
        `;
        contentDiv.appendChild(thinkingDiv);
    }
    const mainContentDiv = document.createElement('div');
    mainContentDiv.className = 'markdown-content';
    if (typeof marked !== 'undefined') {
        let renderedContent = mainContent.replace(/❓/g, '<span class="uncertainty-mark">❓</span>');
        renderedContent = renderedContent.replace(/❗/g, '<span class="uncertainty-mark">❗</span>');
        mainContentDiv.innerHTML = safeRenderMarkdown(renderedContent);
    } else {
        mainContentDiv.innerHTML = mainContent.replace(/\n/g, '<br>');
    }
    contentDiv.appendChild(mainContentDiv);

    const disclaimerMatch = mainContent.match(/(\*\*免责声明\*\*.*)/s);
    if (disclaimerMatch) {
        const disclaimerDiv = document.createElement('div');
        disclaimerDiv.className = 'disclaimer';
        disclaimerDiv.innerText = disclaimerMatch[0].replace(/\*\*/g, '');
        contentDiv.appendChild(disclaimerDiv);
    }
}

function updateChatMessage(messageId, message, isMarkdown = false) {
    const messageElement = document.getElementById(messageId);
    if (!messageElement) return;
    const contentDiv = messageElement.querySelector('.message-content');
    if (!contentDiv) return;
    if (isMarkdown) {
        renderAiMarkdownContent(contentDiv, message);
    } else {
        contentDiv.textContent = message;
        contentDiv.dataset.rawMessage = message || '';
    }
    const chatBox = document.getElementById('chatBox');
    chatBox.scrollTop = chatBox.scrollHeight;
}

function removeChatMessage(messageId) {
    const messageElement = document.getElementById(messageId);
    if (messageElement) messageElement.remove();
}

function submitQuestion() {
    const questionInput = document.getElementById('questionInput');
    const question = questionInput.value.trim();
    if (!question) {
        alert('请输入您的问题');
        return;
    }
    if (!reportGenerated) {
        alert('请先生成报告后再提问');
        return;
    }

    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    addChatMessage('user', question);
    questionInput.value = '';
    activateMainTab('qaTab');
    const streamingMsgId = addChatMessage('ai', '正在分析您的问题...', true, true);
    appendLog(`收到追问：${question}`);

    const streamUrl = `/ask_question_stream?question=${encodeURIComponent(question)}&report_filename=${encodeURIComponent(getCurrentReportFilename())}&conversation_history=${encodeURIComponent(JSON.stringify(conversationHistory))}`;
    const qaStream = new EventSource(streamUrl);
    let streamCompleted = false;
    currentRequest = qaStream;
    let streamedAnswer = '';

    qaStream.onmessage = function(event) {
        const data = JSON.parse(event.data || '{}');
        if (data.event === 'status') {
            appendLog(data.message || '问答处理中');
            updateChatMessage(streamingMsgId, data.message || '正在分析您的问题...', false);
            return;
        }

        if (data.event === 'answer_chunk') {
            streamedAnswer += data.chunk || '';
            updateChatMessage(streamingMsgId, streamedAnswer, true);
            return;
        }

        if (data.event === 'result') {
            streamCompleted = true;
            qaStream.close();
            currentRequest = null;
            const finalAnswer = data.answer || streamedAnswer;
            updateChatMessage(streamingMsgId, finalAnswer, true);
            conversationHistory.push({ role: 'user', content: question });
            if (finalAnswer) {
                conversationHistory.push({ role: 'assistant', content: finalAnswer });
            }
            submitBtn.disabled = false;
            appendLog('问题回答完成');
            return;
        }

        if (data.event === 'error') {
            streamCompleted = true;
            qaStream.close();
            currentRequest = null;
            removeChatMessage(streamingMsgId);
            addChatMessage('ai', `抱歉，处理您的问题时出错: ${data.error || '未知错误'}。请稍后再试。`);
            submitBtn.disabled = false;
            appendLog(`问题回答失败：${data.error || '未知错误'}`);
        }
    };

    qaStream.onerror = function() {
        if (streamCompleted) {
            return;
        }
        qaStream.close();
        currentRequest = null;
        removeChatMessage(streamingMsgId);
        addChatMessage('ai', '抱歉，问答流式连接中断，请稍后再试。');
        submitBtn.disabled = false;
        appendLog('问答流式连接中断');
    };
}

function getReportNodesForExport() {
    const reportContent = document.querySelector('.report-content-body');
    const reportMeta = document.querySelector('.report-meta');
    const emptyState = document.querySelector('#reportContent .empty-state');
    if (!reportContent || emptyState) {
        return null;
    }
    return { reportContent, reportMeta };
}

function getExportBaseName() {
    return `${selectedCompanyName || '未命名'}_${selectedCompanyId || 'stock'}_${selectedFunction || '报告'}`;
}

function getPrintableReportHtml() {
    const nodes = getReportNodesForExport();
    if (!nodes) return '';
    const title = escapeHtml(document.getElementById('reportTitle').textContent || '智能分析报告');
    const metaHtml = nodes.reportMeta ? nodes.reportMeta.innerHTML : '';
    const contentHtml = nodes.reportContent.innerHTML;
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${title}</title>
<style>
body{font-family:"PingFang SC","Microsoft YaHei",Arial,sans-serif;margin:32px;color:#132843;line-height:1.75;background:#fff;}
h1{font-size:28px;margin:0 0 10px;}
.report-meta{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 22px;padding:12px 14px;background:#D6DEEB;border-radius:12px;color:#3966A2;font-size:13px;}
.report-meta span{display:inline-block;}
h1,h2,h3{color:#132843;} table{width:100%;border-collapse:collapse;margin:16px 0;} th,td{border:1px solid #D6DEEB;padding:8px 10px;text-align:left;} pre{white-space:pre-wrap;word-break:break-word;background:#F8F6FF;padding:12px;border-radius:10px;} img{max-width:100%;} @page{margin:18mm 14mm;}
</style>
</head>
<body>
<h1>${title}</h1>
<div class="report-meta">${metaHtml}</div>
<div class="report-body">${contentHtml}</div>
</body>
</html>`;
}

function printReport() {
    const printableHtml = getPrintableReportHtml();
    if (!printableHtml) {
        alert('没有可打印的报告内容');
        return;
    }
    const printWindow = window.open('', '_blank');
    if (!printWindow) {
        alert('打印窗口被浏览器拦截，请允许弹窗后重试');
        return;
    }
    printWindow.document.open();
    printWindow.document.write(printableHtml);
    printWindow.document.close();
    printWindow.focus();
    printWindow.onload = function() {
        printWindow.print();
    };
}

function triggerBlobDownload(content, mimeType, extension) {
    const element = document.createElement('a');
    const file = new Blob([content], {type: mimeType});
    element.href = URL.createObjectURL(file);
    element.download = `${getExportBaseName()}.${extension}`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
    setTimeout(() => URL.revokeObjectURL(element.href), 500);
}

function downloadReport(type = 'markdown') {
    const menu = document.getElementById('downloadOptions');
    if (menu) menu.classList.remove('is-open');
    const nodes = getReportNodesForExport();
    if (!nodes) {
        alert('没有可下载的报告内容');
        return;
    }

    const text = nodes.reportContent.textContent || nodes.reportContent.innerText || '';

    if (type === 'markdown') {
        triggerBlobDownload(text, 'text/markdown;charset=utf-8', 'md');
        return;
    }

    if (type === 'txt') {
        triggerBlobDownload(text, 'text/plain;charset=utf-8', 'txt');
        return;
    }

    if (type === 'word') {
        const wordHtml = getPrintableReportHtml();
        triggerBlobDownload(wordHtml, 'application/msword;charset=utf-8', 'doc');
        return;
    }

    if (type === 'pdf') {
        if (typeof html2pdf === 'undefined') {
            alert('PDF 组件加载失败，请稍后重试');
            return;
        }
        const temp = document.createElement('div');
        temp.innerHTML = getPrintableReportHtml();
        const exportNode = temp.querySelector('body') || temp;
        const wrapper = document.createElement('div');
        wrapper.style.padding = '0';
        wrapper.append(...Array.from(exportNode.childNodes).map(node => node.cloneNode(true)));
        html2pdf().set({
            margin: [12, 10, 12, 10],
            filename: `${getExportBaseName()}.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2, useCORS: true },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
            pagebreak: { mode: ['css', 'legacy'] }
        }).from(wrapper).save();
    }
}

function cancelCurrentRequest() {
    if (reportStream) {
        reportStream.close();
        reportStream = null;
    }
    if (currentRequest && typeof currentRequest.abort === 'function') {
        currentRequest.abort();
        currentRequest = null;
    }
    document.getElementById('loaderContainer').style.display = 'none';
    updateStatus('已取消当前报告生成请求', 'red');
    appendLog('已取消当前报告生成请求');
    addChatMessage('ai', '已取消当前报告生成请求');
}


/* ==========================================================
 * 深度升级模块：安全渲染 / ECharts 行情图 / 辩论透明化 / 历史报告 / 全市场搜索
 * ========================================================== */

// ---------- XSS 防护：统一 Markdown 安全渲染 ----------
function safeRenderMarkdown(raw) {
    if (typeof marked === 'undefined') {
        return String(raw || '').replace(/\n/g, '<br>');
    }
    let html;
    try {
        html = marked.parse(String(raw || ''));
    } catch (err) {
        return String(raw || '').replace(/\n/g, '<br>');
    }
    if (typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(html, { FORBID_TAGS: ['style', 'form', 'input'], FORBID_ATTR: ['onerror', 'onclick', 'onload'] });
    }
    return html;
}

// ---------- ECharts 行情图表 ----------
let klineChartInstance = null;
let volumeChartInstance = null;
let radarChartInstance = null;

function destroyChart(instance) {
    if (instance && !instance.isDisposed()) {
        instance.dispose();
    }
    return null;
}

function upDownColor(value) {
    // 中国市场惯例：涨红跌绿
    const num = Number(value);
    if (Number.isNaN(num)) return '#888';
    return num >= 0 ? '#FF4D4F' : '#3CB371';
}

function loadChart() {
    if (!selectedCompanyId) {
        document.getElementById('chartMeta').textContent = '请先在左侧选择股票，图表将自动加载该股真实行情。';
        return;
    }
    const meta = document.getElementById('chartMeta');
    meta.textContent = '正在加载真实行情数据（AkShare）...';
    fetch(`/stock_chart_data?stock_code=${encodeURIComponent(selectedCompanyId)}`)
        .then(res => res.json())
        .then(data => {
            if (!data || !data.success) {
                meta.textContent = '行情数据加载失败：' + (data && data.error ? data.error : '未知错误');
                return;
            }
            meta.textContent = `${selectedCompanyName}（${selectedCompanyId}） 近 ${data.dates.length} 个交易日 | 区间涨跌幅: ` +
                `${data.summary.period_pct_change != null ? data.summary.period_pct_change + '%' : '—'}` +
                ` | 数据源: AkShare（东财公开数据）`;
            renderKlineChart(data);
            renderVolumeChart(data);
        })
        .catch(err => {
            meta.textContent = '行情数据加载异常：' + err;
        });
}

function renderKlineChart(data) {
    const el = document.getElementById('klineChart');
    if (!el || typeof echarts === 'undefined') return;
    klineChartInstance = destroyChart(klineChartInstance);
    klineChartInstance = echarts.init(el);
    klineChartInstance.setOption({
        title: { text: '日 K 线（前复权）', left: 'center', textStyle: { fontSize: 14, color: '#132843' } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        grid: { left: '10%', right: '6%', top: '14%', bottom: '12%' },
        xAxis: {
            type: 'category',
            data: data.dates,
            axisLabel: { color: '#3966A2' }
        },
        yAxis: { type: 'value', scale: true, axisLabel: { color: '#3966A2' } },
        series: [{
            type: 'candlestick',
            data: data.kline,
            itemStyle: {
                color: '#FF4D4F',        // 阳线：红（中国市场惯例）
                color0: '#3CB371',       // 阴线：绿
                borderColor: '#FF4D4F',
                borderColor0: '#3CB371'
            }
        }]
    });
}

function renderVolumeChart(data) {
    const el = document.getElementById('volumeChart');
    if (!el || typeof echarts === 'undefined') return;
    volumeChartInstance = destroyChart(volumeChartInstance);
    volumeChartInstance = echarts.init(el);
    volumeChartInstance.setOption({
        title: { text: '成交量', left: 'center', textStyle: { fontSize: 14, color: '#132843' } },
        tooltip: { trigger: 'axis' },
        grid: { left: '10%', right: '6%', top: '16%', bottom: '12%' },
        xAxis: { type: 'category', data: data.dates, axisLabel: { color: '#3966A2' } },
        yAxis: { type: 'value', axisLabel: { color: '#3966A2' } },
        series: [{
            type: 'bar',
            data: data.dates.map((d, i) => ({
                value: data.volumes[i],
                itemStyle: { color: upDownColor((data.kline[i][1] - data.kline[i][0]) / (data.kline[i][0] || 1) * 100) }
            }))
        }]
    });
}

// ---------- 评分雷达图 ----------
function renderScoreRadar(scoreboard) {
    const el = document.getElementById('radarChart');
    if (!el || typeof echarts === 'undefined' || !scoreboard) return;
    const dims = ['数据扎实', '逻辑', '清晰度', '风险揭示', '合规'];
    const dimKeys = ['data_grounding', 'logic', 'clarity', 'risk', 'compliance'];
    const pick = key => scoreboard[key];
    if (!pick('draft_a_v2') && !pick('draft_b_v2')) return;

    radarChartInstance = destroyChart(radarChartInstance);
    radarChartInstance = echarts.init(el);

    const seriesData = [];
    if (pick('draft_a_v2')) {
        seriesData.push({
            name: '多头方（终稿）',
            value: dimKeys.map(k => (pick('draft_a_v2').dimension_scores || {})[k] || 0),
            lineStyle: { color: '#FF4D4F' },
            itemStyle: { color: '#FF4D4F' }
        });
    }
    if (pick('draft_b_v2')) {
        seriesData.push({
            name: '空方/风控方（终稿）',
            value: dimKeys.map(k => (pick('draft_b_v2').dimension_scores || {})[k] || 0),
            lineStyle: { color: '#3CB371' },
            itemStyle: { color: '#3CB371' }
        });
    }

    radarChartInstance.setOption({
        title: { text: '多空双方终稿 · 五维评分对比', left: 'center', textStyle: { fontSize: 14, color: '#132843' } },
        tooltip: {},
        legend: { bottom: 0, data: seriesData.map(s => s.name) },
        radar: {
            indicator: dims.map(name => ({ name, max: 20 })),
            axisName: { color: '#3966A2' }
        },
        series: [{ type: 'radar', data: seriesData }]
    });
}

// ---------- 辩论过程透明化 ----------
const DRAFT_LABELS = {
    draft_a_v1: { side: 'a', round: '第一轮初稿', title: '多头研究员 · 初稿' },
    draft_b_v1: { side: 'b', round: '第一轮初稿', title: '空方/风控研究员 · 初稿' },
    draft_a_v2: { side: 'a', round: '第二轮修订稿', title: '多头研究员 · 修订稿' },
    draft_b_v2: { side: 'b', round: '第二轮修订稿', title: '空方/风控研究员 · 修订稿' }
};

function renderDebatePanel(resultData) {
    const metaEl = document.getElementById('debateMeta');
    const grid = document.getElementById('debateGrid');
    if (!metaEl || !grid) return;

    const scoreboard = (resultData && resultData.scoreboard) || {};
    const keys = Object.keys(DRAFT_LABELS);
    if (!keys.some(k => scoreboard[k])) {
        metaEl.textContent = '暂无辩论数据。生成报告后，这里将展示多空双方的完整对抗过程。';
        grid.innerHTML = '';
        return;
    }

    const mode = resultData.debate_mode || 'adversarial';
    const winner = resultData.winner || '';
    const modeText = mode === 'adversarial'
        ? '多空对抗模式：多头研究员 vs 空方/风控研究员，评审中立仲裁'
        : '平行视角模式：两个生成器侧重不同方向';

    metaEl.innerHTML = `辩论模式：<strong>${modeText}</strong>` +
        (winner && winner !== 'structured_fallback'
            ? ` · 胜者：<strong>${winner === 'generator_a' ? '多头研究员（Generator A）' : '空方/风控研究员（Generator B）'}</strong>` +
              ` · 最终得分：<strong>${(resultData.final_score || {}).total_score != null ? resultData.final_score.total_score : '—'}</strong>`
            : '');

    grid.innerHTML = '';
    keys.forEach(key => {
        const label = DRAFT_LABELS[key];
        const score = scoreboard[key];
        if (!score) return;
        const card = document.createElement('div');
        card.className = 'debate-card' + (key === 'draft_a_v2' || key === 'draft_b_v2'
            ? (winner === (key === 'draft_a_v2' ? 'generator_a' : 'generator_b') ? ' is-winner' : '')
            : '');
        const roleClass = label.side === 'a' ? 'is-bull' : 'is-bear';
        const roleName = label.side === 'a' ? '多头' : '空方/风控';
        const strengths = (score.strengths || []).slice(0, 3).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>—</li>';
        const weaknesses = (score.weaknesses || []).slice(0, 3).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>—</li>';
        card.innerHTML = `
            <div class="debate-card-head">
                <span class="debate-card-title">${escapeHtml(label.title)}</span>
                <span class="debate-score">${score.total_score != null ? score.total_score : '—'} 分</span>
            </div>
            <div>
                <span class="debate-role ${roleClass}">${roleName}</span>
                <span class="debate-role">${escapeHtml(label.round)}</span>
            </div>
            <div class="debate-list-title">✔ 优势</div>
            <ul class="debate-list">${strengths}</ul>
            <div class="debate-list-title">⚠ 短板</div>
            <ul class="debate-list">${weaknesses}</ul>
        `;
        grid.appendChild(card);
    });

    renderScoreRadar(scoreboard);
}

// ---------- 历史报告中心 ----------
function loadReportHistory() {
    const list = document.getElementById('historyList');
    if (!list) return;
    fetch('/report_list')
        .then(res => res.json())
        .then(data => {
            const reports = (data && data.reports) || [];
            if (!reports.length) {
                list.innerHTML = '<div class="history-empty">还没有任何报告。选择股票后点击"生成分析报告"即可创建第一份报告。</div>';
                return;
            }
            list.innerHTML = '';
            reports.forEach(rep => {
                const item = document.createElement('div');
                item.className = 'history-item';
                const title = rep.stock_name
                    ? `${rep.stock_name}（${rep.stock_code}）· ${rep.report_type || ''}`
                    : rep.filename;
                const sub = `${rep.created_at || ''}${rep.winner && rep.winner !== 'structured_fallback' ? ' · 胜者: ' + (rep.winner === 'generator_a' ? '多头方' : '空方/风控方') : ''}${rep.debate_mode ? ' · ' + (rep.debate_mode === 'adversarial' ? '多空对抗' : '平行视角') : ''}`;
                item.innerHTML = `
                    <div class="history-item-main">
                        <div class="history-item-title">${escapeHtml(title)}</div>
                        <div class="history-item-sub">${escapeHtml(sub)}</div>
                    </div>
                    <div class="history-score">${rep.total_score != null ? rep.total_score + ' 分' : '—'}</div>
                `;
                item.addEventListener('click', () => openHistoryReport(rep.filename));
                list.appendChild(item);
            });
        })
        .catch(() => {
            list.innerHTML = '<div class="history-empty">历史报告加载失败，请稍后重试。</div>';
        });
}

function openHistoryReport(filename) {
    fetch(`/read_report/${encodeURIComponent(filename)}`)
        .then(res => res.json())
        .then(data => {
            if (data && data.error) {
                alert('读取报告失败：' + data.error);
                return;
            }
            displayReport({
                title: filename,
                full_content: data.content || '',
                creation_time: data.created_at || ''
            });
            if (window.activateMainTab) window.activateMainTab('fulltextTab');
            // 同时拉取该报告的辩论元数据
            fetch(`/report_metadata/${encodeURIComponent(filename)}`)
                .then(res => res.json())
                .then(metaData => {
                    if (metaData && metaData.metadata) {
                        renderDebatePanel(metaData.metadata);
                        activateMainTab && activateMainTab('debateTab') ;
                    }
                })
                .catch(() => {});
        })
        .catch(err => alert('读取报告异常：' + err));
}

// ---------- 全市场股票搜索 ----------
let searchDebounceTimer = null;

function initStockSearch() {
    const searchBox = document.getElementById('companySearchBox');
    const dropdown = document.getElementById('companyDropdown');
    const listEl = document.getElementById('companyList');
    const noResults = document.getElementById('companyNoResults');
    if (!searchBox) return;

    searchBox.addEventListener('input', function() {
        const keyword = this.value.trim();
        clearTimeout(searchDebounceTimer);
        if (!keyword) {
            // 恢复默认列表
            restoreDefaultCompanyList();
            return;
        }
        searchDebounceTimer = setTimeout(() => {
            fetch(`/search_stocks?keyword=${encodeURIComponent(keyword)}&limit=20`)
                .then(res => res.json())
                .then(data => {
                    const results = (data && data.results) || [];
                    listEl.innerHTML = '';
                    if (!results.length) {
                        noResults.style.display = 'block';
                        noResults.textContent = data && data.error ? data.error : '无匹配结果';
                        return;
                    }
                    noResults.style.display = 'none';
                    results.forEach(stock => {
                        const li = document.createElement('li');
                        const pct = stock.pct_change;
                        const pctText = pct != null ? ` ${pct >= 0 ? '+' : ''}${pct}%` : '';
                        const pctColor = upDownColor(pct);
                        li.innerHTML = `${escapeHtml(stock.name)} (${stock.code})` +
                            `<span style="margin-left:8px;color:${pctColor};font-size:12px;">${pctText}</span>`;
                        li.addEventListener('click', function() {
                            selectedCompanyId = stock.code;
                            selectedCompanyName = stock.name;
                            searchBox.value = `${stock.name} (${stock.code})`;
                            document.getElementById('topSearchInput').value = searchBox.value;
                            dropdown.classList.remove('active');
                            highlightSelected('#companyList li', li);
                            updateGenerateButtonState();
                            appendLog(`已选择股票：${selectedCompanyName}（${selectedCompanyId}）`);
                            updateStatus(`已选择 ${selectedCompanyName}，等待生成报告`, 'green');
                            loadChart();
                        });
                        listEl.appendChild(li);
                    });
                })
                .catch(() => {
                    noResults.style.display = 'block';
                    noResults.textContent = '搜索服务暂时不可用';
                });
        }, 250);
    });
}

function restoreDefaultCompanyList() {
    // 重新加载页面内嵌的默认列表（保存在 initStockSearch 时快照）
    const listEl = document.getElementById('companyList');
    if (!listEl || !window.__defaultCompanyListHTML) return;
    listEl.innerHTML = window.__defaultCompanyListHTML;
    bindDefaultCompanyList();
}

function bindDefaultCompanyList() {
    document.querySelectorAll('#companyList li').forEach(function(item) {
        item.addEventListener('click', function() {
            selectedCompanyId = this.getAttribute('data-code');
            selectedCompanyName = this.getAttribute('data-name');
            const searchBox = document.getElementById('companySearchBox');
            searchBox.value = this.textContent;
            document.getElementById('topSearchInput').value = this.textContent;
            document.getElementById('companyDropdown').classList.remove('active');
            highlightSelected('#companyList li', this);
            updateGenerateButtonState();
            appendLog(`已选择股票：${selectedCompanyName}（${selectedCompanyId}）`);
            updateStatus(`已选择 ${selectedCompanyName}，等待生成报告`, 'green');
            loadChart();
        });
    });
}

// 兼容默认股票代码格式（600519.SS -> 600519）
function normalizeSelectedCode(code) {
    return String(code || '').split('.')[0];
}
