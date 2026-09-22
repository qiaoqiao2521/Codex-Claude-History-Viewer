const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

// loadApp() replaces globalThis.process with a stub; keep the real one for
// exit-code signalling.
const nodeProcess = process;


class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...tokens) { tokens.forEach((t) => this.values.add(t)); }
  remove(...tokens) { tokens.forEach((t) => this.values.delete(t)); }
  toggle(token, force) {
    if (force === true) { this.values.add(token); return true; }
    if (force === false) { this.values.delete(token); return false; }
    if (this.values.has(token)) { this.values.delete(token); return false; }
    this.values.add(token); return true;
  }
  contains(token) { return this.values.has(token); }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = { setProperty(name, value) { this[name] = value; } };
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.eventListeners = new Map();
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.checked = true;
    this.parentNode = null;
    this.ownerDocument = null;
    this._rect = { top: 0, bottom: 0, width: 960, height: 640 };
  }
  appendChild(child) {
    if (!child) return child;
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = String(value);
    }
  }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(type, handler) { this.eventListeners.set(type, handler); }
  removeEventListener(type) { this.eventListeners.delete(type); }
  focus() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  scrollIntoView() {}
  scrollTo(value) {
    if (typeof value === "number") { this.scrollTop = value; return; }
    if (value && typeof value === "object" && Number.isFinite(value.top)) { this.scrollTop = value.top; }
  }
  getBoundingClientRect() { return this._rect; }
}

function createStorage() {
  const store = new Map();
  return {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); },
    clear() { store.clear(); },
  };
}

function createDocument() {
  const elements = new Map();
  const documentElement = new FakeElement("html");
  documentElement.dataset = {};
  const body = new FakeElement("body");
  const fakeWindow = {
    eventListeners: new Map(),
    addEventListener(type, callback) { this.eventListeners.set(type, callback); },
    removeEventListener() {},
    requestAnimationFrame(callback) { queueMicrotask(callback); return 1; },
    cancelAnimationFrame() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    ResizeObserver: null,
    performance: { now: () => Date.now() },
    location: { search: "", pathname: "/", origin: "http://localhost" },
    history: {
      writes: [],
      pushState(_state, _title, url) { this.writes.push(["push", url]); fakeWindow.location.search = url.includes("?") ? url.slice(url.indexOf("?")) : ""; },
      replaceState(_state, _title, url) { this.writes.push(["replace", url]); fakeWindow.location.search = url.includes("?") ? url.slice(url.indexOf("?")) : ""; },
    },
  };
  documentElement.ownerDocument = { defaultView: fakeWindow };
  body.ownerDocument = { defaultView: fakeWindow };
  const roleInputs = ["user", "assistant", "system", "developer", "tool", "other"].map((role) => {
    const input = new FakeElement("input");
    input.dataset.role = role;
    input.checked = true;
    input.ownerDocument = { defaultView: fakeWindow };
    return input;
  });

  const document = {
    documentElement,
    body,
    defaultView: fakeWindow,
    getElementById(id) {
      if (!elements.has(id)) {
        const el = new FakeElement(["readerProject", "readerSource"].includes(id) ? "select" : "div");
        el.ownerDocument = document;
        elements.set(id, el);
      }
      return elements.get(id);
    },
    querySelectorAll(selector) {
      if (selector === ".roles input[type=checkbox]") return roleInputs;
      return [];
    },
    createElement(tagName) {
      const el = new FakeElement(tagName);
      el.ownerDocument = document;
      return el;
    },
    createDocumentFragment() {
      const el = new FakeElement("#fragment");
      el.ownerDocument = document;
      return el;
    },
    createTextNode(text) {
      return { nodeValue: String(text), textContent: String(text), parentNode: null };
    },
    createTreeWalker() { return { nextNode() { return null; } }; },
  };
  fakeWindow.document = document;
  return document;
}

