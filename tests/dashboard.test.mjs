/** UI logic smoke tests using a minimal DOM; no browser or npm packages required. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../app/index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes = new Map();

function element(id) {
    if (!nodes.has(id)) {
        const fields = new Map();
        nodes.set(id, {
            value: '', innerHTML: '', textContent: '', open: false, fields,
            classList: { toggle() {}, add() {}, remove() {} },
            querySelectorAll() { return []; },
            querySelector() { return { focus() {} }; },
            setAttribute() {},
            showModal() { this.open = true; },
            close() { this.open = false; },
            reset() { for (const field of fields.values()) field.value = ''; },
            elements: {
                namedItem(name) {
                    if (!fields.has(name)) fields.set(name, { value: '' });
                    return fields.get(name);
                },
            },
        });
    }
    return nodes.get(id);
}

const now = Date.now() / 1000;
const stateService = {
    id: 2, assignment: 1, name: 'Port status', kind: 'snmp', target: '.1.2.3',
    unit: 1, scale: 1, units: '', direction: 'below', warning: null, critical: null,
    persistence: 2, revision: 1, value_type: 'state',
    state_map: { '1': { label: 'Up', status: 'healthy' }, '2': { label: 'Down', status: 'critical' } },
};
const fixture = {
    projects: [{ id: 1, name: 'Test' }],
    devices: [{ id: 1, name: 'SW001', address: '127.0.0.1', model: 'Switch' }],
    assignments: [{ id: 1, project: 1, device: 1, alias: 'Stage', visible: 1, monitoring: 1 }],
    runs: [{ id: 1, project: 1 }], settings: { active_run: '1', retention_days: '30' },
    legacy_addresses: [], service_templates: [],
    services: [{ id: 1, assignment: 1, kind: 'ping', revision: 1 }, stateService],
    latest: [
        { service: 1, status: 'healthy', value: 1, timestamp: now },
        { service: 2, status: 'healthy', value: 1, display_value: 'Up', timestamp: now },
    ],
    incident_lists: { active: [], acknowledged: [], resolved: [], suppressed: [] },
};
const context = vm.createContext({
    document: {
        getElementById: element,
        querySelectorAll() { return []; },
        body: { dataset: {}, addEventListener() {} },
    },
    fetch: async path => ({ ok: true, json: async () => {
        if (path === '/api/me') return {id:1,username:'admin',role:'admin',csrf:'test',must_change_password:0};
        if (path === '/api/users') return [];
        if (path === '/api/telegram' || path === '/api/whatsapp') return {configuration:{},outbox:[]};
        return fixture;
    } }),
    setInterval() {},
    confirm() { return true; },
    FormData: class {
        constructor(form) {
            this.entries = [...form.fields].map(([key, field]) => [key, field.value]);
        }
        [Symbol.iterator]() { return this.entries[Symbol.iterator](); }
    },
});
new vm.Script(script).runInContext(context);
await context.refresh();
assert.match(element('dashboard').innerHTML, /SW001 - Stage/);
assert.match(element('dashboard').innerHTML, /class="action-menu"/);
assert.match(element('dashboard').innerHTML, />Up /);
context.openAliasEditor(1);
assert.equal(element('alias-edit-form').elements.namedItem('alias').value, 'Stage');
context.openServiceEditor(2);
const payload = context.servicePayload(element('service-edit-form'));
assert.equal(payload.state_map['2'].label, 'Down');
fixture.latest[0].status = 'unreachable';
await context.refresh();
assert.match(element('dashboard').innerHTML, /Suppressed — host offline/);

const sample = (timestamp, value, status = 'healthy', revision = 1) => ({
    timestamp, value, status, revision, display_value: value === null ? null : String(value),
});
const numeric = { ...stateService, value_type: 'metric', units: '%', warning: 50, critical: 80 };
const line = context.historyGraph([sample(30, 90), sample(20, 60), sample(10, 30)], numeric);
assert.match(line, /<svg/);
assert.match(line, /L /);
assert.match(line, /stroke-dasharray/);
assert.doesNotMatch(line, /NaN|Infinity/);
const steps = context.historyGraph([sample(30, 2), sample(20, 1), sample(10, 1)], stateService);
assert.match(steps, /H .* V /);
assert.match(steps, />Up<\/text>/);
assert.match(steps, />Down<\/text>/);
const gap = context.historyGraph([sample(30, 2), sample(20, null, 'blocked'), sample(10, 1)], numeric);
assert.equal((gap.match(/<path /g) || []).length, 2);
const oldConfig = context.historyGraph([sample(30, 90, 'healthy', 2)], numeric);
assert.match(oldConfig, /No usable readings/);
assert.match(context.historyGraph([], numeric), /No usable readings/);
assert.doesNotMatch(context.historyGraph([sample(10, 0)], numeric), /NaN|Infinity/);
const escaped = context.historyGraph([sample(10, 1)], { ...numeric, name: '<img src=x>' });
assert.doesNotMatch(escaped, /<img/);
context.historyView(false);
assert.equal(element('history-graph').hidden, true);
assert.equal(element('readings').hidden, false);
console.log('Dashboard smoke tests passed: cards, menus, alias/state editors, dependency display, graphs and gaps.');

// The anonymous overview must render active incidents before equipment cards,
// while escaping operator-controlled names and providing an empty state.
const statusPage = await readFile(new URL('../app/status.html', import.meta.url), 'utf8');
assert.ok(statusPage.indexOf('id="incidents"') < statusPage.indexOf('id="devices"'));
const publicNodes = new Map();
const publicData = {
    project: 'Deployment', updated: now,
    devices: [{ name: 'SW001', alias: 'Stage', status: 'unreachable', services: [] }],
    incidents: [{ device: 'SW001', alias: '<img src=x>', service: 'Host ping', status: 'unreachable', opened: now }],
};
const publicContext = vm.createContext({
    document: { getElementById(id) {
        if (!publicNodes.has(id)) publicNodes.set(id, { innerHTML: '', textContent: '' });
        return publicNodes.get(id);
    } },
    fetch: async () => ({ ok: true, json: async () => publicData }),
    setInterval() {},
});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(publicContext);
await publicContext.refresh();
assert.match(publicNodes.get('incidents').innerHTML, /Host ping/);
assert.match(publicNodes.get('incidents').innerHTML, /Offline/);
assert.doesNotMatch(publicNodes.get('incidents').innerHTML, /<img/);
publicData.incidents = [];
await publicContext.refresh();
assert.match(publicNodes.get('incidents').innerHTML, /No active incidents/);
console.log('Public incident overview smoke tests passed.');
