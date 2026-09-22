'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.textContent = ''; this.value = ''; this.attributes = {}; this.dataset = {}; this.hidden = false; this.disabled = false; this.checked = false; }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const child of this.children) child.parent = null; this.children = []; this.textContent = ''; this.append(...nodes); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  click() { if (!this.disabled) return this.listeners.click?.({preventDefault() {}}); }
  focus() { document.activeElement = this; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; }
}
const html = fs.readFileSync(path.join(__dirname, '../static/workspace.html'), 'utf8');
const elements = Object.fromEntries([...html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)].map(match => [match[2], Object.assign(new Element(match[1]), {hidden: /\bhidden\b/.test(match[0])})]));
const walk = node => [node, ...node.children.flatMap(walk)];
const body = new Element('body'); body.append(...Object.values(elements));
const document = {body, documentElement: new Element('html'), getElementById: id => elements[id], createElement: tag => new Element(tag), querySelectorAll: () => walk(body).filter(node => node.dataset.evidenceSelection)};
const flatten = node => node.textContent + '\n' + node.children.map(flatten).join('\n');
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
const response = data => ({ok: true, status: 200, json: async () => data});
const failed = error => ({ok: false, status: 409, json: async () => ({error})});
const calls = [], downloads = [], clipboard = [], replacedUrls = [];
const browserLocation = {pathname: '/', search: '', hash: ''};
const browserWindow = {location: browserLocation, history: {replaceState(_state, _title, value) { replacedUrls.push(value); const url = new URL(value, 'http://local'); browserLocation.search = url.search; }}};
let fetcher = async url => response(url === '/api/reuse/health' ? {sources: []} : {items: []});
let copyFails = false;
const urlApi = {createObjectURL(blob) { downloads.push(blob); return 'blob:local-test'; }, revokeObjectURL() {}};
const context = {document, window: browserWindow, fetch: (...args) => { calls.push(args); return fetcher(...args); }, navigator: {clipboard: {writeText: async value => { if (copyFails) throw new Error('denied'); clipboard.push(value); }}}, URL: urlApi, URLSearchParams, Blob, setTimeout: fn => fn(), Date, localStorage: {getItem: () => 'slate'}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/workspace.js'), 'utf8'), context);
const api = context.window.__workspaceTestApi;
const now = Date.parse('2026-09-22T00:00:00Z');
const base = {system: 'linux', source: 'codex', store_id: 'local', source_revision: 'index-revision-1', id: 'a&evil="', title: '<img src=x onerror=alert(1)>', project: '/work/<project>', updated_at: now, status: 'completed', provenance: {status: 'captured', content_revision: 'sha256:' + 'a'.repeat(64), context_revision: 'sha256:' + 'b'.repeat(64)}, evidence: [{id: 'e1', message_index: 3, line_no: 9, summary: 'exit 0 <script>bad</script>'}], snippets: [{message_index: 3, text: '<img> exact failure', role: 'assistant'}]};
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await flush();
  assert.equal(document.documentElement.getAttribute('data-code-theme'), 'slate');
  assert.equal(calls.length, 2, 'boot reads known sources and the project directory without searching or refreshing');
  assert.equal(calls[0][0], '/api/reuse/health');
  assert.equal(new URL(calls[1][0], 'http://local').pathname, '/api/reuse/projects');
  assert.equal(api.state.view, 'projects');
  assert.equal(elements.projectsView.hidden, false);
  assert.equal(elements.searchView.hidden, true);
  assert.equal(elements.selectionPanel.hidden, true, 'empty handoff does not consume the project homepage');
  assert.match(elements.reuseLayout.className, /projects-home/);
  assert.ok(html.includes('data-open-settings'));
  assert.ok(html.indexOf('/settings.js') < html.indexOf('/workspace.js'));
  // Project rows open the exact project immediately, including duplicate labels and unbound sessions.
  api.state.pages.projects.items = [
    {project: '/work/a&b/repo', label: 'repo', session_count: 7, last_activity: now, sources: [{source: 'codebuddy'}]},
    {project: '/other/repo', label: 'repo', session_count: 2},
    {project: '', label: '未绑定项目', session_count: 1},
  ];
  api.renderPage('projects');
  const projectLinks = walk(elements.projectList).filter(node => node.tag === 'a');
  assert.deepEqual(projectLinks.map(link => new URL(link.href, 'http://local').searchParams.get('project')), ['/work/a&b/repo', '/other/repo', '']);
  assert.ok(projectLinks.every(link => new URL(link.href, 'http://local').pathname === '/history'));
  assert.ok(new URL(projectLinks[2].href, 'http://local').searchParams.has('project'));
  assert.match(flatten(elements.projectList), /\/work\/a&b\/repo/);
  assert.match(flatten(elements.projectList), /\/other\/repo/);
  assert.match(flatten(elements.projectList), /CodeBuddy \(cbc\)/);
  assert.equal(walk(elements.projectList).filter(node => node.tag === 'button' && node.textContent === '查看工作记录').length, 3);
  const record = api.record({...base, blockers: ['build failed'], decisions: ['choose version'], verified: [{command: 'pytest', status: 'passed'}]}, now);
  assert.equal(record.tag, 'details');
  assert.equal(record.children[0].tag, 'summary');
  assert.equal(record.children[0].textContent, base.title);
  const labels = record.children.at(-1).children.map(node => node.children[0].textContent);
  assert.deepEqual(Array.from(labels), ['进展', '成果', '阻塞', '待决定', '下一步', '证据']);
  for (const expected of ['历史自报完成', 'build failed', 'choose version', 'pytest', '审计事件 3 / 原始行 9', '当前 Git HEAD 也不是历史基线证明']) assert.ok(flatten(record).includes(expected));
  assert.match(flatten(api.record({...base, updated_at: now - 8 * 86400000}, now)), /超过 7 天/);
  assert.match(flatten(api.record({...base, evidence_status: 'unavailable', evidence: []}, now)), /证据读取失败/);
  // Full audit failure counts survive a bounded evidence list and later successful records.
  const failures = api.record({...base, status: 'completed', failures: {observed_error_count: 12, parse_errors: 0}, evidence: [{id: 'early-success', message_index: 0, summary: 'exit 0'}], verified: [{command: 'later test', status: 'passed'}]}, now);
  assert.match(failures.children[0].textContent, /历史失败 12 次/);
  assert.match(flatten(failures), /共观察到 12 次失败/);
  assert.match(flatten(failures), /后续成功记录不代表这些失败已解决/);
  assert.match(flatten(failures), /历史自报完成/);
  assert.doesNotMatch(flatten(api.record({...base, failures: {observed_error_count: -1}}, now)), /失败 -1 次/);
  // Failed evidence is not selectable even if the response carries old evidence and revisions.
  const errored = api.record({...base, evidence_status: 'error', error_code: 'source_changed_since_index'}, now);
  assert.equal(walk(errored).filter(node => node.type === 'checkbox').length, 0);
  assert.match(flatten(errored), /证据读取失败/);
  assert.equal(api.toggleSelection({...base, evidence_status: 'error'}, base.evidence[0], true), false);
  assert.equal(api.state.selected.size, 0);
  assert.match(flatten(api.record({...base, evidence_status: 'source_schema_unavailable'}, now)), /证据读取失败/);
  assert.equal(walk(api.record({...base, evidence_status: 'source_schema_unavailable'}, now)).some(node => node.type === 'checkbox'), false);
  assert.equal(api.hasSourceRevision({...base, provenance: {status: 'unknown', content_revision: 'unknown', context_revision: 'unknown'}}), false);
  assert.equal(api.hasSourceRevision({...base, provenance: {status: 'captured', content_revision: 'unknown', context_revision: base.provenance.context_revision}}), true);
  // Structured patches stay plain text and historical attempts, with a visible selected file.
  const patchText = '*** Update File: src/parser.py\n- old\n+ <script>alert(1)</script>';
  const fileRecord = api.record({...base, file_status: 'partial', diff_status: 'partial', file_changes: [
    {path: '/work/src/parser.py', scope: 'historical_tool_call', status: 'attempted', diff: patchText, raw_ref: {line_no: 17}, message_index: 7},
    {path: 'unknown.py', status: 'unknown', diff: null},
  ]}, now, 'src/parser.py');
  const selectedFile = walk(fileRecord).find(node => node.className === 'file-change file-change-selected');
  assert.ok(selectedFile);
  assert.match(flatten(selectedFile), /当前筛选文件：\/work\/src\/parser.py/);
  assert.match(flatten(selectedFile), /尝试修改；执行结果与当前文件状态未验证/);
  const historicalDiff = walk(selectedFile).find(node => node.tag === 'details');
  assert.equal(historicalDiff.open, undefined, 'diff is collapsed by default');
  const patch = walk(historicalDiff).find(node => node.tag === 'pre');
  assert.equal(patch.textContent, patchText);
  assert.equal(patch.innerHTML, undefined);
  assert.match(flatten(fileRecord), /历史补丁不可用/);
  assert.match(flatten(fileRecord), /历史修改结果未知/);
  assert.equal(walk(selectedFile).some(node => node.tag === 'a' && /message=/.test(node.href || '')), false, 'audit/file refs never guess a cached message index');
  const toolOutcomes = api.record({...base, file_changes: [{path: 'ok.py', status: 'success', diff: null}, {path: 'bad.py', status: 'failed', diff: null}]}, now);
  assert.match(flatten(toolOutcomes), /历史工具执行成功；当前文件状态未验证/);
  assert.match(flatten(toolOutcomes), /历史工具执行失败；是否在后续修复及当前文件状态未知/);
  // Raw audit locators use ID/revision or raw line, not the unrelated cached message number.
  const rawPanel = api.rawRecord(base, base.evidence[0]);
  const rawButton = rawPanel.children[0];
  fetcher = async () => response({text: '{"payload":"<script>raw</script>"}', line_no: 9, truncated: true, provenance: base.provenance});
  await rawButton.click();
  let rawUrl = new URL(calls.at(-1)[0], 'http://local');
  assert.equal(rawUrl.pathname, '/api/reuse/raw');
  assert.equal(rawUrl.searchParams.get('evidence_id'), 'e1');
  assert.equal(rawUrl.searchParams.get('content_revision'), base.provenance.content_revision);
  assert.equal(rawUrl.searchParams.get('context_revision'), base.provenance.context_revision);
  assert.equal(rawUrl.searchParams.has('message'), false);
  assert.equal(walk(rawPanel).find(node => node.tag === 'pre').textContent, '{"payload":"<script>raw</script>"}');
  assert.match(flatten(rawPanel), /仅显示有界摘录/);
  await rawButton.click();
  const rawPending = deferred(); fetcher = () => rawPending.promise;
  const rawWaiting = rawButton.click(); await rawButton.click();
  rawPending.resolve(response({text: 'late raw', line_no: 9})); await rawWaiting;
  assert.equal(rawButton.getAttribute('aria-expanded'), 'false');
  assert.doesNotMatch(flatten(rawPanel), /late raw/);
  fetcher = async () => failed('selection_stale'); await rawButton.click();
  assert.match(flatten(rawPanel), /重新搜索并重新选择证据/);
  const fileRaw = api.rawRecord(base, {raw_ref: {line_no: 17}, message_index: 7});
  fetcher = async () => response({text: 'line 17 patch', line_no: 17}); await fileRaw.children[0].click();
  rawUrl = new URL(calls.at(-1)[0], 'http://local');
  assert.equal(rawUrl.searchParams.get('line_no'), '17');
  assert.equal(rawUrl.searchParams.has('evidence_id'), false);
  assert.equal(walk(api.rawRecord({...base, provenance: {}}, base.evidence[0])).some(node => node.tag === 'button'), false);
  const unavailable = api.record({...base, provenance: {}}, now);
  assert.equal(walk(unavailable).find(node => node.type === 'checkbox').disabled, true);

  // All-source results show literal snippets and carry the exact message/query deep link.
  elements.reuseQuery.value = 'sqlite locked';
  let pageNumber = 0;
  fetcher = async () => response({items: pageNumber++ ? [{...base, id: 'second'}] : [base], next_cursor: pageNumber === 1 ? 'revision/page2' : null, errors: [{source: 'claude', error: 'missing'}], truncated: true});
  await api.search();
  const requestUrl = new URL(calls.at(-1)[0], 'http://local');
  assert.equal(requestUrl.searchParams.get('q'), 'sqlite locked');
  assert.equal(requestUrl.searchParams.has('source'), false);
  assert.equal(new URL(replacedUrls.at(-1), 'http://local').searchParams.get('q'), 'sqlite locked');
  assert.match(flatten(elements.searchResults), /<img> exact failure/);
  const resultLink = walk(elements.searchResults).find(node => node.tag === 'a');
  const target = new URL(resultLink.href, 'http://local');
  assert.equal(target.pathname, '/history');
  assert.equal(target.searchParams.get('session'), base.id);
  assert.equal(target.searchParams.get('message'), '3');
  assert.equal(target.searchParams.get('source_revision'), 'index-revision-1');
  assert.equal(target.searchParams.get('project'), base.project);
  assert.equal(api.state.view, 'search');
  assert.equal(elements.searchView.hidden, false);
  assert.equal(new URL(replacedUrls.at(-1), 'http://local').searchParams.get('view'), 'search');
  assert.equal(new URL(api.historyLink(base, 'whole session').href, 'http://local').searchParams.has('source_revision'), false);
  assert.equal(target.searchParams.get('q'), 'sqlite locked');
  assert.match(flatten(elements.searchWarnings), /部分来源未能读取/);
  assert.match(flatten(elements.searchWarnings), /读取上限/);
  assert.equal(elements.searchMore.hidden, false);
  elements.reuseQuery.value = 'unsent edit';
  await api.search(true);
  const nextUrl = new URL(calls.at(-1)[0], 'http://local');
  assert.equal(nextUrl.searchParams.get('cursor'), 'revision/page2');
  assert.equal(nextUrl.searchParams.get('q'), 'sqlite locked', 'pagination keeps the submitted query');
  assert.equal(elements.searchResults.children.length, 2);
  assert.equal(elements.searchMore.hidden, true);
  fetcher = async () => response({items: [base], partial: true}); await api.search();
  assert.match(flatten(elements.searchWarnings), /部分结果或摘录未完整读取/);

  fetcher = async () => response({items: [base], next_cursor: 'unsafe-next', pagination_status: 'restart_after_source_error'}); await api.search();
  assert.match(flatten(elements.searchWarnings), /本次只能查看第一页/);
  assert.equal(elements.searchMore.hidden, true);
  assert.equal(api.state.pages.search.cursor, null);

  const old = deferred(); fetcher = () => old.promise;
  elements.reuseQuery.value = 'old'; const oldSearch = api.search();
  elements.reuseQuery.value = 'new'; fetcher = async () => response({items: [{...base, title: 'new result'}]});
  await api.search();
  old.resolve(response({items: [{...base, title: 'old result'}]})); await oldSearch;
  assert.match(flatten(elements.searchResults), /new result/);
  assert.doesNotMatch(flatten(elements.searchResults), /old result/);
  fetcher = async () => failed('index_revision_changed');
  await api.search();
  assert.equal(elements.searchResults.children.length, 0);
  assert.match(elements.searchStatus.textContent, /读取失败/);
  assert.match(elements.searchStatus.textContent, /索引已变化，请重新搜索/);
  elements.reuseQuery.value = ''; const beforeEmpty = calls.length; await api.search();
  assert.equal(calls.length, beforeEmpty);
  fetcher = async () => response({items: []}); elements.reuseQuery.value = 'not found'; await api.search();
  assert.match(elements.searchStatus.textContent, /没有匹配结果/);

  // Project and file filters are explicit, and stale project responses never overwrite a new choice.
  api.state.pages.projects.items = [{project: '/work/a', label: 'a'}];
  fetcher = async () => response({items: [base]});
  await api.selectProject('/work/a');
  assert.equal(elements.projectsView.hidden, false);
  assert.equal(elements.timelineSection.hidden, false);
  assert.equal(elements.selectionPanel.hidden, false);
  assert.equal(new URL(api.historyLink({id: 'fallback'}, '会话').href, 'http://local').searchParams.get('project'), '/work/a');
  assert.equal(new URL(api.historyLink({id: 'unbound', project: ''}, '会话').href, 'http://local').searchParams.get('project'), '');
  assert.equal(new URL(calls.at(-1)[0], 'http://local').searchParams.get('project'), '/work/a');
  elements.timelineFile.value = 'src/parser.py'; await api.timeline();
  const fileUrl = new URL(calls.at(-1)[0], 'http://local');
  assert.equal(fileUrl.searchParams.get('project'), '/work/a');
  assert.equal(fileUrl.searchParams.get('file'), 'src/parser.py');
  const oldTimeline = deferred(); fetcher = () => oldTimeline.promise;
  const oldProject = api.selectProject('/work/old');
  fetcher = async () => response({items: [{...base, title: 'new project'}]});
  await api.selectProject('/work/new');
  oldTimeline.resolve(response({items: [{...base, title: 'old project'}]})); await oldProject;
  assert.match(flatten(elements.timelineResults), /new project/);
  assert.doesNotMatch(flatten(elements.timelineResults), /old project/);
  assert.equal(elements.timelineFile.value, '');
  await api.selectProject('');
  const unboundUrl = new URL(calls.at(-1)[0], 'http://local');
  assert.equal(unboundUrl.searchParams.has('project'), true);
  assert.equal(unboundUrl.searchParams.get('project'), '');
  assert.equal(elements.timelineTitle.textContent, '未绑定项目的历史');
  elements.timelineFile.value = 'lost.py'; await api.timeline();
  assert.equal(new URL(calls.at(-1)[0], 'http://local').searchParams.get('project'), '');
  let prevented = false;
  elements.projectsTab.listeners.keydown({key: 'ArrowLeft', preventDefault() { prevented = true; }});
  assert.equal(prevented, true); assert.equal(document.activeElement, elements.searchTab);
  assert.equal(elements.searchTab.getAttribute('aria-selected'), 'true');
  elements.searchTab.listeners.keydown({key: 'Home', preventDefault() {}});
  assert.equal(document.activeElement, elements.projectsTab);
  assert.equal(elements.timelineSection.hidden, true);
  assert.equal(api.state.project, null);
  assert.equal(elements.selectionPanel.hidden, true);
  assert.equal(browserLocation.search, '', 'project homepage clears the search URL');
  elements.projectsTab.listeners.keydown({key: 'End', preventDefault() {}});
  assert.equal(document.activeElement, elements.searchTab);

  // Evidence expansion is explicitly requested, and closing cancels its outstanding response.
  const result = api.searchResult(base, 'term'); body.append(result);
  const expand = walk(result).find(node => node.tag === 'button' && node.textContent === '查看并选择证据');
  fetcher = async () => response({...base}); await expand.click();
  assert.equal(expand.getAttribute('aria-expanded'), 'true');
  assert.match(flatten(result), /审计事件 3/);
  assert.match(calls.at(-1)[0], /\/api\/reuse\/evidence\?/);
  assert.equal(new URL(calls.at(-1)[0], 'http://local').searchParams.get('session'), base.id);
  assert.equal(new URL(calls.at(-1)[0], 'http://local').searchParams.get('source_revision'), 'index-revision-1');
  await expand.click();
  const pendingEvidence = deferred(); fetcher = () => pendingEvidence.promise;
  const openPending = expand.click(); await expand.click();
  pendingEvidence.resolve(response({...base, title: 'late'})); await openPending;
  assert.equal(expand.getAttribute('aria-expanded'), 'false');

  fetcher = async () => response({...base, evidence_status: 'error', error_code: 'index_revision_changed'});
  await expand.click();
  assert.match(flatten(result), /证据读取失败/);
  assert.match(flatten(result), /索引已变化，请重新搜索/);
  assert.equal(walk(result).filter(node => node.type === 'checkbox').length, 0);

  // A hit outside the bounded audit list remains selectable as a complete message, never as a fake summary.
  const later = api.searchResult({...base, snippets: [{message_index: 99, text: 'brief hit only', role: 'assistant'}]}, 'hit'); body.append(later);
  const laterButton = walk(later).find(node => node.tag === 'button' && node.textContent === '查看并选择证据');
  fetcher = async () => response({...base, evidence: Array.from({length: 10}, (_, index) => ({id: `first-${index}`, message_index: index, summary: `summary ${index}`}))});
  await laterButton.click();
  const messageChoice = walk(later).find(node => node.type === 'checkbox' && JSON.parse(node.dataset.evidenceSelection)[4] === null);
  assert.ok(messageChoice); assert.equal(messageChoice.disabled, false);
  assert.match(flatten(later), /完整消息 99/);
  assert.match(flatten(later), /合计超过 8000 字符会明确拒绝/);
  assert.match(flatten(later), /审计摘要（导出摘要）/);
  const beforeMessageSelect = calls.length; messageChoice.checked = true; messageChoice.listeners.change();
  assert.equal(calls.length, beforeMessageSelect);
  const chosenMessage = Array.from(api.state.selected.values())[0].selection;
  assert.equal(chosenMessage.message_index, 99);
  assert.equal(chosenMessage.evidence_id, undefined);
  assert.match(flatten(elements.selectionList), /将导出完整消息 99/);
  let messageRequest;
  fetcher = async (_url, options) => { messageRequest = JSON.parse(options.body); return response({items: messageRequest.selections, markdown: 'complete verified message body', authorization: 'context_only'}); };
  await api.previewSelection();
  assert.equal(Object.hasOwn(messageRequest.selections[0], 'evidence_id'), false);
  assert.equal(messageRequest.selections[0].message_index, 99);
  assert.equal(elements.selectionMarkdown.textContent, 'complete verified message body');
  fetcher = async () => failed('selection_body_limit_exceeded'); await api.previewSelection();
  assert.equal(elements.selectionExport.hidden, true);
  assert.match(elements.selectionStatus.textContent, /超出 8000 字符导出上限，未截断导出/);
  elements.selectionClear.click();
  const boundedMessages = api.matchingMessages({...base, provenance: {...base.provenance, truncated: true}}, base.snippets, 'hit');
  assert.equal(walk(boundedMessages).find(node => node.type === 'checkbox').disabled, true);
  const matchedHref = walk(later).filter(node => node.tag === 'a').find(node => node.textContent === '核对完整消息').href;
  assert.equal(new URL(matchedHref, 'http://local').searchParams.get('source_revision'), 'index-revision-1');

  // Selections have a hard cap, source identity/revisions, and no implicit generation.
  const beforeSelect = calls.length;
  for (let i = 0; i < 5; i++) assert.equal(api.toggleSelection({...base, id: `session-${i}`}, {...base.evidence[0], id: `e${i}`}, true), true);
  assert.equal(api.toggleSelection({...base, id: 'sixth'}, {...base.evidence[0], id: 'e6'}, true), false);
  assert.equal(api.state.selected.size, 5);
  assert.equal(calls.length, beforeSelect);
  assert.match(elements.selectionStatus.textContent, /最多选择 5 条/);
  let sent;
  fetcher = async (url, options) => { sent = JSON.parse(options.body); return response({items: sent.selections, markdown: '# Selected <script>', authorization: 'context_only'}); };
  await api.previewSelection();
  assert.equal(sent.selections.length, 5);
  assert.equal(sent.selections[0].content_revision, base.provenance.content_revision);
  assert.equal(sent.selections[0].context_revision, base.provenance.context_revision);
  assert.equal(sent.selections[0].system, 'linux');
  assert.equal(elements.selectionExport.hidden, false);
  assert.equal(elements.selectionMarkdown.textContent, '# Selected <script>');
  await api.copySelection(); assert.equal(clipboard.at(-1), '# Selected <script>');
  api.downloadSelection('md'); api.downloadSelection('json'); assert.equal(downloads.length, 2);
  copyFails = true; await api.copySelection(); assert.match(elements.selectionStatus.textContent, /浏览器未允许复制/); copyFails = false;
  api.toggleSelection({...base, id: 'session-0'}, {...base.evidence[0], id: 'e0'}, false);
  assert.equal(elements.selectionExport.hidden, true);
  api.downloadSelection('md'); assert.equal(downloads.length, 2);
  const oldPreview = deferred(); fetcher = () => oldPreview.promise;
  const awaiting = api.previewSelection();
  api.toggleSelection({...base, id: 'session-1'}, {...base.evidence[0], id: 'e1'}, false);
  oldPreview.resolve(response({items: [], markdown: 'stale', authorization: 'context_only'})); await awaiting;
  assert.equal(elements.selectionExport.hidden, true);
  assert.equal(api.state.preview, null);
  fetcher = async () => failed('source_changed_since_index'); await api.previewSelection();
  assert.match(elements.selectionStatus.textContent, /来源内容已变化，请重新搜索并重新选择证据/);
  assert.equal(elements.selectionExport.hidden, true);

  // Source statuses offer specific recovery steps; indexing and unsupported sources cannot refresh.
  const sourceStates = ['not_found', 'unreadable', 'unsupported', 'indexing', 'unknown', 'ready', 'empty', 'stale', 'error'];
  api.renderHealth({sources: sourceStates.map(status => ({system: 'linux', source: status, status}))});
  for (const expected of ['路径不存在', '没有读取权限', '来源格式暂不支持', '正在建立索引', '状态未知', '更改启动配置后重新启动', '读取权限', '无需重复刷新', '刷新此来源', '暂无已索引记录']) assert.ok(flatten(elements.sourceStatus).includes(expected));
  for (const status of ['indexing', 'unsupported']) {
    const sourceRow = elements.sourceStatus.children.find(node => node.children[0].textContent.startsWith(status + ' /'));
    assert.equal(sourceRow.children.find(node => node.tag === 'button').disabled, true);
  }
  // Diagnosis is only downloadable after an explicit preview; health failures clear it.
  api.renderHealth({demo: true, version: '1.2.0', sources: [{system: 'linux', source: 'codex', status: 'readable', count: 8, path: '/local/private', last_refreshed_at: now}, {system: 'linux', source: '<script>', status: 'missing', error_code: 'not_found', next_step: '检查路径', command: 'cchv --demo'}], diagnostic: {sources: [{source: 'codex', count: 8}]}});
  assert.equal(elements.demoNotice.hidden, false);
  assert.match(flatten(elements.sourceStatus), /<script>/);
  assert.match(flatten(elements.sourceStatus), /检查路径/);
  const downloadCount = downloads.length; elements.diagnosticDownload.click(); assert.equal(downloads.length, downloadCount);
  api.previewDiagnostic(); assert.equal(elements.diagnosticPreview.hidden, false);
  elements.diagnosticDownload.click(); assert.equal(downloads.length, downloadCount + 1);
  assert.doesNotMatch(elements.diagnosticText.textContent, /\/local\/private/);
  const oldHealth = deferred(); fetcher = () => oldHealth.promise; const pendingHealth = api.loadHealth();
  fetcher = async () => response({sources: [], version: 'new'}); await api.loadHealth();
  oldHealth.resolve(response({sources: [], version: 'old'})); await pendingHealth;
  assert.match(elements.workspaceStatus.textContent, /new/); assert.doesNotMatch(elements.workspaceStatus.textContent, /old/);
  fetcher = async () => failed('offline'); await api.loadHealth();
  assert.equal(elements.sourceStatus.children.length, 0);
  assert.equal(elements.diagnosticPreview.hidden, true); assert.equal(elements.diagnosticPreviewBtn.disabled, true);
  assert.match(elements.workspaceStatus.textContent, /来源检查失败/);
  // Returning from a transcript restores every submitted filter and waits for source discovery first.
  browserLocation.search = '?q=back%20to%20work&source=claude&project=%2Fwork%2Fa&start=2026-09-01&end=2026-09-22';
  api.state.pages.search.sequence = 0;
  const healthReady = deferred();
  const beforeBoot = calls.length;
  fetcher = async url => url === '/api/reuse/health' ? healthReady.promise : response({items: [base]});
  const restoring = api.bootstrapWorkspace();
  await flush(); assert.equal(calls.length, beforeBoot + 1, 'restore waits for health before searching');
  healthReady.resolve(response({sources: [{source: 'codex', status: 'ready'}]})); await restoring;
  const restored = new URL(calls.at(-1)[0], 'http://local');
  for (const [key, value] of [['q', 'back to work'], ['source', 'claude'], ['project', '/work/a'], ['start', '2026-09-01'], ['end', '2026-09-22']]) assert.equal(restored.searchParams.get(key), value);
  assert.equal(elements.reuseSource.value, 'claude', 'an unavailable restored source must not silently become all sources');
  assert.ok(elements.reuseSource.children.some(option => option.value === 'claude'));
  api.renderHealth({sources: [{source: 'codex', status: 'ready'}]});
  assert.equal(elements.reuseSource.value, 'claude', 'rechecking sources preserves explicit filter intent');
  // Explicit search URLs without a query show the single search entry without an empty request.
  browserLocation.search = '?view=search';
  api.state.pages.search.sequence = 0;
  fetcher = async () => response({sources: []});
  const beforeSearchHome = calls.length;
  await api.bootstrapWorkspace();
  assert.equal(calls.length, beforeSearchHome + 1);
  assert.equal(api.state.view, 'search');
  assert.equal(elements.reuseQuery.value, '');
  assert.equal(elements.searchView.hidden, false);
  assert.equal(elements.projectsView.hidden, true);
  assert.equal(api.restoreSearchFromUrl('?q='), true, 'legacy query URLs retain search intent even when empty');
  api.state.selected.clear();
  api.showProjects();
  assert.equal(elements.selectionPanel.hidden, true);
  assert.match(elements.reuseLayout.className, /projects-home/);
  console.log('workspace: unified retrieval, safe snippets/deep links, project/file timeline, revision-bound selections, preview/export, diagnosis, keyboard and response races passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
