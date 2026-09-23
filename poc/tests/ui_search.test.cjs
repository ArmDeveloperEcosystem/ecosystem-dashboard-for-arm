/* No dependencies: exercise the browser controller with a small DOM fixture.
 * Run with: node --test poc/tests/ui_search.test.cjs
 */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');

class Element {
    constructor() {
        this.attributes = {};
        this.children = [];
        this.listeners = {};
        this.hidden = false;
        this.checked = false;
        this.value = '';
        this.id = '';
        this.dataset = {};
        const classes = new Set();
        this.classList = {
            add: value => classes.add(value), remove: value => classes.delete(value),
            contains: value => classes.has(value),
            toggle: (value, on) => on ? classes.add(value) : classes.delete(value)
        };
    }
    set innerHTML(_) { throw new Error('Returned content must not use innerHTML'); }
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return this.text || ''; }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    getAttribute(key) { return this.attributes[key] ?? null; }
    appendChild(child) { child.parent = this; this.children.push(child); }
    replaceChildren() { this.children = []; }
    remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    focus() {}
    closest() { return this.parent || this; }
}

function fixture(fetcher) {
    const ids = ['nl-search-input', 'nl-search-form', 'nl-search-tested', 'nl-search-clear',
        'nl-search-feedback', 'nl-search-status', 'nl-search-interpretation', 'nl-search-constraints',
        'nl-search-notice', 'nl-search-refinements', 'currently-shown-number', 'if-none-contribute-div',
        'filter-facet-display-name-group-license', 'filter-facet-display-name-group-category', 'category-description'];
    const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
    const submit = new Element();
    nodes['nl-search-form'].querySelector = () => submit;
    const root = new Element();
    root.dataset.endpoint = '/api/search';
    root.querySelector = selector => nodes[selector.slice(1)];
    root.querySelectorAll = () => [];
    const rows = ['postgresql', 'nginx'].map((id, index) => {
        const row = new Element();
        row.id = 'row-' + index;
        row.setAttribute('data-title-urlized', id);
        row.setAttribute('data-catalog-id', 'linux/opensource_packages/' + id + '.md');
        row.setAttribute('data-title', id === 'postgresql' ? 'PostgreSQL' : 'Nginx');
        row.setAttribute('data-has-arm64-tests', String(index === 0));
        row.title = new Element();
        row.querySelector = () => row.title;
        return row;
    });
    const radios = {};
    for (const [group, labels] of Object.entries({ license: ['All', 'Open source', 'Commercial'], category: ['All', 'Databases'] })) {
        radios[group] = labels.map((label, index) => {
            const radio = new Element();
            radio.setAttribute('data-display-name', label);
            radio.setAttribute('data-urlized-name', label.toLowerCase().replaceAll(' ', '-'));
            radio.checked = index === 0;
            return radio;
        });
    }
    const document = {
        getElementById: id => nodes[id], createElement: () => new Element(),
        querySelector: selector => radios[selector.includes('license') ? 'license' : 'category'].find(radio => radio.checked),
        querySelectorAll: selector => {
            if (selector === '.search-div') return rows;
            if (selector === '.nl-search-match') return rows.flatMap(row => row.title.children);
            return radios[selector.includes('license') ? 'license' : 'category'];
        }
    };
    const window = { location: { href: 'http://localhost:8765/linux/' }, setTimeout, clearTimeout };
    const calls = [];
    const context = vm.createContext({
        window, document, URL, AbortController, console,
        fetch: async (url, options) => { calls.push(JSON.parse(options.body)); return fetcher(url, options); },
        sanitizeInput: value => value.replace(/[^a-zA-Z0-9 .\-/]+/g, '').replace(/\s+/g, ' '),
        filter_card: () => false,
        hideElements: (all, hidden) => all.forEach(row => { row.hidden = hidden.includes(row); }),
        updateClearFilterOption: () => {}
    });
    vm.runInContext(readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/static/js/eco-dashboard/conversational-search.js'), 'utf8'), context);
    const app = window.createDashboardSearch(root);
    return { app, root, rows, nodes, calls, radios };
}

function response(results, extra = {}) {
    return { ok: true, json: async () => ({ status: 'ok', mode: 'hybrid',
        interpreted_query: 'databases', constraints: { license: 'all', category: null, tested_only: false },
        results: results.map(item => ({ ...item, id: item.id.includes('/') ? item.id : 'linux/opensource_packages/' + item.id + '.md' })), notices: [], ...extra }) };
}

test('Only catalog IDs render; reasons are text and unsafe evidence URLs are rejected', async () => {
    const f = fixture(async () => response([
        { id: 'postgresql', reason: '<img src=x onerror=alert(1)>', evidence_url: 'javascript:alert(1)' },
        { id: 'invented-package', reason: 'Invented result' }
    ]));
    await f.app.search('databases');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.equal(f.rows[0].title.children[0].textContent, '<img src=x onerror=alert(1)>');
    assert.equal(f.rows[0].title.children[0].children.length, 0);
    assert.match(f.nodes['nl-search-notice'].textContent, /outside the current catalog/);
    assert.equal(f.nodes['currently-shown-number'].textContent, '1');
});

test('Refinements carry previous subject and synchronize visible license and test constraints', async () => {
    let request = 0;
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }], {
        constraints: { license: ++request === 1 ? 'all' : 'opensource', category: null, tested_only: request > 1 }
    }));
    await f.app.search('databases');
    await f.app.search('Only open-source ones');
    assert.equal(f.calls[1].previous_query, 'databases');
    assert.equal(f.radios.license[1].checked, true);
    assert.equal(f.nodes['nl-search-tested'].checked, true);
    assert.match(f.nodes['filter-facet-display-name-group-license'].textContent, /Open source/);
});

