'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const settingsCode = fs.readFileSync(path.join(root, 'static/settings.js'), 'utf8');
const appCode = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8').replace(/^export \{\};/, '');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const keys = {theme: 'historyViewer.ui.codeTheme', roles: 'historyViewer.ui.roleFilters', reader: 'historyViewer.ui.readerPreferences'};
const flush = async () => { for (let n = 0; n < 5; n++) await new Promise(resolve => setImmediate(resolve)); };
const response = (data, ok = true) => ({ok, status: ok ? 200 : 500, json: async () => data});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };

function fixture({reader = true, stored = {}, storageBlocked = false, fetcher} = {}) {
  const storage = new Map(Object.entries(stored)), events = [], requests = [];
  let document;
  class EventTarget {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, callback) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(callback);
    }
    removeEventListener(type, callback) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter(item => item !== callback));
    }
    dispatchEvent(event) {
      event.target ||= this;
      event.preventDefault ||= () => { event.defaultPrevented = true; };
      for (const callback of this.listeners.get(event.type) || []) callback(event);
      return !event.defaultPrevented;
    }
    async fire(type, extra = {}) {
      const event = {type, target: this, preventDefault() { this.defaultPrevented = true; }, ...extra};
      for (const callback of this.listeners.get(type) || []) await callback(event);
      return event;
    }
  }
  const walk = node => node.children.flatMap(child => [child, ...walk(child)]);
  const matches = (node, selector) => {
    if (selector === '.roles input[type=checkbox]') return node.tagName === 'INPUT' && node.dataset.role;
    if (selector.startsWith('#')) return node.id === selector.slice(1);
    if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
    const attribute = /^\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/.exec(selector);
    if (attribute) return node.attributes.has(attribute[1]) && (attribute[2] === undefined || node.getAttribute(attribute[1]) === attribute[2]);
    return node.tagName === selector.toUpperCase();
  };
  class Element extends EventTarget {
    constructor(tag = 'div') {
      super(); this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
      this.attributes = new Map(); this.dataset = {}; this.style = {setProperty(key, value) { this[key] = value; }};
      this.value = ''; this.checked = false; this.hidden = false; this.disabled = false; this.open = false;
      this._text = ''; this._classes = new Set(); this.clientWidth = 1200; this.clientHeight = 800;
      this.offsetWidth = 1200; this.scrollHeight = 800; this.scrollTop = 0;
      this.classList = {
        contains: value => this._classes.has(value),
        add: (...values) => values.forEach(value => this._classes.add(value)),
        remove: (...values) => values.forEach(value => this._classes.delete(value)),
        toggle: (value, force) => {
          const enabled = force === undefined ? !this._classes.has(value) : force;
          if (enabled) this._classes.add(value); else this._classes.delete(value);
          return enabled;
        },
      };
    }
    get ownerDocument() { return document; }
    get isConnected() { return this === document.body || !!this.parentNode?.isConnected; }
    get className() { return [...this._classes].join(' '); }
    set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this.replaceChildren(); this._text = String(value); }
    get innerHTML() { return this._html || ''; }
    set innerHTML(value) {
      this.replaceChildren(); this._html = String(value);
      // Parse the real static markup so settings and app.js bind the same nodes.
      const stack = [this], voidTags = new Set(['input', 'meta', 'link', 'br', 'hr']);
      for (const token of this._html.matchAll(/<\/?([\w-]+)([^>]*)>|([^<]+)/g)) {
        if (!token[1]) { stack.at(-1)._text += token[3]; continue; }
        const tag = token[1].toLowerCase();
        if (token[0][1] === '/') { if (stack.length > 1) stack.pop(); continue; }
        const node = new Element(tag);
        for (const attr of token[2].matchAll(/([\w-]+)(?:="([^"]*)"|'([^']*)'|=([^\s]+))?/g)) {
          node.setAttribute(attr[1], attr[2] ?? attr[3] ?? attr[4] ?? '');
        }
        stack.at(-1).append(node);
        if (!voidTags.has(tag)) stack.push(node);
      }
    }
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      if (name === 'id') this.id = String(value);
      if (name === 'class') this.className = value;
      if (name === 'checked') this.checked = true;
      if (name === 'hidden') this.hidden = true;
      if (name === 'type') this.type = value;
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = String(value);
    }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    append(...nodes) { for (const node of nodes) { node.parentNode = this; this.children.push(node); } }
    appendChild(node) { this.append(node); return node; }
    replaceChildren(...nodes) { for (const child of this.children) child.parentNode = null; this.children = []; this._text = ''; this.append(...nodes); }
    querySelectorAll(selector) { return walk(this).filter(node => matches(node, selector)); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { return matches(this, selector) ? this : this.parentNode?.closest(selector); }
    focus() { document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatchEvent({type: 'close'}); }
    escape() { if (this.dispatchEvent({type: 'cancel'})) this.close(); }
    click() { return this.disabled ? undefined : this.fire('click'); }
    getBoundingClientRect() { return {top: 0, bottom: 800, width: 1200, height: 800}; }
    scrollIntoView() {}
    scrollTo() {}
  }
  const window = new EventTarget();
  window.location = {search: '', pathname: '/history', origin: 'http://local'};
  window.history = {replaceState() {}, pushState() {}};
  window.performance = {now: () => 0};
  window.requestAnimationFrame = callback => { queueMicrotask(callback); return 1; };
  window.cancelAnimationFrame = () => {};
  document = {body: new Element('body'), documentElement: new Element('html'), defaultView: window,
    createElement: tag => new Element(tag),
    createDocumentFragment: () => new Element('fragment'),
    createTextNode: text => Object.assign(new Element('text'), {_text: text}),
    createTreeWalker: () => ({nextNode: () => null}),
    getElementById: id => document.body.querySelector('#' + id),
    querySelectorAll: selector => document.body.querySelectorAll(selector),
    querySelector: selector => document.body.querySelector(selector),
  };
  document.body.className = reader ? 'reader-page' : 'workspace-page';
  document.body.innerHTML = html.split('<body class="reader-page">')[1].split('</body>')[0];
  document.activeElement = document.getElementById('readerSettings');
  window.document = document;
  window.addEventListener('hv-preferences-change', event => events.push(event.detail));
  const localStorage = {
    getItem(key) { if (storageBlocked) throw new Error('SecurityError'); return storage.get(key) ?? null; },
    setItem(key, value) { if (storageBlocked) throw new Error('SecurityError'); storage.set(key, String(value)); },
    removeItem(key) { if (storageBlocked) throw new Error('SecurityError'); storage.delete(key); },
    key(index) { return [...storage.keys()][index] || null; },
    get length() { return storage.size; },
  };
  const context = vm.createContext({window, document, localStorage, Element, URLSearchParams,
    CustomEvent: class {constructor(type, options) { this.type = type; this.detail = options?.detail; }},
    fetch: async (url, options) => {
      requests.push([url, options]);
      if (fetcher) { const value = fetcher(url, options); if (value !== undefined) return value; }
      if (url === '/sources') return response({runtime_system: 'linux', sources: []});
      return response({sources: [], items: [], next_cursor: null, has_more: false});
    },
    navigator: {clipboard: {writeText: async () => {}}},
    requestAnimationFrame: window.requestAnimationFrame, cancelAnimationFrame() {},
    setTimeout: () => 1, clearTimeout() {}, queueMicrotask,
    IntersectionObserver: class {observe() {} unobserve() {} disconnect() {}},
    NodeFilter: {SHOW_TEXT: 4}, performance: window.performance,
    console, alert() {}, __CCHV_TEST__: true, process: {env: {NODE_ENV: 'test'}},
  });
  vm.runInContext(settingsCode, context, {filename: 'settings.js'});
  if (reader) vm.runInContext(appCode, context, {filename: 'app.js'});
  return {document, window, storage, events, requests, api: window.HVSettings,
    app: context.__testApi, get: id => document.getElementById(id), walk};
}

