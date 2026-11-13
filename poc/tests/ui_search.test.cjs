/* No dependencies: exercise the browser controller with a small DOM fixture.
 * Run with: node --test poc/tests/ui_search.test.cjs
 */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');

const sharedContext = vm.createContext({ document: { addEventListener() {} } });
vm.runInContext(readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/static/js/eco-dashboard/search.js'), 'utf8'), sharedContext);
const hideElements = sharedContext.hideElements;

class Element {
    constructor() {
        this.attributes = {};
        this.children = [];
        this.insertedChildren = [];
        this.listeners = {};
        this.hidden = false;
        this.open = false;
        this.checked = false;
        this.value = '';
        this.id = '';
        this.dataset = {};
        const classes = new Set();
        this.classList = {
            add: value => classes.add(value), remove: value => classes.delete(value),
            contains: value => classes.has(value),
            toggle: (value, on = !classes.has(value)) => on ? classes.add(value) : classes.delete(value)
        };
    }
    set innerHTML(_) { throw new Error('Returned content must not use innerHTML'); }
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return this.text || ''; }
    setAttribute(key, value) {
        this.attributes[key] = String(value);
        if (key === 'id') this.id = String(value);
        if (key === 'hidden') this.hidden = true;
    }
    removeAttribute(key) {
        delete this.attributes[key];
        if (key === 'hidden') this.hidden = false;
    }
    getAttribute(key) { return key === 'id' ? this.id || null : this.attributes[key] ?? null; }
    get parentNode() { return this.parent || null; }
    get nextElementSibling() {
        return this.parent ? this.parent.children[this.parent.children.indexOf(this) + 1] || null : null;
    }
    appendChild(child) {
        return this.insertBefore(child, null);
    }
    insertBefore(child, reference) {
        if (reference !== null && reference.parentNode !== this) throw new Error('Reference is not a child');
        if (child === reference) return child;
        if (child.parent) child.remove();
        child.parent = this;
        this.children.splice(reference === null ? this.children.length : this.children.indexOf(reference), 0, child);
        this.insertedChildren.push(child);
        return child;
    }
    replaceChildren() { this.children = []; }
    remove() { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    focus() { this.focused = true; }
    closest() { return this.parent || this; }
}

function fixture(fetcher, packageIDs = ['postgresql', 'nginx'], filterCard = () => false, options = {}) {
    const ids = ['nl-search-input', 'nl-search-form', 'nl-search-tested', 'nl-search-clear',
        'nl-search-feedback', 'nl-search-status', 'nl-search-details', 'nl-search-details-copy',
        'nl-search-notice', 'nl-search-refinements', 'nl-search-examples', 'currently-shown-number', 'results-status-bar', 'if-none-contribute-div',
        'filter-facet-display-name-group-license', 'filter-facet-display-name-group-category', 'category-description'];
    const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
    nodes['nl-search-details'].hidden = true;
    const submit = new Element();
    nodes['nl-search-form'].querySelector = () => submit;
    const root = new Element();
    root.dataset.endpoint = options.endpoint || (options.transport === 'browser' ? 'https://knowledge.armdevtechapi.com/search' : '/api/search');
    root.dataset.transport = options.transport || 'api';
    root.querySelector = selector => nodes[selector.slice(1)];
    const buttons = ['opensource'].map(value => {
        const button = new Element();
        button.dataset.searchRefinement = value;
        return button;
    });
    const example = new Element();
    example.dataset.searchExample = 'Web servers';
    root.querySelectorAll = () => [...buttons, example];
    const table = new Element();
    const rows = packageIDs.map((id, index) => {
        const row = new Element();
        row.id = 'row-' + index;
        row.classList.add('search-div');
        row.setAttribute('data-title-urlized', id);
        row.setAttribute('data-catalog-id', 'linux/opensource_packages/' + id + '.md');
        row.setAttribute('data-title', id === 'postgresql' ? 'PostgreSQL' : 'Nginx');
        row.setAttribute('data-woa', 'true');
        row.setAttribute('data-kb-edition', 'open-source');
        row.setAttribute('data-kb-description', 'Catalog description for ' + id);
        row.setAttribute('data-has-arm64-tests', String(index === 0));
        row.title = new Element();
        row.caret = new Element();
        row.querySelector = selector => selector === '.caret-spin' ? row.caret : row.title;
        row.details = new Element();
        row.details.id = 'details-' + index;
        row.details.hidden = true;
        table.appendChild(row);
        table.appendChild(row.details);
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
            if (selector === '.search-div') return table.children.filter(row => row.classList.contains('search-div'));
            if (selector === '.nl-search-match') return table.children.filter(row => row.title).flatMap(row => row.title.children);
            return radios[selector.includes('license') ? 'license' : 'category'];
        }
    };
    const window = { setTimeout: options.setTimeout || setTimeout, clearTimeout };
    const calls = [];
    const signals = [];
    if (options.configureRows) options.configureRows(rows, table);
    const context = vm.createContext({
        window, document, AbortController, URL, URLSearchParams, console,
        Date: options.Date || Date,
        fetch: async (url, options) => { calls.push(options.body ? JSON.parse(options.body) : { url: String(url), options }); signals.push(options.signal); return fetcher(url, options); },
        sanitizeInput: value => value.replace(/[^a-zA-Z0-9 .\-/]+/g, '').replace(/\s+/g, ' '),
        filter_card: filterCard,
        hideElements,
        updateClearFilterOption: () => {}
    });
    if (options.transport === 'browser') {
        vm.runInContext(readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/static/js/eco-dashboard/browser-kb-search.js'), 'utf8'), context);
    }
    vm.runInContext(readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/static/js/eco-dashboard/conversational-search.js'), 'utf8'), context);
    vm.runInContext(readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/static/js/eco-dashboard/table_functionality.js'), 'utf8'), context);
    const app = window.createDashboardSearch(root);
    return { app, root, rows, nodes, calls, radios, buttons, example, table, signals, rowClickHandler: context.rowClickHandler };
}

function response(results, extra = {}) {
    return { ok: true, json: async () => ({ status: 'ok', mode: 'kb_scoped',
        query: 'databases',
        results: results.map(item => ({ ...item, id: item.id.includes('/') ? item.id : 'linux/opensource_packages/' + item.id + '.md' })), notices: [], ...extra }) };
}

test('URL searches preserve the decoded query through KB dispatch while legacy search remains sanitized', async () => {
    const query = '  C++ & 日本語 databases? "exact" + café  ';
    for (const enabled of [true, false]) {
        const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
        const searchBox = new Element();
        let pending, legacyQuery;
        const context = vm.createContext({
            URLSearchParams,
            console: { log() {} },
            window: enabled ? { dashboardSearch: { search(value) { pending = f.app.search(value); } } } : {},
            document: {
                addEventListener() {},
                getElementById: id => id === 'search-box' ? searchBox : null,
                querySelectorAll: () => []
            }
        });
        vm.runInContext(readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/static/js/eco-dashboard/search.js'), 'utf8'), context);
        context.applySearchAndFilters = (_, value) => { legacyQuery = value; return []; };
        context.updateShownNumber = () => {};
        context.URLsearchAndfiltering('?search=' + encodeURIComponent(query));
        if (enabled) {
            await pending;
            assert.equal(f.calls[0].query, query);
            assert.equal(f.nodes['nl-search-input'].value, query);
            assert.equal(searchBox.getAttribute('search-value'), query);
            assert.equal(legacyQuery, undefined);
        } else {
            assert.equal(legacyQuery, ' C databases exact caf ');
            assert.equal(searchBox.getAttribute('search-value'), ' C databases exact caf ');
            assert.equal(f.calls.length, 0);
        }
    }
});

test('Search feedback uses a closed native disclosure without repeated query or scope nodes', () => {
    const template = readFileSync(resolve(__dirname, '../../themes/arm-design-system-hugo-theme/layouts/partials/eco-dashboard/conversational-search.html'), 'utf8');
    const details = template.match(/<details\b([^>]*\bid="nl-search-details"[^>]*)>([\s\S]*?)<\/details>/);
    assert.ok(details, 'Search explanation must use a native details element');
    assert.doesNotMatch(details[1], /\bopen(?:\s|=|$)/);
    assert.match(details[2], /<summary\b[^>]*>\s*How search works\s*<\/summary>/);
    assert.doesNotMatch(template, /id="nl-search-(?:interpretation|constraints)"/);
    assert.doesNotMatch(template, /data-search-refinement="tested"/);
});

test('Successful searches show one compact count with optional explanation and refinements', async () => {
    for (const ids of [['postgresql'], ['postgresql', 'nginx']]) {
        const f = fixture(async () => response(ids.map(id => ({ id, reason: 'A match' }))));
        await f.app.search('software');
        assert.equal(f.nodes['nl-search-status'].textContent, ids.length === 1 ? '1 result' : '2 results');
        assert.equal(f.nodes['nl-search-details'].hidden, false);
        assert.equal(f.nodes['nl-search-details'].open, false);
        assert.match(f.nodes['nl-search-details-copy'].textContent, /Packages are ranked by the Arm Knowledge Base\./);
        assert.equal(f.nodes['nl-search-notice'].hidden, true);
        assert.equal(f.nodes['nl-search-refinements'].hidden, false);
        assert.equal(f.nodes['results-status-bar'].hidden, true);
        assert.equal(f.nodes['nl-search-examples'].hidden, true);
    }
});

test('Example searches hide while loading and return on clear with focus kept on the input', async () => {
    let finishRequest;
    const f = fixture(() => new Promise(resolve => { finishRequest = resolve; }));
    assert.equal(f.nodes['nl-search-examples'].hidden, false);
    f.example.listeners.click();
    assert.equal(f.nodes['nl-search-input'].focused, true);
    assert.equal(f.nodes['nl-search-input'].value, 'Web servers');
    assert.equal(f.nodes['nl-search-examples'].hidden, true);
    assert.equal(f.calls[0].query, 'Web servers');
    finishRequest(response([{ id: 'nginx', reason: 'Web server' }]));
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.nodes['nl-search-examples'].hidden, true);
    f.nodes['nl-search-clear'].listeners.click();
    assert.equal(f.nodes['nl-search-examples'].hidden, false);
    assert.equal(f.nodes['nl-search-input'].value, '');
    assert.equal(f.nodes['results-status-bar'].hidden, false);
});

test('Only catalog IDs render; descriptions remain plain text without injected elements', async () => {
    const f = fixture(async () => response([
        { id: 'postgresql', reason: '<img src=x onerror=alert(1)>' },
        { id: 'invented-package', reason: 'Invented result' }
    ]));
    await f.app.search('databases');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.equal(f.rows[0].title.children[0].textContent, '<img src=x onerror=alert(1)>');
    assert.equal(f.rows[0].title.children[0].children.length, 0);
    assert.match(f.nodes['nl-search-notice'].textContent, /Some results are unavailable in this dashboard and were not shown\./);
    assert.equal(f.nodes['nl-search-notice'].hidden, false);
    assert.equal(f.nodes['currently-shown-number'].textContent, '1');
});

test('Shared visibility updates scale linearly and close hidden details and carets', () => {
    const ids = Array.from({ length: 256 }, (_, index) => 'package-' + index);
    const f = fixture(async () => response([]), ids);
    const hidden = f.rows.filter((_, index) => index % 2 === 0);
    for (const row of f.rows) {
        row.details.hidden = false;
        row.classList.add('main-sw-row--clicked');
        row.caret.classList.add('rotated');
    }
    let membershipReads = 0;
    const measuredHidden = new Proxy(hidden, {
        get(target, key, receiver) {
            if (typeof key === 'string' && /^\d+$/.test(key)) membershipReads += 1;
            return Reflect.get(target, key, receiver);
        }
    });
    hideElements(f.rows, measuredHidden);
    assert.ok(membershipReads <= f.rows.length, 'Visibility must not rescan the hidden list for each row');
    f.rows.forEach((row, index) => {
        const shouldHide = index % 2 === 0;
        assert.equal(row.hidden, shouldHide);
        assert.equal(row.details.hidden, shouldHide);
        assert.equal(row.classList.contains('main-sw-row--clicked'), !shouldHide);
        assert.equal(row.caret.classList.contains('rotated'), !shouldHide);
    });
});

test('Open-source shortcut and recorded-tests checkbox preserve the exact submitted query', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }], {
        query: 'This response must not rewrite the query'
    }));
    const query = '  Databases for vector search?  ';
    await f.app.search(query);
    f.buttons[0].listeners.click();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.nodes['nl-search-refinements'].hidden, true, 'Already-selected license must not offer a redundant action');
    assert.equal(f.nodes['nl-search-input'].focused, true, 'Focus stays on a visible control');
    f.nodes['nl-search-tested'].checked = true;
    f.nodes['nl-search-tested'].listeners.change();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.deepEqual(f.calls.map(call => call.query), [query, query, query]);
    assert.deepEqual(f.calls[2], {
        query, filters: { license: 'opensource', category: null, tested_only: true }
    });
    assert.equal(f.nodes['nl-search-input'].value, query);
    assert.equal(f.radios.license[1].checked, true);
    assert.equal(f.nodes['nl-search-tested'].checked, true);
    assert.match(f.nodes['filter-facet-display-name-group-license'].textContent, /Open source/);
});

