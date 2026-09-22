const $ = id => document.getElementById(id);
const listOf = value => Array.isArray(value) ? value : [];
const state = {
  view: 'projects', project: null, query: '', selected: new Map(), selectionVersion: 0,
  preview: null, diagnostic: null, diagnosticShown: false, healthSequence: 0, selectionSequence: 0,
  pages: Object.fromEntries(['search', 'projects', 'timeline'].map(key => [key, {sequence: 0, items: [], cursor: null, params: {}}])),
};
function text(tag, content, className) {
  const node = document.createElement(tag);
  node.textContent = content == null ? '' : String(content);
  if (className) node.className = className;
  return node;
}
function button(label, action, className = 'btn small') {
  const node = text('button', label, className);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
}
function dateLabel(value) {
  if (value == null) return '时间未知';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : '时间未知';
}
function isStale(item, now = Date.now()) {
  const stamp = new Date(item.updated_at).getTime();
  return item.updated_at != null && Number.isFinite(stamp) && now - stamp > 7 * 86400000;
}
function historyLink(item, label, messageIndex, query = '') {
  const link = text('a', label);
  const params = new URLSearchParams({system: item.system || 'linux', source: item.source || '', session: item.id || item.session_id || ''});
  const project = item.project ?? state.project;
  if (project != null) params.set('project', String(project));
  if (Number.isInteger(messageIndex) && messageIndex >= 0) {
    params.set('message', String(messageIndex));
    if (item.source_revision) params.set('source_revision', item.source_revision);
  }
  if (query) params.set('q', query);
  link.href = `/history?${params.toString()}`;
  return link;
}
async function request(path, options) {
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error(`HTTP ${response.status || 'response'}`); }
  if (!response.ok) throw new Error(data.error || data.code || `HTTP ${response.status}`);
  return data;
}
function errorAdvice(error, fallback = '请检查来源状态后重试。') {
  const code = String(error?.message || error || 'unknown');
  if (/index_revision_changed|index_revision_required|cursor.*(?:expired|invalid|changed)|invalid_cursor/.test(code)) return '索引已变化，请重新搜索或重新选择项目，从第一页读取。';
  if (/source_changed|context_revision|revision_mismatch|stale_selection|selection_stale/.test(code)) return '来源内容已变化，请重新搜索并重新选择证据。';
  if (/selection_body_limit_exceeded/.test(code)) return '所选完整消息超出 8000 字符导出上限，未截断导出。请减少选择或改选审计摘要。';
  if (/selection_message_outside_verified_scope/.test(code)) return '完整消息不在已核对范围内，请改选可核对的审计摘要。';
  if (/not_found|source_missing/.test(code)) return '请检查已配置的来源路径；更改启动配置后重新启动应用。';
  if (/unreadable|permission|access_denied/.test(code)) return '请检查当前用户是否有来源读取权限。';
  if (/unsupported/.test(code)) return '当前来源暂不支持此操作，可打开完整会话核对。';
  if (/indexing|busy/.test(code)) return '来源正在建立索引，请等待后重新检查。';
  return fallback;
}
function evidenceFailed(item) {
  return !!item.evidence_status && !['available', 'ready', 'captured'].includes(item.evidence_status);
}
function post(path, data) {
  return request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
}
function warnings(container, data) {
  container.replaceChildren();
  if (container === $('projectsWarnings')) {
    if (listOf(data.errors).length || listOf(data.content_warnings).length || data.partial) {
      const notice = text('p', '部分来源暂未读全，当前项目列表可能不完整。 ', 'work-warning');
      notice.append(button('查看来源状态', () => window.HVSettings?.open('sources')));
      container.append(notice);
    }
    if (data.truncated) container.append(text('p', '项目列表达到读取上限。可使用“搜索历史”按项目路径缩小范围。', 'work-warning'));
    return;
  }
  for (const error of listOf(data.errors)) container.append(text('p', `部分来源未能读取：${error.source || '未知来源'}（${error.error || error.error_code || '读取失败'}）。以下结果并非全部历史。`, 'work-warning'));
  for (const warning of listOf(data.content_warnings)) container.append(text('p', `${sourceLabel(warning.source)} 有 ${warning.incomplete_sessions} 个会话正文未完整解码；搜索仅覆盖可读取内容。`, 'work-warning'));
  if (data.partial && !listOf(data.errors).length && !data.truncated) container.append(text('p', '部分结果或摘录未完整读取。请缩小筛选范围，或打开完整会话核对。', 'work-warning'));
  if (data.pagination_status === 'restart_after_source_error') container.append(text('p', '部分来源读取失败，本次只能查看第一页。请选择可用来源重新搜索，或修复来源后重试。', 'work-warning'));
  if (data.truncated) container.append(text('p', '本次结果达到读取上限。请增加关键词、项目或日期筛选以缩小范围。', 'work-warning'));
}
function meta(item) {
  const node = text('div', '', 'result-meta');
  node.append(text('span', item.source || '来源未知'), text('span', dateLabel(item.updated_at || item.last_activity)));
  node.append(text('span', item.project || '项目未绑定', 'result-project'));
  if (item.content_status && item.content_status !== 'decoded_text') {
    node.append(text('span', item.content_status === 'partial_unsupported_steps' ? '部分步骤未解码，正文不完整' : '仅元数据，正文不可用', 'work-warning'));
  }
  return node;
}
function section(label, values, empty) {
  const node = text('section', '', 'work-fact');
  node.append(text('h4', label));
  if (values.length) {
    const list = text('ul', '');
    for (const value of values) list.append(text('li', value));
    node.append(list);
  } else node.append(text('p', empty, 'muted'));
  return node;
}
const description = value => typeof value === 'string' ? value : value?.summary || value?.description || '';
function hasSourceRevision(item) {
  const provenance = item.provenance || {};
  return provenance.status === 'captured' && [provenance.content_revision, provenance.context_revision].some(value => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value));
}
function observedFailures(item) {
  const count = item.failures?.observed_error_count;
  return Number.isSafeInteger(count) && count >= 0 ? count : null;
}
let rawPanelCounter = 0;
function rawRecord(item, ref, label = '核对原始记录') {
  const wrapper = text('div', '', 'raw-record');
  const line = ref.raw_ref?.line_no ?? ref.line_no;
  const evidenceId = ref.id || ref.evidence_id;
  if (!hasSourceRevision(item) || (!evidenceId && !Number.isInteger(line))) {
    wrapper.append(text('p', '缺少可核对的来源修订或原始行，暂不能精确展开；可打开完整会话核对。', 'muted'));
    return wrapper;
  }
  const panel = text('div', ''); panel.hidden = true; panel.id = `raw-record-${++rawPanelCounter}`;
  let sequence = 0;
  const open = button(label, async () => {
    if (!panel.hidden) { sequence++; panel.hidden = true; open.setAttribute('aria-expanded', 'false'); return; }
    panel.hidden = false; open.setAttribute('aria-expanded', 'true');
    panel.replaceChildren(text('p', '正在核对原始记录…', 'muted'));
    const current = ++sequence;
    try {
      const provenance = item.provenance;
      const params = new URLSearchParams({system: item.system || 'linux', source: item.source || '', session: item.id || item.session_id || '', content_revision: provenance.content_revision || 'unknown', context_revision: provenance.context_revision || 'unknown'});
      if (item.store_id) params.set('store_id', item.store_id);
      if (evidenceId) params.set('evidence_id', evidenceId);
      else params.set('line_no', String(line));
      const data = await request(`/api/reuse/raw?${params.toString()}`);
      if (current !== sequence) return;
      if (typeof data.text !== 'string' || (!Number.isInteger(data.line_no) && !/^\/messages\/\d+$/.test(data.json_pointer || ''))) throw new Error('invalid_raw_record');
      const location = Number.isInteger(data.line_no) ? `原始行 ${data.line_no}` : `原始记录 ${data.json_pointer}`;
      panel.replaceChildren(text('p', `${location}；历史记录，不代表当前代码状态。`, 'muted'));
      const raw = text('pre', data.text); raw.setAttribute('tabindex', '0'); raw.setAttribute('aria-label', location); panel.append(raw);
      if (data.truncated) panel.append(text('p', '原始记录过长，当前仅显示有界摘录。', 'work-warning'));
    } catch (error) {
      if (current !== sequence) return;
      panel.replaceChildren(text('p', `原始记录读取失败（${error.message}）。${errorAdvice(error, '关闭后可重试，或打开完整会话核对。')}`, 'work-warning work-error'));
    }
  });
  open.setAttribute('aria-expanded', 'false'); open.setAttribute('aria-controls', panel.id);
  wrapper.append(open, panel);
  return wrapper;
}
function selectionFor(item, ref) {
  const provenance = item.provenance || {};
  return {system: item.system || 'linux', source: item.source || '', store_id: item.store_id,
    session_id: item.id || item.session_id, evidence_id: ref.id, message_index: ref.message_index,
    content_revision: provenance.content_revision, context_revision: provenance.context_revision};
}
function selectionKey(selection) {
  return JSON.stringify([selection.system, selection.source, selection.store_id || '', selection.session_id, selection.evidence_id, selection.message_index]);
}
function invalidatePreview() {
  state.selectionVersion++;
  state.selectionSequence++;
  state.preview = null;
  $('selectionExport').hidden = true;
  $('selectionMarkdown').textContent = '';
  $('selectionStatus').textContent = '';
}
function toggleSelection(item, ref, checked) {
  if (checked && evidenceFailed(item)) {
    $('selectionStatus').textContent = '证据读取失败，不能加入交接。请重新读取会话后再选。';
    syncSelectionControls();
    return false;
  }
  const selection = selectionFor(item, ref);
  const key = selectionKey(selection);
  if (checked && !state.selected.has(key) && state.selected.size >= 5) {
    $('selectionStatus').textContent = '最多选择 5 条证据。请先移除不需要的条目。';
    syncSelectionControls();
    return false;
  }
  invalidatePreview();
  if (checked) state.selected.set(key, {selection, title: item.title || item.goal || item.id, summary: ref.summary || `证据 ${ref.id}`});
  else state.selected.delete(key);
  renderSelection();
  return true;
}
function syncSelectionControls() {
  for (const input of document.querySelectorAll('[data-evidence-selection]')) {
    input.checked = state.selected.has(input.dataset.evidenceSelection);
  }
}
function evidenceSection(item) {
  if (evidenceFailed(item)) {
    const node = section('证据', [], '证据读取失败或来源不支持，本次内容不能加入交接。');
    node.append(text('p', errorAdvice(item.error || item.error_code || item.evidence_status, '请重新读取会话，或打开完整会话核对。'), 'work-warning'));
    node.append(historyLink(item, '打开完整会话核对'));
    return node;
  }
  const node = section('证据', listOf(item.verified).map(check => `历史验证：${check.command || '命令未记录'}（${check.status || 'unknown'}）`), '未提取到验证依据，请进入历史核对。');
  for (const ref of listOf(item.evidence)) {
    const row = text('div', '', 'evidence-item');
    const label = text('label', '', 'evidence-choice');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.dataset.evidenceSelection = selectionKey(selectionFor(item, ref));
    input.checked = state.selected.has(input.dataset.evidenceSelection);
    const selectable = !!ref.id && hasSourceRevision(item);
    input.disabled = !selectable;
    if (!selectable) input.title = '缺少可核对的来源修订，暂不能加入交接。';
    input.addEventListener('change', () => toggleSelection(item, ref, input.checked));
    const location = Number.isInteger(ref.message_index) ? `审计事件 ${ref.message_index}` : `证据 ${ref.id || '未知'}`;
    label.append(input, text('span', `审计摘要（导出摘要）：${location}${Number.isInteger(ref.line_no) ? ` / 原始行 ${ref.line_no}` : ''}：${ref.summary || '查看原文'}`));
    row.append(label, rawRecord(item, ref));
    if (!selectable) row.append(text('p', '来源修订未知，暂不能选择；仍可查看原文。', 'muted'));
    node.append(row);
  }
  node.append(text('p', '命令成功与历史自报不等于当前代码已验证；当前 Git HEAD 也不是历史基线证明。', 'muted'));
  node.append(historyLink(item, '打开完整会话'));
  return node;
}
function fileChanges(item, activeFile = '') {
  const changes = listOf(item.file_changes);
  const node = section('成果', listOf(item.changed).map(change => `历史变更：${change.path || description(change) || '路径未记录'}`), '未提取到变更记录；不代表没有成果。');
  const statuses = {available: '已提取', known: '已提取', partial: '部分可用', unavailable: '不可用', unsupported: '来源不支持', unknown: '未知', attempted: '记录过修改尝试', none: '未记录'};
  if (item.file_status) node.append(text('p', `文件记录：${statuses[item.file_status] || '未知'}。`, 'muted'));
  if (item.diff_status) node.append(text('p', `补丁记录：${statuses[item.diff_status] || '未知'}。`, 'muted'));
  if (!changes.length) {
    node.append(text('p', '历史补丁不可用；不能据此判断当前文件是否已修改。', 'muted'));
    return node;
  }
  const normalizedFile = String(activeFile).replaceAll('\\', '/').replace(/^\.\//, '');
  for (const change of changes) {
    const path = String(change.path || '路径未记录');
    const normalizedPath = path.replaceAll('\\', '/').replace(/^\.\//, '');
    const selected = normalizedFile && (normalizedPath === normalizedFile || normalizedPath.endsWith(`/${normalizedFile}`));
    const row = text('div', '', `file-change${selected ? ' file-change-selected' : ''}`);
    row.append(text('p', `${selected ? '当前筛选文件：' : ''}${path}`, 'file-change-path'));
    const changeStatus = {attempted: '历史记录：尝试修改；执行结果与当前文件状态未验证。', success: '历史工具执行成功；当前文件状态未验证。', succeeded: '历史工具执行成功；当前文件状态未验证。', failed: '历史工具执行失败；是否在后续修复及当前文件状态未知。'};
    row.append(text('p', changeStatus[change.status] || '历史修改结果未知；当前文件状态未验证。', 'muted'));
    if (change.scope) row.append(text('p', `历史记录范围：${change.scope}`, 'muted'));
    if (typeof change.diff === 'string' && change.diff.trim()) {
      const diff = text('details', '', 'historical-diff');
      diff.append(text('summary', '查看历史补丁（纯文本）'));
      const patch = text('pre', change.diff); patch.setAttribute('tabindex', '0'); patch.setAttribute('aria-label', `${path} 的历史补丁`);
      diff.append(patch); row.append(diff);
    } else row.append(text('p', '历史补丁不可用。请打开原文核对修改意图。', 'muted'));
    row.append(rawRecord(item, change, '核对修改原始记录'));
    node.append(row);
  }
  return node;
}
function facts(item, activeFile = '') {
  const node = text('div', '', 'work-facts');
  const labels = {completed: '历史自报完成 · 当前成果未验证', partial: '历史记录部分完成', failed: '历史记录有失败', blocked: '历史记录有阻塞', unknown: '历史进展未知'};
  node.append(section('进展', [labels[item.status] || labels.unknown], '历史进展未知'));
  node.append(fileChanges(item, activeFile));
  const blockers = listOf(item.blockers).map(description);
  const errorCount = observedFailures(item);
  if (errorCount > 0) blockers.unshift(`历史审计共观察到 ${errorCount} 次失败；当前是否解除未知。后续成功记录不代表这些失败已解决。`);
  else if (errorCount === 0) blockers.push('历史审计未观察到失败；不代表当前运行没有问题。');
  if (!blockers.length && ['failed', 'blocked'].includes(item.status)) blockers.push('历史记录出现失败或阻塞，需核对是否解除。');
  node.append(section('阻塞', blockers, '未提取到历史阻塞；当前是否受阻未知。'));
  node.append(section('待决定', listOf(item.decisions).map(description), '未记录待决定事项；实时审批状态未知。'));
  const next = !item.next_action || String(item.next_action).startsWith('Session outcome is ') ? '核对未完成项与当前代码后继续' : item.next_action;
  node.append(section('下一步', [next, ...listOf(item.remaining).map(description)], '核对当前项目后继续'));
  node.append(evidenceSection(item));
  return node;
}
function record(item, now = Date.now(), activeFile = '') {
  const node = text('details', '', 'work-record');
  const errors = observedFailures(item);
  node.append(text('summary', `${item.goal || item.title || '未命名会话'}${errors > 0 ? ` / 历史失败 ${errors} 次` : ''}`), meta(item));
  if (isStale(item, now)) node.append(text('p', '超过 7 天未见新记录，续接前请核对当前项目。', 'work-warning'));
  node.append(facts(item, activeFile));
  return node;
}
function matchingMessages(item, snippets, query) {
  const node = text('section', '', 'matched-message-choices');
  node.append(text('h4', '命中消息'));
  node.append(text('p', '下方展示命中摘录。选择后导出经修订核对的完整消息；合计超过 8000 字符会明确拒绝，不会悄悄截断。', 'muted'));
  for (const snippet of snippets) {
    if (!Number.isInteger(snippet.message_index) || snippet.message_index < 0) continue;
    const ref = {message_index: snippet.message_index, summary: snippet.text || ''};
    const row = text('div', '', 'evidence-item');
    const label = text('label', '', 'evidence-choice');
    const input = document.createElement('input'); input.type = 'checkbox';
    input.dataset.evidenceSelection = selectionKey(selectionFor(item, ref));
    input.checked = state.selected.has(input.dataset.evidenceSelection);
    input.disabled = evidenceFailed(item) || !hasSourceRevision(item) || !!item.provenance?.truncated;
    input.addEventListener('change', () => toggleSelection(item, ref, input.checked));
    label.append(input, text('span', `完整消息 ${snippet.message_index}${snippet.role ? `（${snippet.role}）` : ''}：${snippet.text || '打开命中原文核对'}`));
    row.append(label, historyLink(item, '核对完整消息', snippet.message_index, query));
    if (input.disabled) row.append(text('p', '完整消息暂无法绑定到已核对的来源修订，可打开原文核对或选择可用审计摘要。', 'muted'));
    node.append(row);
  }
  return node;
}
function searchResult(item, query) {
  const node = text('article', '', 'reuse-result');
  const title = text('h3', '');
  const snippets = listOf(item.snippets);
  title.append(historyLink(item, item.title || '未命名会话', snippets[0]?.message_index, query));
  node.append(title, meta(item));
  if (item.match_reason) node.append(text('p', `命中依据：${description(item.match_reason) || String(item.match_reason)}`, 'muted'));
  for (const snippet of snippets) {
    const block = text('div', '', 'result-snippet');
    block.append(text('div', snippet.text || ''), historyLink(item, `打开命中原文${snippet.role ? `（${snippet.role}）` : ''}`, snippet.message_index, query));
    node.append(block);
  }
  const detail = text('div', '', 'evidence-panel');
  detail.hidden = true;
  let sequence = 0;
  const open = button('查看并选择证据', async () => {
    if (!detail.hidden) { detail.hidden = true; open.setAttribute('aria-expanded', 'false'); sequence++; return; }
    detail.hidden = false;
    open.setAttribute('aria-expanded', 'true');
    detail.replaceChildren(text('p', '正在读取这次会话的证据…', 'muted'));
    const current = ++sequence;
    try {
      const params = new URLSearchParams({system: item.system || 'linux', source: item.source || '', session: item.id || ''});
      if (item.source_revision) params.set('source_revision', item.source_revision);
      const data = await request(`/api/reuse/evidence?${params.toString()}`);
      if (current !== sequence) return;
      const evidence = data.item || data;
      if (evidenceFailed(evidence)) throw new Error(evidence.error || evidence.error_code || evidence.evidence_status);
      if (!Array.isArray(evidence.evidence)) throw new Error('invalid_evidence');
      const boundItem = {...item, ...evidence};
      detail.replaceChildren();
      if (snippets.length) detail.append(matchingMessages(boundItem, snippets, query));
      detail.append(facts(boundItem));
    } catch (error) {
      if (current !== sequence) return;
      detail.replaceChildren(text('p', `证据读取失败（${error.message}）。${errorAdvice(error, '关闭后可重新打开重试。')}`, 'work-warning work-error'));
    }
  });
  const panelId = `evidence-${++evidencePanelCounter}`;
  detail.id = panelId;
  open.setAttribute('aria-expanded', 'false');
  open.setAttribute('aria-controls', panelId);
  const actions = text('div', '', 'result-actions');
  actions.append(open);
  if (item.project != null) actions.append(button('查看工作记录', () => selectProject(item.project)));
  node.append(actions, detail);
  return node;
}
let evidencePanelCounter = 0;
const pageElements = {
  search: {list: 'searchResults', status: 'searchStatus', warnings: 'searchWarnings', more: 'searchMore', label: '结果'},
  projects: {list: 'projectList', status: 'projectsStatus', warnings: 'projectsWarnings', more: 'projectsMore', label: '项目'},
  timeline: {list: 'timelineResults', status: 'timelineStatus', warnings: 'timelineWarnings', more: 'timelineMore', label: '会话'},
};
function renderPage(kind) {
  const page = state.pages[kind], elements = pageElements[kind], list = $(elements.list);
  list.replaceChildren();
  for (const item of page.items) {
    if (kind === 'search') list.append(searchResult(item, page.params.q || ''));
    else if (kind === 'timeline') list.append(record(item, Date.now(), page.params.file || ''));
    else {
      const row = text('div', '', 'project-row');
      const choice = text('a', '', 'project-choice');
      const project = item.project ?? '';
      choice.href = `/history?${new URLSearchParams({project}).toString()}`;
      const identity = text('span', '', 'project-identity');
      identity.append(text('strong', item.label || project || '未绑定项目'), text('span', project || '这些会话未记录项目目录', 'project-path muted'));
      const activity = text('span', '', 'project-activity muted');
      const providers = [...new Set(listOf(item.sources).map(source => sourceLabel(source.source)))];
      activity.append(text('span', `${item.session_count || 0} 个对话${providers.length ? ` · ${providers.join('、')}` : ''}`), text('span', dateLabel(item.last_activity)));
      choice.append(identity, activity);
      const records = button('查看工作记录', () => selectProject(project), 'btn small project-records');
      records.setAttribute('aria-label', `查看 ${item.label || project || '未绑定项目'} 的工作记录`);
      records.setAttribute('aria-expanded', String(state.project === project && !$('timelineSection').hidden));
      records.setAttribute('aria-controls', 'timelineSection');
      row.append(choice, records);
      list.append(row);
    }
  }
  $(elements.status).textContent = page.items.length ? kind === 'projects' ? `${page.items.length} 个项目，按最近活动排列。选择项目即可阅读对话。` : `已显示 ${page.items.length} 个${elements.label}。` : kind === 'search' ? '没有匹配结果。试试更短的关键词，或清除来源、项目与日期筛选。' : kind === 'projects' ? '还没有项目记录。请在设置中检查来源；索引完成后刷新列表。' : '当前项目与文件条件下没有会话。清除文件筛选后重试。';
  $(elements.more).hidden = !page.cursor;
  $(elements.more).disabled = false;
}
async function loadPage(kind, params, append = false) {
  const page = state.pages[kind], elements = pageElements[kind], sequence = ++page.sequence;
  if (!append) { page.items = []; page.cursor = null; page.params = {...params}; $(elements.list).replaceChildren(); }
  const query = new URLSearchParams(page.params);
  query.set('limit', '20');
  if (append && page.cursor) query.set('cursor', page.cursor);
  $(elements.more).disabled = true;
  $(elements.more).hidden = true;
  $(elements.status).textContent = `正在读取${elements.label}…`;
  $(elements.warnings).replaceChildren();
  try {
    const data = await request(`/api/reuse/${kind}?${query.toString()}`);
    if (sequence !== page.sequence) return;
    if (!Array.isArray(data.items)) throw new Error('invalid_response');
    page.items = append ? page.items.concat(data.items) : data.items;
    page.cursor = data.pagination_status === 'restart_after_source_error' ? null : data.next_cursor || null;
    renderPage(kind);
    warnings($(elements.warnings), data);
  } catch (error) {
    if (sequence !== page.sequence) return;
    page.items = []; page.cursor = null;
    $(elements.list).replaceChildren();
    $(elements.more).hidden = true;
    $(elements.status).textContent = `读取失败（${error.message}）。${errorAdvice(error, '请重新搜索或重新读取。')}已清除旧结果。`;
  }
}
function persistSearch(params) {
  if (!window.history?.replaceState || !window.location) return;
  const query = new URLSearchParams({view: 'search'});
  for (const key of ['q', 'source', 'project', 'start', 'end']) if (params[key]) query.set(key, params[key]);
  const value = query.toString();
  window.history.replaceState(null, '', `${window.location.pathname || '/'}${value ? `?${value}` : ''}${window.location.hash || ''}`);
}
function setSourceFilter(value) {
  const select = $('reuseSource');
  if (value && !Array.from(select.children).some(option => option.value === value)) {
    const option = text('option', `${value}（未配置或状态未知）`); option.value = value; select.append(option);
  }
  select.value = value || '';
}
function restoreSearchFromUrl(searchValue = window.location?.search || '') {
  const params = new URLSearchParams(searchValue);
  if (!params.has('q') && params.get('view') !== 'search') return false;
  for (const [id, key] of [['reuseQuery', 'q'], ['reuseProject', 'project'], ['reuseStart', 'start'], ['reuseEnd', 'end']]) $(id).value = params.get(key) || '';
  setSourceFilter(params.get('source') || '');
  return true;
}
function searchParams() {
  const result = {q: $('reuseQuery').value.trim()};
  for (const [id, key] of [['reuseSource', 'source'], ['reuseProject', 'project'], ['reuseStart', 'start'], ['reuseEnd', 'end']]) if ($(id).value.trim()) result[key] = $(id).value.trim();
  return result;
}
async function search(append = false) {
  setView('search', false);
  if (append) return loadPage('search', null, true);
  const params = searchParams();
  persistSearch(params);
  state.query = params.q;
  if (!params.q) {
    state.pages.search.sequence++; state.pages.search.items = []; state.pages.search.cursor = null;
    $('searchResults').replaceChildren(); $('searchWarnings').replaceChildren(); $('searchMore').hidden = true;
    $('searchStatus').textContent = '输入记得的关键词、报错或文件名，再开始搜索。';
    return;
  }
  return loadPage('search', params);
}
function updateLayout() {
  const hasSelectionPanel = state.view === 'search' || (state.view === 'projects' && !$('timelineSection').hidden) || state.selected.size > 0;
  $('selectionPanel').hidden = !hasSelectionPanel;
  $('reuseLayout').className = `reuse-layout${hasSelectionPanel ? '' : ' projects-home'}`;
}
function setView(view, persist = true) {
  state.view = view;
  for (const name of ['search', 'projects']) {
    const selected = name === view;
    $(`${name}View`).hidden = !selected;
    $(`${name}Tab`).setAttribute('aria-selected', String(selected));
    $(`${name}Tab`).setAttribute('tabindex', selected ? '0' : '-1');
    $(`${name}Tab`).className = `tab${selected ? ' active' : ''}`;
  }
  updateLayout();
  if (persist && window.history?.replaceState) {
    if (view === 'search') persistSearch(state.pages.search.params);
    else window.history.replaceState(null, '', `${window.location?.pathname || '/'}${window.location?.hash || ''}`);
  }
  if (view === 'projects' && !state.pages.projects.items.length) return loadPage('projects', {});
}
function showProjects() {
  state.project = null;
  $('timelineSection').hidden = true;
  renderPage('projects');
  return setView('projects');
}
function selectProject(project) {
  if (project == null) return;
  state.project = String(project);
  setView('projects');
  $('timelineSection').hidden = false;
  updateLayout();
  $('timelineTitle').textContent = state.project || '未绑定项目的历史';
  $('timelineFile').value = '';
  renderPage('projects');
  return loadPage('timeline', {project: state.project});
}
function timeline(append = false) {
  if (state.project === null) return;
  if (append) return loadPage('timeline', null, true);
  const params = {project: state.project};
  if ($('timelineFile').value.trim()) params.file = $('timelineFile').value.trim();
  return loadPage('timeline', params);
}
function renderSelection() {
  updateLayout();
  $('selectionCount').textContent = `${state.selected.size} / 5`;
  $('selectionPreview').disabled = !state.selected.size;
  $('selectionClear').disabled = !state.selected.size;
  $('selectionList').replaceChildren();
  for (const [key, item] of state.selected) {
    const row = text('div', '', 'selection-item');
    row.append(text('p', `${item.selection.source} / ${item.title}`), text('p', item.selection.evidence_id ? '将导出审计摘要' : `将导出完整消息 ${item.selection.message_index}（当前仅显示摘录）`, 'muted'), text('p', item.summary));
    row.append(button('移除', () => { invalidatePreview(); state.selected.delete(key); renderSelection(); }));
    $('selectionList').append(row);
  }
  syncSelectionControls();
}
async function previewSelection() {
  if (!state.selected.size) return;
  const version = state.selectionVersion, sequence = ++state.selectionSequence;
  state.preview = null; $('selectionExport').hidden = true; $('selectionMarkdown').textContent = '';
  $('selectionPreview').disabled = true;
  $('selectionStatus').textContent = '正在核对所选证据并生成预览…';
  try {
    const data = await post('/api/reuse/selection', {selections: Array.from(state.selected.values(), item => item.selection)});
    if (version !== state.selectionVersion || sequence !== state.selectionSequence) return;
    if (typeof data.markdown !== 'string' || !Array.isArray(data.items) || data.authorization !== 'context_only') throw new Error('invalid_selection');
    state.preview = data;
    $('selectionMarkdown').textContent = data.markdown;
    $('selectionExport').hidden = false;
    $('selectionStatus').textContent = '预览已就绪。请核对下方内容，再复制或下载。';
  } catch (error) {
    if (version !== state.selectionVersion || sequence !== state.selectionSequence) return;
    $('selectionStatus').textContent = `无法生成交接（${error.message}）。${errorAdvice(error, '来源可能已变化，请重新读取并选择证据。')}`;
  } finally {
    if (version === state.selectionVersion && sequence === state.selectionSequence) $('selectionPreview').disabled = !state.selected.size;
  }
}
function download(name, contents, type) {
  const url = URL.createObjectURL(new Blob([contents], {type}));
  const anchor = text('a', ''); anchor.href = url; anchor.download = name;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function downloadSelection(format) {
  if (!state.preview) return;
  download(`history-evidence.${format}`, format === 'md' ? state.preview.markdown : JSON.stringify(state.preview, null, 2), format === 'md' ? 'text/markdown;charset=utf-8' : 'application/json');
}
async function copySelection() {
  if (!state.preview) return;
  const preview = state.preview;
  try {
    await navigator.clipboard.writeText(preview.markdown);
    if (state.preview === preview) $('selectionStatus').textContent = '已复制 Markdown。';
  } catch {
    if (state.preview === preview) $('selectionStatus').textContent = '浏览器未允许复制。可从预览选择文本，或下载 Markdown。';
  }
}
function sourceLabel(source) {
  return {codebuddy: 'CodeBuddy (cbc)', gemini: 'Gemini CLI', opencode: 'OpenCode',
    codex: 'Codex', claude: 'Claude Code', pi: 'pi', copilot: 'GitHub Copilot', zcode: 'ZCode', prime: 'Prime Agent', agy: 'AGY CLI', antigravity: 'Antigravity'}[source] || source || '未知来源';
}
function renderHealth(data) {
  if (!Array.isArray(data.sources)) throw new Error('invalid_health');
  const sources = $('sourceStatus'); sources.replaceChildren();
  const labels = {readable: '可读取', ready: '可读取', available: '可读取', empty: '暂无记录', missing: '路径不存在', not_found: '路径不存在', unreadable: '没有读取权限', unsupported: '来源格式暂不支持', indexing: '正在建立索引', unknown: '状态未知', unavailable: '不可用', error: '读取失败', stale: '需要刷新'};
  const nextSteps = {
    empty: '来源暂无已索引记录。已有历史时可刷新此来源；也可用 python3 app.py --demo 体验。',
    missing: '检查已配置的来源路径；更改启动配置后重新启动应用。',
    not_found: '检查已配置的来源路径；更改启动配置后重新启动应用。',
    unreadable: '检查当前用户是否有来源文件和目录的读取权限，再重试。',
    unsupported: '当前来源格式暂不支持。可在原生工具中打开记录，或检查应用版本。',
    indexing: '正在建立索引，请稍后点击“重新检查”；无需重复刷新。',
    unknown: '暂不能确认来源状态。请重新检查；仍失败时查看脱敏诊断。',
    stale: '索引可能落后于历史文件。点击“刷新此来源”后重新搜索。',
    error: '检查来源路径与读取权限，然后重试；仍失败时查看脱敏诊断。',
    unavailable: '来源当前不可用。检查路径与读取权限后重新检查。',
  };
  const chosen = $('reuseSource').value;
  $('reuseSource').replaceChildren();
  const all = text('option', '全部来源'); all.value = ''; $('reuseSource').append(all);
  const seen = new Set();
  for (const source of data.sources) {
    if (!seen.has(source.source)) { const option = text('option', sourceLabel(source.source)); option.value = source.source || ''; $('reuseSource').append(option); seen.add(source.source); }
    const row = text('div', '', 'source-row');
    row.append(text('h3', `${sourceLabel(source.source)} / ${source.error_code === 'not_configured' ? '未加载' : source.status === 'partial' ? '部分可读取' : labels[source.status] || source.status || '状态未知'}`));
    row.append(text('p', `记录数：${Number.isFinite(source.count) ? source.count : '未知'}；上次刷新：${dateLabel(source.last_refreshed_at)}`, 'muted'));
    if (source.path) row.append(text('p', source.path, 'source-path'));
    if (source.error_code) row.append(text('p', `读取状态：${source.error_code}`, 'work-warning'));
    if (source.next_step || nextSteps[source.status]) row.append(text('p', source.next_step || nextSteps[source.status]));
    if (source.command) row.append(text('code', source.command));
    const refresh = button('刷新此来源', async () => {
      refresh.disabled = true;
      const outcome = text('p', '正在刷新此来源…', 'muted'); row.append(outcome);
      try {
        await post('/api/reuse/refresh', {system: source.system || 'linux', source: source.source});
        outcome.textContent = '刷新完成。重新搜索后查看最新记录。';
        invalidatePreview(); renderSelection();
        await loadHealth();
      } catch (error) { outcome.textContent = `刷新失败（${error.message}）。${errorAdvice(error, '请检查路径或权限后重试。')}`; refresh.disabled = false; }
    });
    refresh.disabled = ['indexing', 'unsupported'].includes(source.status) || (source.status === 'not_found' && source.path == null);
    row.append(refresh); sources.append(row);
  }
  if (!data.sources.length) sources.append(text('p', '尚未发现已配置的来源。先运行 python3 app.py --demo 体验，或在启动应用时配置真实来源。', 'work-warning'));
  setSourceFilter(chosen);
  $('demoNotice').hidden = !data.demo;
  const active = data.sources.filter(source => Number(source.count) > 0).length;
  $('workspaceStatus').textContent = `${data.demo ? '演示记录' : '本地历史'}${data.version ? ` ${data.version}` : ''} · ${active} 个来源有记录`;
  state.diagnostic = data.diagnostic && typeof data.diagnostic === 'object' ? data.diagnostic : null;
  state.diagnosticShown = false;
  $('diagnosticPreviewBtn').disabled = !state.diagnostic;
  $('diagnosticPreviewBtn').setAttribute('aria-expanded', 'false');
  $('diagnosticPreview').hidden = true; $('diagnosticText').textContent = '';
}
async function loadHealth() {
  const sequence = ++state.healthSequence;
  $('workspaceStatus').textContent = '正在检查本地来源…';
  try {
    const data = await request('/api/reuse/health');
    if (sequence !== state.healthSequence) return;
    renderHealth(data);
  } catch (error) {
    if (sequence !== state.healthSequence) return;
    $('sourceStatus').replaceChildren(); $('demoNotice').hidden = true;
    state.diagnostic = null; state.diagnosticShown = false;
    $('diagnosticPreviewBtn').disabled = true; $('diagnosticPreviewBtn').setAttribute('aria-expanded', 'false');
    $('diagnosticPreview').hidden = true; $('diagnosticText').textContent = '';
    $('workspaceStatus').textContent = `来源检查失败（${error.message}）。请在设置中重新检查，或确认本地服务仍在运行。`;
  }
}
function previewDiagnostic() {
  if (!state.diagnostic) return;
  state.diagnosticShown = !state.diagnosticShown;
  $('diagnosticPreview').hidden = !state.diagnosticShown;
  $('diagnosticPreviewBtn').setAttribute('aria-expanded', String(state.diagnosticShown));
  $('diagnosticText').textContent = state.diagnosticShown ? JSON.stringify(state.diagnostic, null, 2) : '';
}
$('reuseSearchForm').addEventListener('submit', event => { event.preventDefault(); search(); });
$('searchMore').addEventListener('click', () => search(true));
$('projectsMore').addEventListener('click', () => loadPage('projects', null, true));
$('projectsRetry').addEventListener('click', () => loadPage('projects', {}));
$('timelineMore').addEventListener('click', () => timeline(true));
$('timelineFilter').addEventListener('submit', event => { event.preventDefault(); timeline(); });
$('timelineClear').addEventListener('click', () => { $('timelineFile').value = ''; timeline(); });
$('timelineClose').addEventListener('click', showProjects);
for (const view of ['search', 'projects']) {
  $(`${view}Tab`).addEventListener('click', () => view === 'projects' ? showProjects() : setView(view));
  $(`${view}Tab`).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'projects' : event.key === 'End' ? 'search' : view === 'search' ? 'projects' : 'search';
    if (next === 'projects') showProjects(); else setView(next);
    $(`${next}Tab`).focus();
  });
}
$('selectionClear').addEventListener('click', () => { invalidatePreview(); state.selected.clear(); renderSelection(); });
$('selectionPreview').addEventListener('click', previewSelection);
$('selectionCopy').addEventListener('click', copySelection);
$('selectionDownloadMd').addEventListener('click', () => downloadSelection('md'));
$('selectionDownloadJson').addEventListener('click', () => downloadSelection('json'));
$('workspaceRetry').addEventListener('click', loadHealth);
$('diagnosticPreviewBtn').addEventListener('click', previewDiagnostic);
$('diagnosticDownload').addEventListener('click', () => { if (state.diagnostic && state.diagnosticShown) download('history-diagnostic.json', JSON.stringify(state.diagnostic, null, 2), 'application/json'); });
try {
  const theme = localStorage.getItem('historyViewer.ui.codeTheme');
  if (['light', 'slate', 'warm', 'forest', 'grape', 'dark'].includes(theme)) document.documentElement.setAttribute('data-code-theme', theme);
} catch { /* Storage is optional in local and private browser contexts. */ }
async function bootstrapWorkspace() {
  await loadHealth();
  if (state.pages.search.sequence) return;
  if (restoreSearchFromUrl()) {
    setView('search', false);
    if ($('reuseQuery').value.trim()) await search();
  } else await setView('projects', false);
}
if (typeof window !== 'undefined') window.__workspaceTestApi = {state, record, facts, matchingMessages, restoreSearchFromUrl, bootstrapWorkspace, fileChanges, rawRecord, hasSourceRevision, errorAdvice, historyLink, searchResult, selectionFor, toggleSelection, renderSelection, previewSelection, copySelection, downloadSelection, renderHealth, loadHealth, previewDiagnostic, search, loadPage, renderPage, setView, showProjects, selectProject, timeline, isStale};
renderSelection();
bootstrapWorkspace();