async function run() {
  const app = fixture({stored: {
    [keys.theme]: 'slate', [keys.roles]: JSON.stringify({tool: false}),
    [keys.reader]: JSON.stringify({fontSize: 16, toolsCollapsed: false, auditExpanded: true}),
  }});
  await flush();
  assert.equal(app.document.documentElement.dataset.codeTheme, 'slate');
  assert.equal(app.get('messages').style['--reader-font-size'], '16px');
  assert.equal(app.get('sessionReview').open, true);
  assert.equal(app.api.getPreferences().toolsCollapsed, false);
  assert.equal(app.get('readerSettingsDialog').querySelector('[data-role="tool"]').checked, false);
  assert.equal(app.get('clearRenderCache').hidden, false, 'created before app.js cache handler binds');
  assert.ok(app.get('clearRenderCache').listeners.get('click')?.length);

  const dialog = app.get('readerSettingsDialog');
  await dialog.querySelector('[data-code-theme="dark"]').click();
  assert.equal(app.storage.get(keys.theme), 'dark');
  assert.equal(app.document.documentElement.dataset.codeTheme, 'dark');
  assert.equal(app.app.getToolsCollapsedByDefault(), false);
  assert.equal(dialog.querySelector('[data-code-theme="dark"]').getAttribute('aria-pressed'), 'true');
  const tool = dialog.querySelector('[data-role="tool"]'); tool.checked = true; await tool.fire('change');
  assert.equal(JSON.parse(app.storage.get(keys.roles)).tool, true);
  app.get('readerFontSize').value = '18'; await app.get('readerFontSize').fire('change');
  assert.equal(app.get('messages').style['--reader-font-size'], '18px');
  app.get('readerToolsCollapsed').checked = true; await app.get('readerToolsCollapsed').fire('change');
  assert.equal(app.app.getToolsCollapsedByDefault(), true);
  assert.match(app.get('settingsSaveStatus').textContent, /已保存/);
  await app.get('settingsReset').click();
  assert.equal(app.document.documentElement.dataset.codeTheme, 'light');
  assert.equal(app.get('messages').style['--reader-font-size'], '14px');
  assert.equal(app.get('sessionReview').open, false);
  assert.ok(Object.values(app.api.getPreferences().roles).every(Boolean));

  app.get('readerSettings').focus(); app.api.open();
  assert.equal(app.document.activeElement.id, 'settingsClose');
  assert.equal(dialog.open, true);
  dialog.escape();
  assert.equal(dialog.open, false);
  assert.equal(app.document.activeElement.id, 'readerSettings', 'native dialog cancel restores trigger focus');
  app.storage.set(keys.theme, 'forest');
  app.window.dispatchEvent({type: 'storage', key: keys.theme});
  assert.equal(app.document.documentElement.dataset.codeTheme, 'forest');
  app.storage.clear(); app.window.dispatchEvent({type: 'storage', key: null});
  assert.equal(app.document.documentElement.dataset.codeTheme, 'light');

  const malformed = fixture({reader: false, stored: {[keys.theme]: '__proto__', [keys.roles]: '[broken', [keys.reader]: 'null'}});
  assert.equal(malformed.api.getPreferences().theme, 'light');
  assert.equal(malformed.api.getPreferences().fontSize, 14);
  assert.equal(malformed.get('clearRenderCache').hidden, true);
  const blocked = fixture({storageBlocked: true});
  await flush();
  blocked.api.open();
  await blocked.get('readerSettingsDialog').querySelector('[data-code-theme="dark"]').click();
  assert.match(blocked.get('settingsSaveStatus').textContent, /禁止保存/);
  assert.equal(blocked.storage.size, 0);
  assert.equal(blocked.events.length, 1, 'blocked storage does not throw or prevent reader event delivery');

  const older = deferred(), newer = deferred(); let reads = 0;
  const raced = fixture({reader: false, fetcher: url => {
    if (url === '/api/reuse/health') return ++reads === 1 ? older.promise : newer.promise;
  }});
  raced.api.open('sources');
  const reload = raced.get('settingsSourcesReload').click();
  newer.resolve(response({sources: [{source: 'codebuddy', status: 'ready', count: 18}]}));
  await reload;
  older.resolve(response({sources: [{source: 'codex', status: 'ready', count: 999}]}));
  await flush();
  assert.match(raced.get('settingsSourceList').textContent, /CodeBuddy/);
  assert.doesNotMatch(raced.get('settingsSourceList').textContent, /999/);
  const closedRead = deferred();
  const closed = fixture({reader: false, fetcher: url => url === '/api/reuse/health' ? closedRead.promise : undefined});
  closed.api.open('sources'); closed.get('readerSettingsDialog').close();
  closedRead.resolve(response({sources: [{source: 'codex', count: 999}]}));
  await flush();
  assert.equal(closed.get('settingsSourceList').children.length, 0, 'closed settings discard stale health results');

  const data = {sources: [{system: 'linux', source: 'codebuddy', status: 'ready', count: 2,
    path: '<img src=x onerror=alert(1)>', command: 'python3 app.py --codebuddy-dir "a&b"'}]};
  const refreshed = fixture({reader: false, fetcher: url => url === '/api/reuse/health' ? response(data) : response({status: 'refreshed'})});
  refreshed.api.open('sources'); await flush();
  assert.equal(refreshed.walk(refreshed.get('settingsSourceList')).some(node => node.tagName === 'IMG'), false);
  const button = refreshed.walk(refreshed.get('settingsSourceList')).find(node => node.tagName === 'BUTTON');
  await button.click();
  const request = refreshed.requests.find(([, options]) => options?.method === 'POST');
  assert.equal(request[0], '/api/reuse/refresh');
  assert.deepEqual(JSON.parse(request[1].body), {system: 'linux', source: 'codebuddy'});
  assert.match(refreshed.get('settingsSourceStatus').textContent, /已检查 1/);

  // The first completed refresh replaces both cards. Completion of the second
  // operation must still re-read health, even though its original button left DOM.
  for (const secondSucceeded of [true, false]) {
    const firstPost = deferred(), secondPost = deferred();
    const states = {codex: 'ready', claude: 'ready'};
    let healthReads = 0;
    const concurrent = fixture({reader: false, fetcher(url, options) {
      if (options?.method === 'POST') {
        return JSON.parse(options.body).source === 'codex' ? firstPost.promise : secondPost.promise;
      }
      if (url === '/api/reuse/health') {
        healthReads++;
        return response({sources: Object.entries(states).map(([source, status]) =>
          ({system: 'linux', source, status, path: '/synthetic/' + source}))});
      }
    }});
    concurrent.api.open('sources'); await flush();
    const buttons = concurrent.walk(concurrent.get('settingsSourceList')).filter(node => node.tagName === 'BUTTON');
    const first = buttons[0].click(), second = buttons[1].click();
    states.claude = 'indexing';
    firstPost.resolve(response({status: 'refreshed'})); await first;
    assert.equal(buttons[1].isConnected, false, 'first refresh replaces the second operation\'s old card');
    assert.match(concurrent.get('settingsSourceList').textContent, /更新中/);
    states.claude = secondSucceeded ? 'ready' : 'error';
    secondPost.resolve(response({status: secondSucceeded ? 'refreshed' : 'failed'}, secondSucceeded));
    await second;
    assert.equal(healthReads, 3, 'each completed refresh obtains current health');
    assert.doesNotMatch(concurrent.get('settingsSourceList').textContent, /更新中|正在刷新/);
    if (!secondSucceeded) assert.match(concurrent.get('settingsSourceList').textContent, /读取失败/);
    assert.equal(buttons[1].textContent, '正在刷新…', 'the detached original button is not mistaken for a new card');
  }

  // Leaving the source panel invalidates UI follow-up for either result. Source
  // refresh itself still completes on the server; no hidden health polling starts.
  for (const dismissal of ['close', 'reading']) {
    for (const succeeded of [true, false]) {
      const pendingPost = deferred();
      let healthReads = 0;
      const hidden = fixture({reader: false, fetcher(url, options) {
        if (options?.method === 'POST') return pendingPost.promise;
        if (url === '/api/reuse/health') { healthReads++; return response(data); }
      }});
      hidden.api.open('sources'); await flush();
      const button = hidden.walk(hidden.get('settingsSourceList')).find(node => node.tagName === 'BUTTON');
      const pending = button.click();
      if (dismissal === 'close') hidden.get('readerSettingsDialog').close();
      else hidden.api.open('reading');
      pendingPost.resolve(response({status: 'finished'}, succeeded)); await pending;
      assert.equal(healthReads, 1, `${dismissal} suppresses follow-up reads for ${succeeded ? 'success' : 'failure'}`);
    }
  }

  const failures = [];
  // The legacy theme click listener must not disagree with the settings listener
  // when localStorage rejects the write.
  try {
    const actualTheme = blocked.document.documentElement.dataset.codeTheme;
    const selectedButton = blocked.get('readerSettingsDialog').querySelector(`[data-code-theme="${actualTheme}"]`);
    assert.equal(selectedButton.getAttribute('aria-pressed'), 'true',
      'after a failed save, the pressed theme must agree with the actual reader theme');
  } catch (error) { failures.push(error); }

  // Keep useful previous cards after a failed health reload, but their refresh
  // actions must still complete instead of retaining an expired list sequence.
  let healthCalls = 0;
  const retry = fixture({reader: false, fetcher: url => {
    if (url === '/api/reuse/health') return response(data, ++healthCalls !== 2);
    return response({status: 'refreshed'});
  }});
  retry.api.open('sources'); await flush();
  await retry.get('settingsSourcesReload').click();
  const retryButton = retry.walk(retry.get('settingsSourceList')).find(node => node.tagName === 'BUTTON');
  await retryButton.click();
  try {
    assert.ok(healthCalls >= 3 || !retryButton.disabled,
      'refresh after a failed status reload must fetch current state or recover its button');
  } catch (error) { failures.push(error); }
  if (failures.length) throw new AggregateError(failures, 'Settings integration regressions');
  console.log('Settings: persisted preferences, reader integration, focus, storage failure, stale responses, and refresh contracts passed');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