test('Refinements preserve category feedback and responses do not rewrite selected controls', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }], {
        constraints: { license: 'all', category: null, tested_only: false }
    }));
    f.radios.category.forEach((radio, index) => { radio.checked = index === 1; });
    f.nodes['filter-facet-display-name-group-category'].textContent = 'Category: Databases';
    f.nodes['category-description'].textContent = 'Database software';
    await f.app.search('databases');
    f.buttons[0].listeners.click();
    await new Promise(resolve => setTimeout(resolve, 0));
    f.nodes['nl-search-tested'].checked = true;
    f.nodes['nl-search-tested'].listeners.change();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.deepEqual(f.calls[2].filters, {
        license: 'opensource', category: 'Databases', tested_only: true
    });
    assert.equal(f.radios.license[1].checked, true);
    assert.equal(f.radios.category[1].checked, true);
    assert.equal(f.nodes['nl-search-tested'].checked, true);
    assert.equal(f.nodes['filter-facet-display-name-group-category'].textContent, 'Category: Databases');
    assert.equal(f.nodes['category-description'].textContent, 'Database software');
});

test('An unavailable service falls back to clearly identified package-name matching', async () => {
    const f = fixture(async () => { throw new Error('Offline'); });
    await f.app.search('PostgreSQL');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 1 match/);
    assert.equal(f.nodes['nl-search-refinements'].hidden, true);
    assert.equal(f.nodes['nl-search-examples'].hidden, true);
});