async function loadApp({ fetchImpl, search = "", preferences = {} } = {}) {
  const repoDir = path.resolve(__dirname, "..");
  const sourcePath = path.join(repoDir, "static", "app.js");
  const localStorage = createStorage();
  const document = createDocument();
  document.defaultView.location = { pathname: "/history", search };
  document.defaultView.HVSettings = { getPreferences: () => preferences };
  // renderSessionHeader needs a working querySelector on the session header.
  const sessionTitleEl = new FakeElement("div");
  const sessionMetaEl = new FakeElement("div");
  const sessionHeaderEl = document.getElementById("sessionHeader");
  sessionHeaderEl.querySelector = (selector) => {
    if (selector === ".session-title") return sessionTitleEl;
    if (selector === ".session-meta") return sessionMetaEl;
    return null;
  };
  const defaultFetch = async () => ({
    ok: true,
    json: async () => ({ items: [], next_cursor: null, pagination_status: 'available', next_offset: 0, matches: [] }),
  });
  // Node 22 exposes a getter-only navigator; replace it for this DOM fixture.
  Object.defineProperty(globalThis, "navigator", { value: {}, writable: true, configurable: true });
  Object.assign(globalThis, {
    __CCHV_TEST__: true,
    __testApi: undefined,
    document,
    localStorage,
    navigator: { clipboard: { writeText: async () => {} } },
    window: document.defaultView,
    fetch: (...args) => (fetchImpl ? fetchImpl(...args) : defaultFetch()),
    requestAnimationFrame(callback) { queueMicrotask(callback); return 1; },
    cancelAnimationFrame() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    alert() {},
    URLSearchParams,
    Element: FakeElement,
    NodeFilter: { SHOW_TEXT: 4 },
    IntersectionObserver: class { observe() {} unobserve() {} disconnect() {} },
    process: { env: { NODE_ENV: "test" } },
  });

  const href = `${pathToFileURL(sourcePath).href}?test=${Date.now()}-${Math.random()}`;
  await import(href);
  await flushAsync();
  return { api: globalThis.__testApi, localStorage, document, window: document.defaultView };
}

function flushAsync() {
  return new Promise((resolve) => setImmediate(resolve));
}

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}
function row(source, id = 'same-id', project = '/work/project', updated = 200) {
  return { system: 'linux', source, id, project, title: `${source} conversation`, updated_at: updated, source_revision: `rev-${source}` };
}
function fixture({ sessions, projects, intercept } = {}) {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    const parsed = new URL(url, 'http://localhost');
    if (intercept) {
      const value = intercept(parsed);
      if (value !== undefined) return value;
    }
    if (parsed.pathname === '/api/sources') return response({ runtime_system: 'linux', sources: ['codex', 'claude', 'codebuddy'].map(source => ({ system: 'linux', source, read_only: true })) });
    if (parsed.pathname === '/api/reuse/projects') return response({ items: projects || [{ project: '/work/project', session_count: 2 }], next_cursor: null, pagination_status: 'available' });
    if (parsed.pathname === '/api/reuse/sessions') return response({ items: sessions || [row('codex'), row('codebuddy')], next_cursor: null, pagination_status: 'available' });
    if (parsed.pathname.endsWith('/audit')) return response({}, 404);
    if (parsed.pathname.endsWith('/messages')) return response({ messages: [], total: 0, offset: 0 });
    const match = parsed.pathname.match(/^\/api\/([^/]+)\/([^/]+)\/session\/([^/]+)$/);
    if (match) return response({ session: { id: match[3], cwd: '/work/project', title: `${match[2]} conversation`, message_count: 0 } });
    return response({ items: [] });
  };
  return { calls, fetchImpl };
}

