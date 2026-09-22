/* Shared, local-only reading preferences. Loaded before either page module. */
(() => {
  const keys = {theme: 'historyViewer.ui.codeTheme', roles: 'historyViewer.ui.roleFilters', reader: 'historyViewer.ui.readerPreferences'};
  const themes = {light: '明亮', slate: '石板', warm: '暖色', forest: '森林', grape: '葡萄', dark: '深色'};
  const roles = {user: '我的消息', assistant: '助手回复', tool: '工具记录', system: '系统消息', developer: '开发者消息', other: '其他记录'};
  const sourceNames = {codebuddy: 'CodeBuddy (cbc)', codex: 'Codex', claude: 'Claude Code', gemini: 'Gemini CLI', opencode: 'OpenCode', zcode: 'ZCode', copilot: 'GitHub Copilot', agy: 'AGY CLI', antigravity: 'Antigravity', pi: 'pi', prime: 'Prime Agent', openclaw: 'OpenClaw', hermes: 'Hermes'};
  const defaults = {fontSize: 14, toolsCollapsed: true, auditExpanded: false};
  const get = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const json = key => { try { return JSON.parse(get(key)) || {}; } catch { return {}; } };
  function getPreferences() {
    const raw = json(keys.reader), savedRoles = json(keys.roles), theme = get(keys.theme);
    return {theme: Object.hasOwn(themes, theme) ? theme : 'light',
      fontSize: [13, 14, 15, 16, 18].includes(raw.fontSize) ? raw.fontSize : defaults.fontSize,
      toolsCollapsed: typeof raw.toolsCollapsed === 'boolean' ? raw.toolsCollapsed : defaults.toolsCollapsed,
      auditExpanded: typeof raw.auditExpanded === 'boolean' ? raw.auditExpanded : defaults.auditExpanded,
      roles: Object.fromEntries(Object.keys(roles).map(role => [role, typeof savedRoles[role] === 'boolean' ? savedRoles[role] : true]))};
  }
  const dialog = document.createElement('dialog');
  dialog.id = 'readerSettingsDialog'; dialog.className = 'settings-dialog';
  dialog.setAttribute('aria-labelledby', 'settingsTitle');
  dialog.innerHTML = `
    <header class="settings-heading"><div><h2 id="settingsTitle">设置</h2><p class="muted">调整阅读习惯，管理本地来源。</p></div><button type="button" class="btn" id="settingsClose" aria-label="关闭设置">关闭</button></header>
    <nav class="settings-tabs" aria-label="设置分类"><button type="button" class="btn active" data-settings-tab="reading" aria-pressed="true">阅读偏好</button><button type="button" class="btn" data-settings-tab="sources" aria-pressed="false">本地来源</button></nav>
    <section id="settingsReading">
      <fieldset><legend>外观主题</legend><div class="theme-grid" role="group" aria-label="外观主题">${Object.entries(themes).map(([key, label]) => `<button type="button" class="tab" data-code-theme="${key}" aria-pressed="false">${label}</button>`).join('')}</div></fieldset>
      <div class="settings-row"><label for="readerFontSize">对话字号</label><select id="readerFontSize">${[13, 14, 15, 16, 18].map(size => `<option value="${size}">${size} px</option>`).join('')}</select></div>
      <fieldset><legend>显示哪些消息</legend><div class="roles">${Object.entries(roles).map(([key, label]) => `<label><input type="checkbox" data-role="${key}" checked> ${label}</label>`).join('')}</div></fieldset>
      <label class="settings-check"><input id="readerToolsCollapsed" type="checkbox" checked> 默认收起工具输出</label>
      <label class="settings-check"><input id="readerAuditExpanded" type="checkbox"> 打开对话时展开审计</label>
      <p class="muted settings-help">偏好只保存在当前浏览器，不改变原始会话。</p>
      <div class="settings-footer"><button type="button" class="btn small" id="settingsReset">恢复阅读默认值</button><button type="button" class="btn small" id="clearRenderCache">清除渲染缓存</button></div>
      <p id="settingsSaveStatus" class="muted" role="status" aria-live="polite"></p>
    </section>
    <section id="settingsSources" hidden><div class="settings-source-heading"><p class="muted">读取各工具在本机保存的历史。</p><button type="button" class="btn small" id="settingsSourcesReload">重新检查</button></div><p id="settingsSourceStatus" class="muted" role="status"></p><div id="settingsSourceList"></div><p class="muted settings-help">来源路径由启动参数配置。下面的配置说明只供复制，不会启动 Agent 或修改原始历史。</p></section>`;
  document.body.appendChild(dialog);
  const $ = id => dialog.querySelector('#' + id);
  let previousFocus = null, sourceSequence = 0;
  function apply() {
    const prefs = getPreferences();
    document.documentElement.dataset.codeTheme = prefs.theme;
    document.documentElement.style.setProperty('--reader-font-size', prefs.fontSize + 'px');
    dialog.querySelectorAll('[data-code-theme]').forEach(button => {
      const active = button.dataset.codeTheme === prefs.theme;
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
    });
    dialog.querySelectorAll('[data-role]').forEach(input => { input.checked = prefs.roles[input.dataset.role]; });
    $('readerFontSize').value = String(prefs.fontSize);
    $('readerToolsCollapsed').checked = prefs.toolsCollapsed;
    $('readerAuditExpanded').checked = prefs.auditExpanded;
  }
  function save(prefs) {
    let saved = true;
    try {
      localStorage.setItem(keys.theme, prefs.theme);
      localStorage.setItem(keys.roles, JSON.stringify(prefs.roles));
      localStorage.setItem(keys.reader, JSON.stringify({fontSize: prefs.fontSize, toolsCollapsed: prefs.toolsCollapsed, auditExpanded: prefs.auditExpanded}));
    } catch { saved = false; }
    apply();
    $('settingsSaveStatus').textContent = saved ? '已保存，立即生效。' : '浏览器禁止保存偏好，请允许本地存储后重试。';
    window.dispatchEvent(new CustomEvent('hv-preferences-change', {detail: getPreferences()}));
  }
  function text(tag, value, className) {
    const node = document.createElement(tag); node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  async function loadSources() {
    const sequence = ++sourceSequence;
    $('settingsSourceStatus').textContent = '正在读取来源状态…';
    try {
      const response = await fetch('/api/reuse/health');
      if (!response.ok) throw new Error('read_failed');
      const health = await response.json();
      if (sequence !== sourceSequence) return;
      const labels = {ready: '可读取', indexing: '更新中', partial: '部分内容可读', empty: '暂无会话', not_found: '未发现历史', stale: '需要刷新', error: '读取失败', unreadable: '无法读取', unsupported: '格式暂不支持'};
      $('settingsSourceList').replaceChildren();
      for (const source of health.sources || []) {
        const row = text('section', '', 'settings-source-row');
        const heading = text('div', '', 'settings-source-heading');
        heading.append(text('h3', sourceNames[source.source] || source.source), text('span', labels[source.status] || '状态未知', 'muted'));
        row.append(heading);
        if (Number.isInteger(source.count)) row.append(text('p', `${source.count} 个会话`, 'muted'));
        if (source.path) row.append(text('p', source.path, 'settings-source-path'));
        if (source.next_step && source.status !== 'ready') row.append(text('p', source.next_step, 'muted'));
        if (source.command) {
          const detail = document.createElement('details');
          detail.append(text('summary', '查看路径配置命令'), text('code', source.command)); row.append(detail);
        }
        if (source.path && !['not_found', 'indexing'].includes(source.status)) {
          const refresh = text('button', '刷新此来源', 'btn small'); refresh.type = 'button';
          refresh.addEventListener('click', async () => {
            refresh.disabled = true; refresh.textContent = '正在刷新…';
            try {
              const result = await fetch('/api/reuse/refresh', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({system: source.system, source: source.source})});
              if (!result.ok) throw new Error('refresh_failed');
              if (dialog.open && !$('settingsSources').hidden && refresh.isConnected) {
                refresh.disabled = false; refresh.textContent = '刷新此来源';
                await loadSources();
              }
            } catch {
              if (!dialog.open || $('settingsSources').hidden || !refresh.isConnected) return;
              refresh.disabled = false; refresh.textContent = '重试刷新';
              $('settingsSourceStatus').textContent = '刷新失败，请检查来源路径或稍后重试。';
            }
          }); row.append(refresh);
        }
        $('settingsSourceList').append(row);
      }
      $('settingsSourceStatus').textContent = health.demo ? '当前为演示数据，未读取真实历史。' : `已检查 ${(health.sources || []).length} 个本地来源。`;
    } catch {
      if (sequence === sourceSequence) $('settingsSourceStatus').textContent = '无法读取来源状态，请确认服务仍在运行后重试。' + ($('settingsSourceList').children.length ? '以下为上次检查结果。' : '');
    }
  }
  function selectSection(section) {
    const sources = section === 'sources';
    $('settingsReading').hidden = sources; $('settingsSources').hidden = !sources;
    dialog.querySelectorAll('[data-settings-tab]').forEach(button => {
      const active = button.dataset.settingsTab === (sources ? 'sources' : 'reading');
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
    });
    if (sources) loadSources(); else sourceSequence++;
  }
  function open(section = 'reading') {
    if (!dialog.open) { previousFocus = document.activeElement; apply(); dialog.showModal(); }
    selectSection(section); $('settingsClose').focus();
  }
  dialog.addEventListener('close', () => { sourceSequence++; if (previousFocus?.isConnected) previousFocus.focus(); });
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  $('settingsClose').addEventListener('click', () => dialog.close());
  $('settingsSourcesReload').addEventListener('click', loadSources);
  dialog.querySelectorAll('[data-settings-tab]').forEach(button => button.addEventListener('click', () => selectSection(button.dataset.settingsTab)));
  dialog.querySelectorAll('[data-code-theme]').forEach(button => button.addEventListener('click', () => save({...getPreferences(), theme: button.dataset.codeTheme})));
  dialog.querySelectorAll('[data-role]').forEach(input => input.addEventListener('change', () => {
    const prefs = getPreferences(); prefs.roles[input.dataset.role] = input.checked; save(prefs);
  }));
  for (const [id, key] of [['readerFontSize', 'fontSize'], ['readerToolsCollapsed', 'toolsCollapsed'], ['readerAuditExpanded', 'auditExpanded']]) {
    $(id).addEventListener('change', () => save({...getPreferences(), [key]: key === 'fontSize' ? Number($(id).value) : $(id).checked}));
  }
  $('settingsReset').addEventListener('click', () => save({...defaults, theme: 'light', roles: Object.fromEntries(Object.keys(roles).map(role => [role, true]))}));
  if (!document.body.classList.contains('reader-page')) $('clearRenderCache').hidden = true;
  document.querySelectorAll('[data-open-settings]').forEach(button => button.addEventListener('click', () => open(button.dataset.settingsSection)));
  window.addEventListener('storage', event => {
    if (event.key === null || Object.values(keys).includes(event.key)) { apply(); window.dispatchEvent(new CustomEvent('hv-preferences-change', {detail: getPreferences()})); }
  });
  window.HVSettings = {open, getPreferences};
  apply();
})();