test('Same-title package variants cannot inherit a different catalog record match', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
    f.rows[1].setAttribute('data-title-urlized', 'postgresql');
    f.rows[1].setAttribute('data-title', 'PostgreSQL');
    f.rows[1].setAttribute('data-catalog-id', 'linux/commercial_packages/postgresql.md');
    await f.app.search('PostgreSQL');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
});

test('Same-slug editions open only their own existing details without a new package link', async () => {
    const commercialID = 'linux/commercial_packages/postgresql.md';
    const f = fixture(async () => response([
        { id: commercialID, reason: 'Commercial description' },
        { id: 'postgresql', reason: 'Open-source description' }
    ]));
    const [openSource, commercial] = f.rows;
    commercial.setAttribute('data-title-urlized', 'postgresql');
    commercial.setAttribute('data-title', 'PostgreSQL');
    commercial.setAttribute('data-catalog-id', commercialID);
    openSource.details.textContent = 'Existing open-source details and resources';
    commercial.details.textContent = 'Existing commercial details and resources';
    await f.app.search('PostgreSQL');
    assert.equal(f.table.children[0], commercial);
    assert.equal(commercial.title.children[0].children.length, 0, 'Description creates no ambiguous deep link');
    assert.equal(openSource.title.children[0].children.length, 0);
    f.rowClickHandler(commercial);
    assert.equal(commercial.details.hidden, false);
    assert.equal(openSource.details.hidden, true);
    assert.equal(commercial.nextElementSibling.textContent, 'Existing commercial details and resources');
    await f.app.search('PostgreSQL');
    assert.equal(commercial.details.hidden, false, 'Reapplying search keeps already expanded details open');
    assert.equal(commercial.classList.contains('main-sw-row--clicked'), true);
    assert.equal(openSource.details.hidden, true);
});

test('Offline name matching still excludes records without verified Arm64 test metadata', async () => {
    const f = fixture(async () => { throw new Error('Offline'); });
    f.nodes['nl-search-tested'].checked = true;
    await f.app.search('Nginx');
    assert.deepEqual(f.rows.map(row => row.hidden), [true, true]);
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 0 matches/);
});

test('Scoped results use API-selected IDs while browsing and offline search apply local filters', async () => {
    let filterChecks = 0;
    const rejectByLocalFilter = () => { filterChecks += 1; return true; };
    const f = fixture(async () => response([{ id: 'nginx', reason: 'Web server' }]), undefined, rejectByLocalFilter);
    f.nodes['nl-search-tested'].checked = true;
    await f.app.search('web servers');
    assert.deepEqual(f.rows.map(row => row.hidden), [true, false]);
    assert.equal(filterChecks, 0, 'The API already applied the selected structured filters');
    await f.app.search('');
    assert.deepEqual(f.rows.map(row => row.hidden), [true, true]);
    assert.equal(filterChecks, 2, 'Browsing must still apply sidebar filters');
    const offline = fixture(async () => { throw new Error('Offline'); }, undefined, rejectByLocalFilter);
    await offline.app.search('Nginx');
    assert.deepEqual(offline.rows.map(row => row.hidden), [true, true]);
    assert.equal(filterChecks, 4, 'Name fallback must still apply sidebar filters');
});