test('An unavailable service falls back to clearly identified package-name matching', async () => {
    const f = fixture(async () => { throw new Error('Offline'); });
    await f.app.search('PostgreSQL');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 1 match/);
    assert.equal(f.nodes['nl-search-refinements'].hidden, true);
});

test('Same-title package variants cannot inherit a different catalog record match', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
    f.rows[1].setAttribute('data-title-urlized', 'postgresql');
    f.rows[1].setAttribute('data-title', 'PostgreSQL');
    f.rows[1].setAttribute('data-catalog-id', 'linux/commercial_packages/postgresql.md');
    await f.app.search('PostgreSQL');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
});

test('Offline name matching still excludes records without verified Arm64 test metadata', async () => {
    const f = fixture(async () => { throw new Error('Offline'); });
    f.nodes['nl-search-tested'].checked = true;
    await f.app.search('Nginx');
    assert.deepEqual(f.rows.map(row => row.hidden), [true, true]);
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 0 matches/);
});

test('Late responses cannot replace results from a newer search', async () => {
    const pending = [];
    const f = fixture(() => new Promise(resolve => pending.push(resolve)));
    const oldRequest = f.app.search('databases');
    const newRequest = f.app.search('web servers');
    pending[1](response([{ id: 'nginx', reason: 'Web server' }], { interpreted_query: 'web servers' }));
    await newRequest;
    pending[0](response([{ id: 'postgresql', reason: 'Database' }]));
    await oldRequest;
    assert.deepEqual(f.rows.map(row => row.hidden), [true, false]);
    assert.equal(f.nodes['nl-search-interpretation'].textContent, 'Interpreted as: web servers');
});

test('Clearing a query restores the catalog, preserves selected test filter, and removes reasons', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
    await f.app.search('databases');
    f.nodes['nl-search-tested'].checked = true;
    await f.app.search('');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.equal(f.rows[0].title.children.length, 0);
    f.nodes['nl-search-tested'].checked = false;
    await f.app.search('');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, false]);
    assert.equal(f.nodes['nl-search-feedback'].hidden, true);
});

test('Sidebar changes explicitly override constraints from earlier query wording', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
    await f.app.search('open-source databases');
    f.app.filtersChanged();
    await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(f.calls[1].filters_override, true);
});