async function run() {
  const basic = fixture();
  let app = await loadApp(basic);
  assert.equal(app.api.getReaderState().project, null);
  assert.equal(basic.calls.some(url => /\/sessions\?/.test(url)), false, 'fresh reader waits for project selection');
  assert.match(app.document.getElementById('messages').children.at(-1).textContent, /选择项目/);
  await app.api.chooseReaderProject('/work/project');
  assert.equal(app.api.getCurrentSession().title, 'codex conversation', 'latest project session opens automatically');
  assert.equal(new URLSearchParams(app.window.location.search).get('project'), '/work/project');
  assert.equal(basic.calls.filter(url => url.startsWith('/api/reuse/sessions?')).length, 1);
  assert.equal(app.api.getReaderState().items.length, 2, 'same session ID from different providers is retained');
  await app.api.openReaderSession(row('codebuddy'));
  assert.equal(app.api.getCurrentSession().title, 'codebuddy conversation');
  assert.equal(new URLSearchParams(app.window.location.search).get('source'), 'codebuddy');
  assert.match(app.api.getReaderState().activeKey, /codebuddy/);
  assert.equal(basic.calls.some(url => /^\/api\/linux\/[^/]+\/sessions/.test(url)), false, 'project reader never calls old global list');

  const exactProject = '/work/项目 with "quotes"';
  const encoded = fixture({ sessions: [] });
  app = await loadApp(encoded);
  await app.api.chooseReaderProject(exactProject, { source: 'codebuddy' });
  const encodedRequest = new URL(encoded.calls.find(url => url.startsWith('/api/reuse/sessions?')), 'http://localhost');
  assert.equal(encodedRequest.searchParams.get('project'), exactProject);
  assert.equal(encodedRequest.searchParams.get('source'), 'codebuddy');
  await app.api.chooseReaderProject('');
  assert.equal(app.api.getReaderState().project, '', 'unbound project is a real group, not the choose placeholder');
  assert.equal(app.api.getReaderState().source, '', 'changing project resets source filter');
  assert.equal(new URLSearchParams(app.window.location.search).get('project'), '');

  const restore = fixture();
  app = await loadApp({ ...restore, search: '?project=%2Fwork%2Fproject' });
  await flushAsync();
  assert.equal(app.api.getCurrentSession().title, 'codex conversation');
  assert.equal(app.window.history.writes.some(([method]) => method === 'push'), false, 'bootstrap replaces rather than creates navigation history');
  app.window.location.search = '?project=';
  await app.window.eventListeners.get('popstate')();
  assert.equal(app.api.getReaderState().project, '');

  const deep = fixture();
  app = await loadApp({ ...deep, search: '?system=linux&source=codebuddy&session=same-id&source_revision=deep-rev&message=0&q=needle' });
  await flushAsync();
  assert.equal(app.api.getReaderState().project, '/work/project', 'legacy deep link associates the conversation with cwd');
  assert.equal(app.api.getCurrentSession().title, 'codebuddy conversation');
  assert.equal(deep.calls.some(url => url.includes('/codebuddy/session/same-id?source_revision=deep-rev')), true);
  assert.equal(new URLSearchParams(app.window.location.search).get('q'), 'needle', 'original evidence context survives initial deep link');
  await app.api.openReaderSession(row('codex'));
  assert.equal(new URLSearchParams(app.window.location.search).has('q'), false);
  assert.equal(new URLSearchParams(app.window.location.search).has('message'), false);

  let resolveSlow;
  const race = fixture({ intercept(url) {
    if (url.pathname === '/api/reuse/sessions' && url.searchParams.get('project') === '/slow') {
      return new Promise(resolve => { resolveSlow = resolve; });
    }
    if (url.pathname === '/api/reuse/sessions') return response({ items: [row('codebuddy', 'fast', '/fast')], next_cursor: null, pagination_status: 'available' });
  } });
  app = await loadApp(race);
  const slow = app.api.chooseReaderProject('/slow');
  await app.api.chooseReaderProject('/fast');
  resolveSlow(response({ items: [row('codex', 'stale', '/slow')], next_cursor: null, pagination_status: 'available' }));
  await slow;
  assert.equal(app.api.getReaderState().project, '/fast');
  assert.equal(app.api.getCurrentSession().id, 'fast');
  assert.equal(app.api.getReaderState().items[0].id, 'fast');

  let resolveOldSession;
  const sessionRace = fixture({ intercept(url) {
    if (url.pathname === '/api/linux/codex/session/old') return new Promise(resolve => { resolveOldSession = resolve; });
  } });
  app = await loadApp(sessionRace);
  const old = app.api.openReaderSession(row('codex', 'old'));
  await app.api.openReaderSession(row('codebuddy', 'new'));
  resolveOldSession(response({}, 409));
  await old;
  assert.equal(app.api.getCurrentSession().id, 'new', 'stale HTTP error must not overwrite a newer conversation');
  assert.equal(app.document.getElementById('messages').children.some(item => /索引已变化/.test(item.textContent)), false);

  let page = 0;
  const paging = fixture({ intercept(url) {
    if (url.pathname === '/api/reuse/sessions') {
      ++page;
      if (page === 1) return response({ items: [row('codex')], next_cursor: 'bound-cursor', pagination_status: 'available' });
      assert.equal(url.searchParams.get('cursor'), 'bound-cursor');
      return response({ items: [row('codebuddy')], next_cursor: null, pagination_status: 'available' });
    }
  } });
  app = await loadApp(paging);
  await app.api.chooseReaderProject('/work/project');
  await app.api.fetchReaderSessions({ append: true });
  assert.equal(app.api.getReaderState().items.length, 2);
  assert.equal(app.api.getReaderState().cursor, '');

  app = await loadApp({ ...fixture(), preferences: { fontSize: 17, toolsCollapsed: false, auditExpanded: true } });
  await app.api.chooseReaderProject('/work/project');
  assert.equal(app.api.getToolsCollapsedByDefault(), false, 'tool setting survives opening a conversation');
  assert.equal(app.document.getElementById('sessionReview').open, true);
  assert.equal(app.document.getElementById('messages').style['--reader-font-size'], '17px');
  app.api.setConversationFind(true);
  assert.equal(app.document.getElementById('conversationFind').hidden, false);
  app.api.setConversationFind(false);
  assert.equal(app.document.getElementById('conversationFind').hidden, true);
  assert.equal(app.document.body.classList.contains('reader-has-session'), true);
  app.document.getElementById('readerToggleList').eventListeners.get('click')();
  assert.equal(app.document.body.classList.contains('reader-show-list'), true);
  assert.equal(app.document.getElementById('readerToggleList').getAttribute('aria-expanded'), 'true');
  await app.api.openReaderSession(row('codebuddy'));
  assert.equal(app.document.body.classList.contains('reader-show-list'), false, 'mobile list closes after conversation selection');

  let projectPages = 0;
  const manyProjects = fixture({ intercept(url) {
    if (url.pathname !== '/api/reuse/projects') return undefined;
    assert.equal(url.searchParams.get('limit'), '20', 'cross-source project API caps each page at 20');
    projectPages++;
    if (projectPages === 1) return response({ items: Array.from({length: 20}, (_, n) => ({project: `/project-${n}`})), next_cursor: 'project-cursor', pagination_status: 'available' });
    assert.equal(url.searchParams.get('cursor'), 'project-cursor');
    return response({ items: [{project: '/project-20'}], next_cursor: null, pagination_status: 'available' });
  } });
  app = await loadApp(manyProjects);
  assert.equal(app.document.getElementById('readerProjectsMore').hidden, false);
  await app.api.loadReaderProjects({append: true});
  assert.deepEqual(app.api.getReaderState().projects.map(row => row.project), Array.from({length: 21}, (_, n) => `/project-${n}`));
  assert.equal(app.document.getElementById('readerProjectsMore').hidden, true);

  let failPage = true;
  const stalePage = fixture({ intercept(url) {
    if (url.pathname !== '/api/reuse/sessions') return undefined;
    if (url.searchParams.has('cursor') && failPage) return response({}, 409);
    return response({items: [row('codex')], next_cursor: 'old-cursor', pagination_status: 'available'});
  } });
  app = await loadApp(stalePage);
  await app.api.chooseReaderProject('/work/project');
  await app.api.fetchReaderSessions({append: true});
  assert.equal(app.api.getReaderState().items.length, 1, 'expired pagination leaves previous rows visible');
  assert.match(app.document.getElementById('readerListStatus').textContent, /索引已变化/);
  failPage = false;
  await app.document.getElementById('readerListStatus').children.at(-1).eventListeners.get('click')();
  assert.equal(app.api.getReaderState().items.length, 1, 'refresh restarts pagination instead of duplicating old rows');
  const failedSource = fixture({ intercept(url) {
    if (url.pathname === '/api/reuse/projects') return response({items: [{project: '/partial'}], next_cursor: 'must-not-follow', pagination_status: 'restart_after_source_error', partial: true, errors: [{source: 'codex', error: 'unavailable'}]});
    if (url.pathname === '/api/reuse/sessions') return response({items: [row('codex')], next_cursor: 'must-not-follow', pagination_status: 'restart_after_source_error', partial: true, errors: [{source: 'codex', error: 'unavailable'}]});
  } });
  app = await loadApp(failedSource);
  assert.equal(app.document.getElementById('readerProjectsMore').hidden, true, 'source error blocks project pagination even if response carries a cursor');
  const beforeProjects = failedSource.calls.length;
  await app.api.loadReaderProjects({append: true});
  assert.equal(failedSource.calls.length, beforeProjects);
  await app.api.chooseReaderProject('/partial');
  assert.equal(app.api.getReaderState().cursor, '', 'source error blocks session pagination');
  const beforeSessions = failedSource.calls.length;
  await app.api.fetchReaderSessions({append: true});
  assert.equal(failedSource.calls.length, beforeSessions);
  const limitedContent = fixture({ intercept(url) {
    const warning = {partial: true, errors: [], content_warnings: [{source: 'agy', status: 'partial'}], pagination_status: 'available'};
    if (url.pathname === '/api/reuse/projects') return response({...warning, items: [{project: '/decoded'}], next_cursor: 'project-more'});
    if (url.pathname === '/api/reuse/sessions') return response({...warning, items: [row('codex')], next_cursor: 'session-more'});
  } });
  app = await loadApp(limitedContent);
  assert.match(app.document.getElementById('readerListStatus').textContent, /部分历史正文未完整解码/);
  assert.equal(app.document.getElementById('readerProjectsMore').hidden, false, 'coverage warning retains project pagination');
  await app.api.chooseReaderProject('/decoded');
  assert.match(app.document.getElementById('readerListStatus').textContent, /部分历史正文未完整解码/);
  assert.doesNotMatch(app.document.getElementById('readerListStatus').textContent, /来源暂不可用/);
  assert.equal(app.api.getReaderState().cursor, 'session-more', 'coverage warning retains session pagination');
  const insightNavigation = fixture({ intercept(url) {
    const sessionId = url.pathname.split('/').at(-1);
    if (['usage-other', 'briefing-other'].includes(sessionId)) {
      return response({session: {id: sessionId, cwd: `/work/${sessionId}`, title: sessionId, message_count: 0}});
    }
    if (url.pathname === '/api/reuse/sessions' && url.searchParams.get('project') !== '/work/project') {
      const project = url.searchParams.get('project');
      return response({items: [row('codex', project.split('/').at(-1), project)], next_cursor: null, pagination_status: 'available'});
    }
  } });
  app = await loadApp(insightNavigation);
  await app.api.chooseReaderProject('/work/project');
  for (const [panel, sessionId] of [['usageContent', 'usage-other'], ['briefingContent', 'briefing-other']]) {
    const clicked = new FakeElement('div');
    clicked.dataset.usageSession = sessionId;
    clicked.closest = selector => selector === '[data-usage-session]' ? clicked : null;
    const pushCount = app.window.history.writes.filter(([method]) => method === 'push').length;
    await app.document.getElementById(panel).eventListeners.get('click')({target: clicked});
    assert.equal(app.api.getCurrentSession().id, sessionId);
    assert.equal(app.api.getReaderState().project, `/work/${sessionId}`, `${panel} infers target project from actual session cwd`);
    assert.equal(app.api.getReaderState().items[0].id, sessionId);
    assert.equal(app.api.getReaderState().activeKey, app.api.readerSessionKey(row('codex', sessionId)));
    const target = new URLSearchParams(app.window.location.search);
    assert.equal(target.get('session'), sessionId);
    assert.equal(target.get('project'), `/work/${sessionId}`);
    assert.equal(target.get('source'), 'codex');
    assert.equal(target.get('system'), 'linux');
    assert.equal(target.has('message'), false);
    assert.equal(app.window.history.writes.filter(([method]) => method === 'push').length, pushCount + 1);
    await app.api.restoreReaderLocation();
    assert.equal(app.api.getCurrentSession().id, sessionId, 'refresh resolves the conversation opened from insight panel');
  }
  console.log('Project reader navigation: 14 scenarios passed');
}
run().catch(err => { console.error(err); nodeProcess.exitCode = 1; });