test('Late responses cannot replace results from a newer search', async () => {
    const pending = [];
    const f = fixture(() => new Promise(resolve => pending.push(resolve)));
    const oldRequest = f.app.search('databases');
    const newRequest = f.app.search('web servers');
    pending[1](response([{ id: 'nginx', reason: 'Web server' }], { query: 'web servers' }));
    await newRequest;
    pending[0](response([{ id: 'postgresql', reason: 'Database' }]));
    await oldRequest;
    assert.deepEqual(f.rows.map(row => row.hidden), [true, false]);
    assert.equal(f.nodes['nl-search-input'].value, 'web servers');
    assert.equal(f.signals[0].aborted, true);
});

test('Rapid filter changes coalesce and stale responses cannot replace the filtered results', async () => {
    const pending = [];
    const f = fixture(() => new Promise(resolve => pending.push(resolve)));
    const oldRequest = f.app.search('databases');
    f.radios.category.forEach((radio, index) => { radio.checked = index === 1; });
    f.app.filtersChanged();
    f.radios.license.forEach((radio, index) => { radio.checked = index === 2; });
    f.app.filtersChanged();
    await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(f.calls.length, 2);
    assert.equal(f.signals[0].aborted, true);
    assert.deepEqual(f.calls[1].filters, { license: 'commercial', category: 'Databases', tested_only: false });
    pending[1](response([{ id: 'nginx', reason: 'Current filtered result' }]));
    await new Promise(resolve => setTimeout(resolve, 0));
    pending[0](response([{ id: 'postgresql', reason: 'Stale result' }]));
    await oldRequest;
    assert.deepEqual(f.rows.map(row => row.hidden), [true, false]);
    assert.equal(f.rows[1].title.children[0].textContent, 'Current filtered result');
    assert.equal(f.radios.license[2].checked, true);
    assert.equal(f.radios.category[1].checked, true);
});

test('Clearing a query restores the catalog, preserves selected test filter, and removes reasons', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
    await f.app.search('databases');
    f.nodes['nl-search-tested'].checked = true;
    await f.app.search('');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.equal(f.rows[0].title.children.length, 0);
    assert.equal(f.nodes['results-status-bar'].hidden, true);
    f.nodes['nl-search-tested'].checked = false;
    await f.app.search('');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, false]);
    assert.equal(f.nodes['nl-search-feedback'].hidden, true);
    assert.equal(f.nodes['results-status-bar'].hidden, false);
});

test('Sidebar changes send selected structured filters with the current query', async () => {
    const f = fixture(async () => response([{ id: 'postgresql', reason: 'Database' }]));
    await f.app.search('open-source databases');
    f.radios.license.forEach((radio, index) => { radio.checked = index === 2; });
    f.radios.category.forEach((radio, index) => { radio.checked = index === 1; });
    f.app.filtersChanged();
    await new Promise(resolve => setTimeout(resolve, 5));
    assert.deepEqual(f.calls[1], {
        query: 'open-source databases',
        filters: { license: 'commercial', category: 'Databases', tested_only: false }
    });
});

test('Backend rank moves existing main/detail pairs together and clear restores browse order', async () => {
    const f = fixture(async () => response([
        { id: 'nginx', reason: 'Web server' },
        { id: 'postgresql', reason: 'Database' }
    ]));
    await f.app.search('software');
    assert.deepEqual(f.table.children.map(row => row.id), ['row-1', 'details-1', 'row-0', 'details-0']);
    // Existing details and their state remain attached to the matching row.
    f.rows[1].details.hidden = false;
    await f.app.search('software');
    assert.equal(f.rows[1].nextElementSibling, f.rows[1].details);
    assert.equal(f.rows[1].details.hidden, false);
    await f.app.search('');
    assert.deepEqual(f.table.children.map(row => row.id), ['row-0', 'details-0', 'row-1', 'details-1']);
});

test('Already ordered searches and repeated results do not detach catalog rows', async () => {
    let movesBeforeFetch;
    const f = fixture(async () => {
        movesBeforeFetch = f.table.insertedChildren.length;
        return response([{ id: 'postgresql', reason: 'Database' }, { id: 'nginx', reason: 'Web server' }]);
    });
    const originalNodes = [...f.table.children];
    f.table.insertedChildren.length = 0;
    await f.app.search('software');
    assert.equal(movesBeforeFetch, 0, 'Starting a request must not move an already ordered table');
    assert.equal(f.table.insertedChildren.length, 0, 'Unchanged result order requires no row moves');
    await f.app.search('software');
    assert.equal(f.table.insertedChildren.length, 0, 'Reapplying results must be idempotent');
    assert.ok(f.table.children.every((node, index) => node === originalNodes[index]));
    assert.equal(f.table.children.length, originalNodes.length);
    assert.equal(f.calls.length, 1);
});

test('Changing rank moves only the needed pair and preserves static rows through clear', async () => {
    const f = fixture(async () => response([
        { id: 'nginx', reason: 'Web server' }, { id: 'postgresql', reason: 'Database' }
    ]));
    const header = new Element();
    const footer = new Element();
    header.id = 'static-header';
    footer.id = 'static-footer';
    f.table.insertBefore(header, f.rows[0]);
    f.table.appendChild(footer);
    const originalNodes = [...f.table.children];
    f.rows[1].details.hidden = false;
    f.table.insertedChildren.length = 0;
    await f.app.search('software');
    assert.deepEqual(f.table.children.map(node => node.id), [
        'static-header', 'row-1', 'details-1', 'row-0', 'details-0', 'static-footer'
    ]);
    assert.equal(f.table.insertedChildren.length, 2, 'Swapping two pairs only needs one pair to move');
    assert.ok(f.table.insertedChildren.every(node => node === f.rows[1] || node === f.rows[1].details));
    assert.equal(f.rows[1].details.hidden, true, 'A new request closes details while its results are pending');
    f.table.insertedChildren.length = 0;
    await f.app.search('');
    assert.ok(f.table.children.every((node, index) => node === originalNodes[index]));
    assert.equal(f.table.children.length, originalNodes.length);
    assert.equal(f.table.insertedChildren.length, 2, 'Clear restores browse order with one pair move');
    f.table.insertedChildren.length = 0;
    await f.app.search('');
    assert.equal(f.table.insertedChildren.length, 0, 'Clearing an already restored table does not detach rows');
});

test('Active ranking excludes unmatched rows from comparison sorting', async () => {
    const unmatchedIDs = Array.from({ length: 64 }, (_, index) => 'other-' + index);
    const f = fixture(async () => response([
        { id: 'nginx', reason: 'Web server' }, { id: 'postgresql', reason: 'Database' }
    ]), ['postgresql', 'nginx', ...unmatchedIDs]);
    const originalNodes = [...f.table.children];
    let unmatchedPinChecks = 0;
    for (const row of f.rows.slice(2)) {
        const contains = row.classList.contains;
        row.classList.contains = value => {
            if (value === 'js-pinned') unmatchedPinChecks += 1;
            return contains(value);
        };
    }
    await f.app.search('software');
    assert.ok(unmatchedPinChecks <= unmatchedIDs.length, 'Unmatched rows need one eligibility check, not sorting comparisons');
    assert.deepEqual(f.table.children.slice(0, 4).map(row => row.id), ['row-1', 'details-1', 'row-0', 'details-0']);
    assert.ok(f.rows.slice(2).every(row => row.hidden));
    await f.app.search('');
    assert.ok(f.table.children.every((node, index) => node === originalNodes[index]));
});

test('Pinned packages retain their section and placeholder pairs stay intact through rank and clear', async () => {
    const f = fixture(async () => response([
        { id: 'nginx', reason: 'Web server' }, { id: 'postgresql', reason: 'Database' }
    ]));
    const pinned = f.rows[0];
    pinned.classList.add('js-pinned');
    pinned.details.classList.add('js-pinned');
    const placeholder = new Element();
    placeholder.id = pinned.id + '-placeholder';
    placeholder.attributes = { ...pinned.attributes };
    placeholder.classList.add('search-div');
    placeholder.title = new Element();
    placeholder.querySelector = () => placeholder.title;
    const details = new Element();
    details.id = 'details-0-placeholder';
    details.hidden = true;
    f.table.appendChild(placeholder);
    f.table.appendChild(details);
    f.table.insertedChildren.length = 0;
    await f.app.search('software');
    assert.deepEqual(f.table.children.map(row => row.id), [
        'row-0', 'details-0', 'row-1', 'details-1', 'row-0-placeholder', 'details-0-placeholder'
    ]);
    assert.equal(placeholder.hidden, true);
    assert.equal(placeholder.title.children.length, 0);
    assert.match(f.nodes['nl-search-details-copy'].textContent, /Pinned packages/);
    assert.equal(f.nodes['nl-search-notice'].hidden, true);
    assert.equal(f.nodes['currently-shown-number'].textContent, '2');
    assert.ok(!f.table.insertedChildren.includes(pinned), 'An already positioned pinned row stays attached');
    assert.ok(!f.table.insertedChildren.includes(pinned.details), 'Pinned details stay attached');
    f.table.insertedChildren.length = 0;
    await f.app.search('software');
    assert.equal(f.table.insertedChildren.length, 0, 'Reapplying pinned results does not move rows or placeholders');
    await f.app.search('');
    assert.deepEqual(f.table.children.map(row => row.id), [
        'row-0', 'details-0', 'row-0-placeholder', 'details-0-placeholder', 'row-1', 'details-1'
    ]);
    await f.app.search('software');
    // Legacy unpin promotes the placeholder to the real row, then reapplies search.
    pinned.remove();
    pinned.details.remove();
    placeholder.id = 'row-0';
    await f.app.search('software');
    assert.equal(f.table.children[0], f.rows[1]);
    assert.equal(f.table.children[2], placeholder);
    assert.equal(placeholder.nextElementSibling, details);
    assert.equal(placeholder.title.children[0].textContent, 'Database');
    assert.equal(f.calls.length, 2, 'Unpinning reuses the active search without another KB request');
});

test('Unavailable KB, old hybrid mode, malformed responses and HTTP errors show name-only fallback', async () => {
    for (const reply of [
        response([], { status: 'unavailable', mode: 'kb_unavailable' }),
        response([{ id: 'nginx' }], { mode: 'hybrid' }),
        response([], { results: null }),
        { ok: false, json: async () => ({}) }
    ]) {
        const f = fixture(async () => reply);
        await f.app.search('PostgreSQL');
        assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
        assert.match(f.nodes['nl-search-status'].textContent, /Natural-language search is unavailable. Name search only: 1 match/);
        assert.match(f.nodes['nl-search-notice'].textContent, /Clear search to browse/);
        assert.equal(f.nodes['nl-search-notice'].hidden, false);
        assert.equal(f.nodes['nl-search-details'].hidden, true);
        assert.equal(f.nodes['nl-search-details'].open, false);
    }
});

test('Empty scoped results stay empty and do not become catalog-discovered matches', async () => {
    const f = fixture(async () => response([], { status: 'no_matches' }));
    await f.app.search('PostgreSQL');
    assert.deepEqual(f.rows.map(row => row.hidden), [true, true]);
    assert.equal(f.nodes['nl-search-status'].textContent, 'No matches found.');
    assert.equal(f.nodes['nl-search-refinements'].hidden, true);
    assert.equal(f.nodes['nl-search-notice'].hidden, false);
    assert.match(f.nodes['nl-search-notice'].textContent, /broader wording.*filters.*clear the search/);
    assert.equal(f.nodes['nl-search-details'].hidden, false);
    assert.equal(f.nodes['nl-search-details'].open, false);
    assert.equal(f.nodes['results-status-bar'].hidden, true);
    assert.equal(f.nodes['nl-search-examples'].hidden, false, 'Empty results offer example queries for recovery');
});

test('Routine retrieval details are collapsed while warnings remain visible', async () => {
    const routineNotices = [
        'Showing up to 50 results ranked by relevance, not every possible match.',
        'Category and test filters narrow these results; other matching packages may not appear.',
        'Recorded Arm64 tests do not mean every test passed. Open a package to see its test results.',
        'No matching current catalog packages were found.'
    ];
    const warning = 'An old package was omitted.';
    const notices = [...routineNotices, warning];
    const f = fixture(async () => response([], { status: 'no_matches', notices }));
    await f.app.search('databases');
    assert.equal(f.nodes['nl-search-details'].hidden, false);
    assert.equal(f.nodes['nl-search-details'].open, false);
    for (const notice of routineNotices) {
        assert.ok(f.nodes['nl-search-details-copy'].textContent.includes(notice));
        assert.ok(!f.nodes['nl-search-notice'].textContent.includes(notice));
    }
    assert.equal(f.nodes['nl-search-notice'].hidden, false);
    assert.ok(f.nodes['nl-search-notice'].textContent.includes(warning));
    assert.ok(!f.nodes['nl-search-details-copy'].textContent.includes(warning));
});

test('Editing, loading, clearing and fallback remove stale explanation and reset its disclosure', async () => {
    for (const transition of ['edit', 'loading', 'clear', 'fallback']) {
        let finishRequest;
        let requests = 0;
        const f = fixture(async () => {
            if (++requests === 1) return response([{ id: 'postgresql', reason: 'Database' }]);
            if (transition === 'fallback') throw new Error('Offline');
            return new Promise(resolve => { finishRequest = resolve; });
        });
        await f.app.search('databases');
        f.nodes['nl-search-details'].open = true;
        let pending;
        if (transition === 'edit') {
            f.nodes['nl-search-input'].value = 'new query';
            f.nodes['nl-search-input'].listeners.input();
        } else if (transition === 'clear') {
            await f.app.search('');
        } else {
            pending = f.app.search('PostgreSQL');
            if (transition === 'fallback') await pending;
        }
        assert.equal(f.nodes['nl-search-details'].hidden, true, transition);
        assert.equal(f.nodes['nl-search-details'].open, false, transition);
        assert.equal(f.nodes['nl-search-details-copy'].textContent, '', transition);
        if (transition === 'loading') {
            finishRequest(response([{ id: 'postgresql', reason: 'Database' }]));
            await pending;
            assert.equal(f.nodes['nl-search-details'].hidden, false);
            assert.equal(f.nodes['nl-search-details'].open, false);
        }
    }
});

test('Editing or clearing during a request cancels it and ignores its eventual response', async () => {
    for (const nextValue of ['new query', '']) {
        let resolveRequest;
        const f = fixture(() => new Promise(resolve => { resolveRequest = resolve; }));
        const pending = f.app.search('databases');
        assert.equal(f.root.getAttribute('aria-busy'), 'true');
        f.nodes['nl-search-input'].value = nextValue;
        f.nodes['nl-search-input'].listeners.input();
        assert.equal(f.signals[0].aborted, true);
        assert.equal(f.root.getAttribute('aria-busy'), 'false');
        resolveRequest(response([{ id: 'postgresql', reason: 'Old result' }]));
        await pending;
        assert.deepEqual(f.rows.map(row => row.hidden), [false, false]);
        assert.equal(f.rows[0].title.children.length, 0);
        assert.equal(f.nodes['nl-search-input'].value, nextValue);
    }
});

function kbHit(slug, extra = {}) {
    return {
        doc_type: 'Ecosystem Dashboard', platform: 'linux', edition: 'open-source',
        url: 'https://developer.arm.com/ecosystem-dashboard/linux/?package=' + encodeURIComponent(slug),
        ...extra
    };
}

function kbResponse(results) {
    return { ok: true, json: async () => ({ results }) };
}

function browserFixture(fetcher, options = {}) {
    return fixture(fetcher, options.packageIDs, options.filterCard, { ...options, transport: 'browser' });
}

test('Browser transport sends the unchanged query and scope directly to KB without credentials', async () => {
    const f = browserFixture(async () => kbResponse([kbHit('postgresql')]));
    const query = '  C++ & 日本語 databases? "exact" + café  ';
    await f.app.search(query);
    const { url, options } = f.calls[0];
    const target = new URL(url);
    assert.equal(target.origin + target.pathname, 'https://knowledge.armdevtechapi.com/search');
    assert.deepEqual(Object.fromEntries(target.searchParams), {
        q: query, k: '50', doc_type: 'Ecosystem Dashboard', platform: 'linux'
    });
    assert.equal(options.method || 'GET', 'GET');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.mode, 'cors');
    assert.equal(options.redirect, 'error');
    assert.equal(options.body, undefined);
    assert.ok(!Object.keys(options.headers || {}).some(key => /authorization|api.key/i.test(key)));
    assert.equal(f.nodes['nl-search-input'].value, query);
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
});

test('Browser transport displays local descriptions and retains KB rank without inventing records', async () => {
    const f = browserFixture(async () => kbResponse([
        kbHit('nginx', { snippet: '<img src=x onerror=alert(1)>', title: 'Invented title' }),
        kbHit('not-in-catalog'), kbHit('postgresql')
    ]));
    await f.app.search('software');
    assert.deepEqual(f.table.children.map(row => row.id), ['row-1', 'details-1', 'row-0', 'details-0']);
    assert.equal(f.rows[1].title.children[0].textContent, 'Catalog description for nginx');
    assert.equal(f.rows[1].title.children[0].children.length, 0);
    assert.equal(f.nodes['nl-search-status'].textContent, '2 results');
    assert.match(f.nodes['nl-search-notice'].textContent, /unavailable.*not shown/i);
});

test('Browser identity distinguishes same-slug editions and sends edition before retrieval', async () => {
    const commercialID = 'linux/commercial_packages/postgresql.md';
    const f = browserFixture(async url => {
        const edition = new URL(url).searchParams.get('edition');
        return kbResponse(edition ? [kbHit('postgresql', { edition })] : [
            kbHit('postgresql', { edition: 'commercial' }), kbHit('postgresql')
        ]);
    }, { configureRows(rows) {
        rows[1].setAttribute('data-title-urlized', 'postgresql');
        rows[1].setAttribute('data-catalog-id', commercialID);
        rows[1].setAttribute('data-kb-edition', 'commercial');
    } });
    await f.app.search('PostgreSQL');
    assert.equal(f.table.children[0], f.rows[1]);
    assert.deepEqual(f.rows.map(row => row.hidden), [false, false]);
    for (const [index, edition] of [[1, 'open-source'], [2, 'commercial']]) {
        f.radios.license.forEach((radio, i) => { radio.checked = i === index; });
        await f.app.search('PostgreSQL', { force: true });
        assert.equal(new URL(f.calls.at(-1).url).searchParams.get('edition'), edition);
        assert.deepEqual(f.rows.map(row => row.hidden), index === 1 ? [false, true] : [true, false]);
    }
});

test('Browser category and recorded-test refinements narrow cached candidates without another KB call', async () => {
    let rejectNginx = false;
    const f = browserFixture(async () => kbResponse([kbHit('nginx'), kbHit('postgresql')]), {
        filterCard: row => rejectNginx && row.getAttribute('data-title-urlized') === 'nginx'
    });
    await f.app.search('software');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, false]);
    rejectNginx = true;
    f.radios.category.forEach((radio, i) => { radio.checked = i === 1; });
    await f.app.search('software', { force: true });
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    rejectNginx = false;
    f.nodes['nl-search-tested'].checked = true;
    await f.app.search('software', { force: true });
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    f.nodes['nl-search-tested'].checked = false;
    await f.app.search('software', { force: true });
    assert.deepEqual(f.rows.map(row => row.hidden), [false, false]);
    assert.equal(f.calls.length, 1);
});

test('Browser results exclude catalog rows that are not supported on Arm', async () => {
    const f = browserFixture(async () => kbResponse([kbHit('nginx'), kbHit('postgresql')]), {
        configureRows(rows) { rows[1].setAttribute('data-woa', 'false'); }
    });
    await f.app.search('software');
    assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    assert.equal(f.nodes['nl-search-status'].textContent, '1 result');
});

test('Browser scope and URL errors invalidate the whole response instead of showing partial matches', async () => {
    const invalidHits = [
        null, {}, kbHit('nginx', { doc_type: 'Learning Path' }),
        kbHit('nginx', { platform: 'windows' }), kbHit('nginx', { edition: undefined }),
        kbHit('nginx', { edition: 'commercial' }),
        ...[
            'http://developer.arm.com/ecosystem-dashboard/linux/?package=nginx',
            'https://developer.arm.com.evil.test/ecosystem-dashboard/linux/?package=nginx',
            'https://user@developer.arm.com/ecosystem-dashboard/linux/?package=nginx',
            'https://developer.arm.com:8443/ecosystem-dashboard/linux/?package=nginx',
            'https://developer.arm.com/ecosystem-dashboard/windows/?package=nginx',
            'https://developer.arm.com/ecosystem-dashboard/linux/?package=nginx#section',
            'https://developer.arm.com/ecosystem-dashboard/linux/?package=nginx&package=postgresql',
            'https://developer.arm.com/ecosystem-dashboard/linux/?package=',
            'https://developer.arm.com/ecosystem-dashboard/linux/?package=bad%2Fslug',
            'https://developer.arm.com/ecosystem-dashboard/linux/?package=bad%00slug',
            'https://developer.arm.com/ecosystem-dashboard/linux/?package=nginx\\',
            'https://developer.arm.com/ecosystem-dashboard/linux/../linux/?package=nginx'
        ].map(url => kbHit('nginx', { url }))
    ];
    for (const invalid of invalidHits) {
        const f = browserFixture(async () => kbResponse([kbHit('nginx'), invalid]));
        await f.app.search('PostgreSQL');
        assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 1 match/, JSON.stringify(invalid));
        assert.deepEqual(f.rows.map(row => row.hidden), [false, true]);
    }
});

test('Browser edition-filter violations cannot be hidden by later local filtering', async () => {
    const f = browserFixture(async () => kbResponse([kbHit('nginx', { edition: 'commercial' })]), {
        configureRows(rows) {
            rows[1].setAttribute('data-kb-edition', 'commercial');
            rows[1].setAttribute('data-catalog-id', 'linux/commercial_packages/nginx.md');
        }
    });
    f.radios.license.forEach((radio, i) => { radio.checked = i === 1; });
    await f.app.search('PostgreSQL');
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only/);
});

test('Browser transport treats empty results honestly and malformed or failed responses as unavailable', async () => {
    const empty = browserFixture(async () => kbResponse([]));
    await empty.app.search('PostgreSQL');
    assert.equal(empty.nodes['nl-search-status'].textContent, 'No matches found.');
    assert.deepEqual(empty.rows.map(row => row.hidden), [true, true]);
    for (const fetcher of [
        async () => ({ ok: false, status: 429 }),
        async () => ({ ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); } }),
        async () => kbResponse(null),
        async () => kbResponse(Array.from({ length: 51 }, () => kbHit('nginx'))),
        async () => { throw new TypeError('Failed to fetch'); },
        async () => { throw new DOMException('Timed out', 'AbortError'); }
    ]) {
        const f = browserFixture(fetcher);
        await f.app.search('PostgreSQL');
        assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 1 match/);
        assert.equal(f.root.getAttribute('aria-busy'), 'false');
    }
});

test('Browser cache is scoped by exact query and edition, expires and does not remember failed requests', async () => {
    let now = 0;
    let fail = true;
    const f = browserFixture(async () => {
        if (fail) throw new TypeError('Failed to fetch');
        return kbResponse([kbHit('postgresql')]);
    }, { Date: { now: () => now } });
    await f.app.search('databases');
    fail = false;
    await f.app.search('databases', { force: true });
    await f.app.search('databases', { force: true });
    assert.equal(f.calls.length, 2);
    now = 300000;
    await f.app.search('databases', { force: true });
    assert.equal(f.calls.length, 3);
    await f.app.search('databases ', { force: true });
    assert.equal(f.calls.length, 4);
    f.radios.license.forEach((radio, i) => { radio.checked = i === 1; });
    await f.app.search('databases ', { force: true });
    assert.equal(f.calls.length, 5);
});

test('Browser cache is bounded rather than retaining every search in a long-lived tab', async () => {
    const f = browserFixture(async () => kbResponse([]));
    for (let i = 0; i <= 128; i++) await f.app.search('query-' + i);
    await f.app.search('query-0');
    assert.equal(f.calls.length, 130, 'The oldest of 129 entries must have been evicted');
    await f.app.search('query-128');
    assert.equal(f.calls.length, 130, 'Recent entries remain usable');
});

test('Browser cancellation keeps late results from overriding a newer query or filter', async () => {
    const pending = [];
    const f = browserFixture(() => new Promise(resolve => pending.push(resolve)));
    const first = f.app.search('databases');
    const second = f.app.search('web servers');
    assert.equal(f.signals[0].aborted, true);
    pending[1](kbResponse([kbHit('nginx')]));
    await second;
    pending[0](kbResponse([kbHit('postgresql')]));
    await first;
    assert.deepEqual(f.rows.map(row => row.hidden), [true, false]);
    assert.equal(f.nodes['nl-search-input'].value, 'web servers');
});

test('Browser query bound also covers URL-driven or programmatic searches', async () => {
    const f = browserFixture(async () => kbResponse([]));
    await f.app.search('x'.repeat(500));
    assert.equal(f.calls.length, 1);
    await f.app.search('x'.repeat(501));
    assert.equal(f.calls.length, 1, 'An oversized query must not reach KB');
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only/);
});

test('Browser catalog rejects ambiguous identities but excludes pinned placeholders from that check', async () => {
    const ambiguous = browserFixture(async () => kbResponse([kbHit('postgresql')]), {
        configureRows(rows) { rows[1].setAttribute('data-title-urlized', 'postgresql'); }
    });
    await ambiguous.app.search('PostgreSQL');
    assert.equal(ambiguous.calls.length, 0);
    assert.match(ambiguous.nodes['nl-search-status'].textContent, /Name search only/);
    const pinned = browserFixture(async () => kbResponse([kbHit('nginx'), kbHit('postgresql')]), {
        configureRows(rows, table) {
            rows[0].classList.add('js-pinned');
            const placeholder = new Element();
            placeholder.id = 'row-0-placeholder';
            placeholder.attributes = { ...rows[0].attributes };
            placeholder.classList.add('search-div');
            placeholder.title = new Element();
            placeholder.querySelector = () => placeholder.title;
            table.appendChild(placeholder);
            const details = new Element();
            details.id = 'details-0-placeholder';
            table.appendChild(details);
        }
    });
    await pinned.app.search('software');
    assert.equal(pinned.nodes['nl-search-status'].textContent, '2 results');
    assert.equal(pinned.table.children[0], pinned.rows[0]);
    const placeholder = pinned.table.children.find(row => row.id === 'row-0-placeholder');
    assert.equal(placeholder.hidden, true);
    // The dashboard's unpin operation replaces the original row with its clone.
    pinned.rows[0].remove();
    pinned.rows[0].details.remove();
    placeholder.id = 'row-0';
    await pinned.app.search('software', { force: true });
    assert.equal(pinned.table.children[0], pinned.rows[1]);
    assert.equal(placeholder.hidden, false);
    assert.equal(placeholder.title.children[0].textContent, 'Catalog description for postgresql');
    pinned.nodes['nl-search-tested'].checked = true;
    await pinned.app.search('software', { force: true });
    assert.equal(pinned.rows[1].hidden, true);
    assert.equal(placeholder.hidden, false);
    assert.equal(pinned.calls.length, 1, 'Unpinning and filtering reuse validated candidates');
});

test('Browser repeated KB hits display one package at its first-ranked position', async () => {
    const f = browserFixture(async () => kbResponse([kbHit('nginx'), kbHit('postgresql'), kbHit('nginx')]));
    await f.app.search('software');
    assert.equal(f.nodes['nl-search-status'].textContent, '2 results');
    assert.deepEqual(f.table.children.map(row => row.id), ['row-1', 'details-1', 'row-0', 'details-0']);
});

test('Browser endpoint configuration cannot leak credentials or use insecure remote HTTP', async () => {
    for (const endpoint of [
        'https://user:secret@knowledge.armdevtechapi.com/search',
        'http://knowledge.armdevtechapi.com/search',
        'https://knowledge.armdevtechapi.com/search#secret',
        'javascript:alert(1)'
    ]) {
        const f = browserFixture(async () => kbResponse([]), { endpoint });
        await f.app.search('PostgreSQL');
        assert.equal(f.calls.length, 0, endpoint);
        assert.match(f.nodes['nl-search-status'].textContent, /Name search only/);
    }
});

test('Browser request deadline aborts the in-flight fetch and releases the loading state', async () => {
    let fireDeadline;
    const f = browserFixture((_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }), { setTimeout(callback, milliseconds) {
        assert.equal(milliseconds, 15000);
        fireDeadline = callback;
        return undefined;
    } });
    const request = f.app.search('PostgreSQL');
    assert.equal(f.root.getAttribute('aria-busy'), 'true');
    fireDeadline();
    await request;
    assert.equal(f.signals[0].aborted, true);
    assert.equal(f.root.getAttribute('aria-busy'), 'false');
    assert.match(f.nodes['nl-search-status'].textContent, /Name search only: 1 match/);
});
