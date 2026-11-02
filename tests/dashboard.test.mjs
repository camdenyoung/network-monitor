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
            attributes: {},
            setAttribute(key, value) { this.attributes[key] = value; },
            getAttribute(key) { return this.attributes[key]; },
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
assert.match(element('service-edit-form').elements.namedItem('state_map').value, /2 \| Down \| Critical/);
assert.equal(payload.state_map['2'].status, 'critical');
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
const publicStorage = new Map();
const publicContext = vm.createContext({
    localStorage: {getItem: key => publicStorage.get(key), setItem: (key, value) => publicStorage.set(key, value)},
    document: { getElementById(id) {
        if (!publicNodes.has(id)) publicNodes.set(id, { innerHTML: '', textContent: '', attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }, getAttribute(key) { return this.attributes[key]; } });
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

// Checkbox values must be sent as booleans, including an explicit false when
// an administrator allows the user to keep their assigned password.
let submittedUser;
context.fetch = async (path, options) => {
    if (options) submittedUser = { path, body: JSON.parse(options.body) };
    let data = {};
    if (path === '/api/users') data = [{ id: 2, username: 'reader', email: 'reader@example.com', role: 'viewer', must_change_password: 0 }];
    if (path === '/api/telegram' || path === '/api/whatsapp') data = { configuration: {}, outbox: [] };
    return { ok: true, json: async () => data };
};
const userForm = element('user-form');
for (const [key, value] of Object.entries({user: '', username: 'new-reader', email: 'reader@example.com', role: 'viewer', password: 'Assigned-password-123'})) {
    userForm.elements.namedItem(key).value = value;
}
userForm.elements.namedItem('must_change_password').checked = false;
await userForm.onsubmit({ preventDefault() {}, target: userForm });
assert.equal(submittedUser.path, '/api/user-create');
assert.equal(submittedUser.body.email, 'reader@example.com');
assert.equal(submittedUser.body.must_change_password, false);
assert.match(element('users').innerHTML, /reader@example.com/);
assert.match(element('users').innerHTML, /Assigned password allowed/);
console.log('Account email and password-policy form smoke tests passed.');

// Operators can acknowledge, but never see configuration actions on the cards.
const previousFetch = context.fetch;
context.fetch = async (path, options) => path === '/api/state'
    ? {ok: true, json: async () => fixture} : previousFetch(path, options);
vm.runInContext('currentUser.role = "operator"', context);
fixture.assignments[0].incident_status = 'warning';
await context.refresh();
assert.match(element('dashboard').innerHTML, /host-card incident-warning/);
assert.match(element('dashboard').innerHTML, /Warning incident/);
assert.doesNotMatch(element('dashboard').innerHTML, /data-copy-service|data-edit-service/);
const incident = {id: 1,service: 2,status: 'critical',opened: now,closed: null,acknowledged: null};
assert.match(context.renderIncidents([incident], true), /data-ack/);
assert.match(context.renderIncidents([incident], true), />Critical<\/span>/);
vm.runInContext('currentUser.role = "viewer"', context);
assert.doesNotMatch(context.renderIncidents([incident], true), /data-ack/);
assert.equal(vm.runInContext("formatStatus('healthy')", context), 'Healthy');
assert.equal(vm.runInContext("formatStatus('warning')", context), 'Warning');
assert.equal(vm.runInContext("formatStatus('critical')", context), 'Critical');
publicData.devices[0].incident_status = 'critical';
await publicContext.refresh();
assert.match(publicNodes.get('devices').innerHTML, /host-card incident-critical/);
assert.match(publicNodes.get('devices').innerHTML, /Critical incident/);
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicNodes.get('devices').hidden, true);
assert.equal(publicNodes.get('toggle-hosts').textContent, 'Show host cards');
assert.equal(publicNodes.get('toggle-hosts').attributes['aria-expanded'], 'false');
assert.equal(publicStorage.get('field-monitor.status.hide-hosts'), 'true');
await publicContext.refresh();
assert.equal(publicNodes.get('devices').hidden, true);
assert.match(publicNodes.get('incidents').innerHTML, /No active incidents/);
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicNodes.get('devices').hidden, false);
assert.equal(publicNodes.get('toggle-hosts').textContent, 'Hide host cards');
console.log('Operator permissions, capitalised labels, card colours and host visibility smoke tests passed.');

// Simulate a full reload: fresh JavaScript globals, same browser storage.
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicStorage.get('field-monitor.status.hide-hosts'), 'true');
const reloadedPublicContext = vm.createContext({
    document: publicContext.document,
    localStorage: publicContext.localStorage,
    fetch: async () => ({ ok: true, json: async () => publicData }),
    setInterval() {},
});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(reloadedPublicContext);
await reloadedPublicContext.refresh();
assert.equal(publicNodes.get('devices').hidden, true);
assert.equal(publicNodes.get('toggle-hosts').textContent, 'Show host cards');
console.log('Host visibility preference survives a simulated full page reload.');

// Both layouts filter matching service names and omit unrelated hosts/readings.
fixture.latest[0].status = 'healthy';
fixture.services.push({...stateService, id:3, name:'Local RSSI', value_type:'metric', units:'dBm'});
fixture.latest.push({service:3,status:'healthy',value:-60,display_value:'-60',timestamp:now});
fixture.devices.push({id:2,name:'SW002',address:'127.0.0.2',model:'Switch'});
fixture.assignments.push({id:2,project:1,device:2,alias:'Front',visible:1,monitoring:1});
fixture.services.push({...stateService,id:4,assignment:2,name:'Temperature',value_type:'metric',units:'°C'});
const mainStorage = new Map();
context.localStorage = {getItem:key => mainStorage.get(key), setItem:(key,value) => mainStorage.set(key,value)};
await context.refresh();
element('view-list').onclick();
assert.match(element('dashboard').innerHTML, /<table class="host-list">/);
assert.match(element('dashboard').innerHTML, /SW002 - Front/);
element('service-filter').value = 'rSsI';
element('service-filter').oninput();
assert.match(element('dashboard').innerHTML, /Local RSSI/);
assert.doesNotMatch(element('dashboard').innerHTML, /Port status|Temperature|SW002/);
assert.match(element('dashboard').innerHTML, /host-row incident-warning/);
assert.equal(mainStorage.get('field-monitor.main.host-view'), 'list');
assert.equal(mainStorage.get('field-monitor.main.service-filter'), 'rSsI');
await context.refresh();
assert.match(element('dashboard').innerHTML, /<table class="host-list">/);
assert.doesNotMatch(element('dashboard').innerHTML, /SW002/);
element('service-filter').value = 'No matching service';
element('service-filter').oninput();
assert.match(element('dashboard').innerHTML, /No hosts match/);
element('service-filter').value = 'RSSI';
element('service-filter').oninput();

const reloadedMain = vm.createContext({
    document: context.document,
    localStorage: context.localStorage,
    fetch: async path => ({ok:true,json:async () => path === '/api/me'
        ? {id:2,username:'reader',role:'viewer',csrf:'test',must_change_password:0} : fixture}),
    setInterval() {},
});
new vm.Script(script).runInContext(reloadedMain);
await reloadedMain.initializeSession();
assert.match(element('dashboard').innerHTML, /<table class="host-list">/);
assert.match(element('dashboard').innerHTML, /Local RSSI/);
assert.doesNotMatch(element('dashboard').innerHTML, /SW002/);
assert.equal(element('service-filter').value, 'RSSI');
element('clear-service-filter').onclick();
assert.match(element('dashboard').innerHTML, /SW002 - Front/);
element('view-cards').onclick();
assert.match(element('dashboard').innerHTML, /<article class="host-card/);

publicData.devices[0].services = [
    {name:'Remote RSSI',value:'-62',units:'dBm',status:'healthy'},
    {name:'Temperature',value:'42',units:'°C',status:'healthy'},
];
publicData.devices.push({name:'SW002',alias:'Front',status:'healthy',services:[{name:'Temperature',value:'43',units:'°C',status:'critical'}]});
publicData.incidents = [{device:'SW002',alias:'Front',service:'Temperature',status:'critical',opened:now}];
await reloadedPublicContext.refresh();
publicNodes.get('view-list').onclick();
publicNodes.get('service-filter').value = 'rssi';
publicNodes.get('service-filter').oninput();
assert.match(publicNodes.get('devices').innerHTML, /<table class="host-list">/);
assert.match(publicNodes.get('devices').innerHTML, /Remote RSSI/);
assert.doesNotMatch(publicNodes.get('devices').innerHTML, /Temperature|SW002/);
assert.match(publicNodes.get('incidents').innerHTML, /Temperature/);
assert.equal(publicStorage.get('field-monitor.status.host-view'), 'list');
assert.equal(publicStorage.get('field-monitor.status.service-filter'), 'rssi');
assert.equal(publicNodes.get('devices').hidden, true);
assert.equal(publicNodes.get('toggle-hosts').textContent, 'Show host list');
const reloadedFilteredPublic = vm.createContext({
    document: publicContext.document, localStorage: publicContext.localStorage,
    fetch: async () => ({ok:true,json:async () => publicData}), setInterval() {},
});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(reloadedFilteredPublic);
await reloadedFilteredPublic.refresh();
assert.match(publicNodes.get('devices').innerHTML, /<table class="host-list">/);
assert.doesNotMatch(publicNodes.get('devices').innerHTML, /Temperature|SW002/);
assert.equal(publicNodes.get('service-filter').value, 'rssi');
assert.equal(publicNodes.get('devices').hidden, true);
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicNodes.get('devices').hidden, false);
assert.equal(publicNodes.get('toggle-hosts').textContent, 'Hide host list');
publicNodes.get('clear-service-filter').onclick();
assert.match(publicNodes.get('devices').innerHTML, /SW002 - Front/);
publicNodes.get('view-cards').onclick();
assert.match(publicNodes.get('devices').innerHTML, /<article class="host-card/);
console.log('Cards/list layouts, service filters, role restrictions and browser preference reloads passed on both dashboards.');

// Logo URLs update with project selection/data refresh without replacing edits.
fixture.projects[0].logo_url = '/api/project-logo?project=1&v=first';
await reloadedMain.refresh();
assert.equal(element('project-logo').hidden, false);
assert.equal(element('project-logo').getAttribute('src'), fixture.projects[0].logo_url);
element('project-edit-form').elements.namedItem('name').value = 'Unsaved event name';
await reloadedMain.refresh();
assert.equal(element('project-edit-form').elements.namedItem('name').value, 'Unsaved event name');
fixture.projects[0].logo_url = '/api/project-logo?project=1&v=replacement';
await reloadedMain.refresh();
assert.equal(element('project-logo').getAttribute('src'), fixture.projects[0].logo_url);
publicData.logo_url = '/api/public-logo?project=1&v=first';
await reloadedFilteredPublic.refresh();
assert.equal(publicNodes.get('project-logo').hidden, false);
assert.equal(publicNodes.get('project-logo').getAttribute('src'), publicData.logo_url);
publicData.logo_url = null;
await reloadedFilteredPublic.refresh();
assert.equal(publicNodes.get('project-logo').hidden, true);
for (const marker of ['id="incidents"', '<summary>Acknowledged incidents', '<summary>Suppressed service incidents', '<summary>Resolved incidents']) {
    assert.ok(html.indexOf(marker) < html.indexOf('id="dashboard"'));
}
console.log('Project logos, unsaved name edits, and all incident sections above hosts passed.');

vm.runInContext('currentUser.role="admin"', reloadedMain);
fixture.services.find(service => service.id === 3).monitoring = 0;
reloadedMain.renderHosts();
assert.match(element('dashboard').innerHTML, /data-service-monitoring="3" data-enabled="true">Resume/);
assert.match(element('dashboard').innerHTML, /metric-status paused">Paused/);
element('catalogue-host').value = '1';
reloadedMain.renderServiceCatalogue();
assert.match(element('service-catalogue').innerHTML, /Port status/);
assert.doesNotMatch(element('service-catalogue').innerHTML, /Temperature/);
element('catalogue-search').value = 'rssi';
element('catalogue-search').oninput();
assert.match(element('service-catalogue').innerHTML, /Local RSSI/);
assert.doesNotMatch(element('service-catalogue').innerHTML, /Port status/);
element('catalogue-monitoring').value = 'paused';
element('catalogue-monitoring').onchange();
assert.match(element('service-catalogue').innerHTML, /Resume/);
element('catalogue-protocol').value = 'tcp';
element('catalogue-protocol').onchange();
assert.match(element('service-catalogue').innerHTML, /No services match/);
for (let index=0; index<25; index++) {
    fixture.services.push({...stateService,id:100+index,assignment:1,name:'Catalogue item '+index,
        target:'.1.3.6.'+index,enabled:1,monitoring:1});
}
element('catalogue-host').value = '*';
element('catalogue-monitoring').value = '';
element('catalogue-protocol').value = '';
element('catalogue-search').value = 'catalogue';
element('catalogue-search').oninput();
assert.equal(element('catalogue-summary').textContent, 'Showing 20 of 25 matching services');
assert.doesNotMatch(element('service-catalogue').innerHTML, /Catalogue item 20/);
element('catalogue-more').onclick();
assert.equal(element('catalogue-summary').textContent, 'Showing 25 of 25 matching services');
assert.match(element('service-catalogue').innerHTML, /Catalogue item 24/);
fixture.assignments.find(assignment => assignment.id===2).removed = 1;
reloadedMain.renderHosts();
assert.doesNotMatch(element('dashboard').innerHTML, /SW002/);
element('catalogue-host').value = '';
reloadedMain.renderServiceCatalogue();
assert.equal(element('service-catalogue').innerHTML, '');
assert.match(element('catalogue-summary').textContent, /Choose a host/);
console.log('Per-service pause controls, archived-host visibility and bounded service-catalogue filters passed.');

// Hiding services removes readings/actions, but never the host or severity badge.
vm.runInContext('currentUser.role="viewer"', reloadedMain);
reloadedMain.renderHosts();
assert.match(element('dashboard').innerHTML, /Port status/);
element('toggle-services').onclick();
assert.match(element('dashboard').innerHTML, /SW001 - Stage/);
assert.match(element('dashboard').innerHTML, /Warning incident/);
assert.doesNotMatch(element('dashboard').innerHTML, /Port status|Local RSSI|data-service-monitoring/);
assert.equal(element('toggle-services').textContent, 'Show services');
assert.equal(mainStorage.get('field-monitor.main.hide-services'), 'true');
element('view-list').onclick();
assert.match(element('dashboard').innerHTML, /<table class="host-list">/);
assert.doesNotMatch(element('dashboard').innerHTML, /<th>Services<\/th>|Port status/);
await reloadedMain.refresh();
assert.doesNotMatch(element('dashboard').innerHTML, /<th>Services<\/th>|Port status/);

const hostOnlyMain = vm.createContext({
    document: context.document, localStorage: context.localStorage,
    fetch: async path => ({ok:true,json:async () => path === '/api/me'
        ? {id:2,username:'reader',role:'viewer',csrf:'test',must_change_password:0} : fixture}),
    setInterval() {},
});
new vm.Script(script).runInContext(hostOnlyMain);
await hostOnlyMain.initializeSession();
assert.equal(element('toggle-services').textContent, 'Show services');
assert.match(element('dashboard').innerHTML, /SW001 - Stage/);
assert.doesNotMatch(element('dashboard').innerHTML, /Port status/);
element('toggle-services').onclick();
assert.match(element('dashboard').innerHTML, /Port status/);

publicNodes.get('toggle-services').onclick();
assert.match(publicNodes.get('devices').innerHTML, /SW001 - Stage/);
assert.match(publicNodes.get('devices').innerHTML, /Critical incident/);
assert.doesNotMatch(publicNodes.get('devices').innerHTML, /Remote RSSI|Temperature/);
assert.equal(publicStorage.get('field-monitor.status.hide-services'), 'true');
publicNodes.get('view-list').onclick();
assert.doesNotMatch(publicNodes.get('devices').innerHTML, /<th>Services<\/th>|Remote RSSI/);
const hostOnlyPublic = vm.createContext({
    document: publicContext.document, localStorage: publicContext.localStorage,
    fetch: async () => ({ok:true,json:async () => publicData}), setInterval() {},
});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(hostOnlyPublic);
await hostOnlyPublic.refresh();
assert.equal(publicNodes.get('toggle-services').textContent, 'Show services');
assert.doesNotMatch(publicNodes.get('devices').innerHTML, /<th>Services<\/th>|Remote RSSI/);
publicNodes.get('toggle-services').onclick();
assert.match(publicNodes.get('devices').innerHTML, /Remote RSSI/);
console.log('Host-only Cards/List views and service visibility persistence passed on both dashboards.');

publicData.devices = [
    {name:'SW10',alias:'Alpha',status:'healthy',incident_status:null,services:[]},
    {name:'SW2',alias:'Zulu',status:'unreachable',incident_status:'critical',services:[]},
    {name:'SW1',alias:'Middle',status:'unknown',incident_status:'warning',services:[]},
];
publicNodes.get('host-sort').value = 'hostname';
publicNodes.get('host-sort').onchange();
await hostOnlyPublic.refresh();
let ordered = publicNodes.get('devices').innerHTML;
assert.ok(ordered.indexOf('SW1 -') < ordered.indexOf('SW2 -'));
assert.ok(ordered.indexOf('SW2 -') < ordered.indexOf('SW10 -'));
publicNodes.get('host-sort').value = 'status';
publicNodes.get('host-sort').onchange();
ordered = publicNodes.get('devices').innerHTML;
assert.ok(ordered.indexOf('SW2 -') < ordered.indexOf('SW1 -'));
assert.ok(ordered.indexOf('SW1 -') < ordered.indexOf('SW10 -'));
publicNodes.get('host-sort').value = 'status-ok';
publicNodes.get('host-sort').onchange();
assert.ok(publicNodes.get('devices').innerHTML.indexOf('SW10 -') < publicNodes.get('devices').innerHTML.indexOf('SW2 -'));
publicNodes.get('host-sort').value = 'severity';
publicNodes.get('host-sort').onchange();
assert.ok(publicNodes.get('devices').innerHTML.indexOf('SW2 -') < publicNodes.get('devices').innerHTML.indexOf('SW1 -'));
publicNodes.get('host-sort').value = 'alias';
publicNodes.get('host-sort').onchange();
assert.equal(publicStorage.get('field-monitor.status.host-sort'), 'alias');
const sortedPublic = vm.createContext({
    document:publicContext.document,localStorage:publicContext.localStorage,
    fetch:async () => ({ok:true,json:async () => publicData}),setInterval(){},
});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(sortedPublic);
await sortedPublic.refresh();
assert.equal(publicNodes.get('host-sort').value, 'alias');
ordered = publicNodes.get('devices').innerHTML;
assert.ok(ordered.indexOf('SW10 -') < ordered.indexOf('SW1 -'));
assert.ok(ordered.indexOf('SW1 -') < ordered.indexOf('SW2 -'));
publicData.acknowledge_enabled = true;
publicData.can_acknowledge = true;
publicData.csrf = 'status-csrf';
publicData.incidents = [{id:42,device:'SW2',alias:'Zulu',service:'Host ping',status:'unreachable',opened:now}];
await sortedPublic.refresh();
assert.match(publicNodes.get('incidents').innerHTML, /data-status-ack="42"/);
let statusAcknowledgement;
sortedPublic.fetch = async (path, options) => {
    if (path === '/api/status-ack') {
        statusAcknowledgement = {headers:options.headers,body:JSON.parse(options.body)};
        publicData.incidents = [];
        return {ok:true,json:async () => ({ok:true})};
    }
    return {ok:true,json:async () => publicData};
};
await publicNodes.get('incidents').onclick({target:{dataset:{statusAck:'42'},disabled:false}});
assert.equal(statusAcknowledgement.body.id, '42');
assert.equal(statusAcknowledgement.headers['X-CSRF-Token'], 'status-csrf');
assert.match(publicNodes.get('incidents').innerHTML, /No active incidents/);
publicData.can_acknowledge = false;
publicData.incidents = [{id:42,device:'SW2',alias:'Zulu',service:'Host ping',status:'unreachable',opened:now}];
await sortedPublic.refresh();
assert.doesNotMatch(publicNodes.get('incidents').innerHTML, /data-status-ack/);
assert.equal(publicNodes.get('status-ack-note').hidden, false);

let projectSubmission;
hostOnlyMain.fetch = async (path, options) => {
    if (options) {
        projectSubmission = {path,body:JSON.parse(options.body)};
        return {ok:true,json:async () => ({ok:true})};
    }
    return {ok:true,json:async () => fixture};
};
const duplicateForm = element('project-duplicate-form');
duplicateForm.elements.namedItem('name').value = 'Copied event';
await duplicateForm.onsubmit({preventDefault(){},target:duplicateForm});
assert.equal(projectSubmission.path, '/api/project-duplicate');
assert.equal(projectSubmission.body.project, '1');
assert.equal(projectSubmission.body.name, 'Copied event');
assert.equal(duplicateForm.elements.namedItem('name').value, '');
const statusSettingsForm = element('project-status-form');
statusSettingsForm.elements.namedItem('enabled').checked = true;
await statusSettingsForm.onsubmit({preventDefault(){},target:statusSettingsForm});
assert.equal(projectSubmission.path, '/api/project-status-settings');
assert.equal(projectSubmission.body.enabled, true);
console.log('Project duplication/settings, persisted host sorting and authenticated status acknowledgement UI tests passed.');

// Inventory stays collapsed, expands for search, and renders bounded results.
hostOnlyMain.renderInventory();
assert.equal(element('inventory').innerHTML, '');
element('inventory-search').value = 'sW001';
element('inventory-search').oninput();
assert.equal(element('inventory-details').open, true);
assert.match(element('inventory').innerHTML, /SW001/);
assert.doesNotMatch(element('inventory').innerHTML, /SW002/);
element('inventory-search').value = '127.0.0.2';
element('inventory-search').oninput();
assert.match(element('inventory').innerHTML, /SW002/);
assert.doesNotMatch(element('inventory').innerHTML, /SW001/);
for (let index=0; index<60; index++) fixture.devices.push({id:200+index,name:'Bulk-'+index,model:'Industrial',address:'10.44.0.'+index});
element('inventory-search').value = 'industrial';
element('inventory-search').oninput();
assert.equal(element('inventory-results').textContent, 'Showing 50 of 60 matching devices');
assert.doesNotMatch(element('inventory').innerHTML, /Bulk-50/);
element('inventory-more').onclick();
assert.match(element('inventory').innerHTML, /Bulk-59/);
element('inventory-details').open = false;
element('inventory-details').ontoggle();
assert.equal(element('inventory').innerHTML, '');
element('inventory-details').open = true;
element('inventory-details').ontoggle();
assert.match(element('inventory').innerHTML, /Bulk-59/);
await hostOnlyMain.refresh();
assert.equal(element('inventory-search').value, 'industrial');
assert.equal(element('inventory-details').open, true);
assert.equal(element('project-settings-logo').getAttribute('src'), fixture.projects[0].logo_url);

publicData.viewer = null;
await sortedPublic.refresh();
assert.equal(publicNodes.get('status-session').textContent, 'Not signed in');
assert.equal(publicNodes.get('status-session-link').textContent, 'Sign in');
publicData.viewer = {username:'operator',role:'operator',must_change_password:false};
await sortedPublic.refresh();
assert.equal(publicNodes.get('status-session').textContent, 'Signed in: operator · Operator');
assert.equal(publicNodes.get('status-session-link').textContent, 'Dashboard');
publicData.viewer.must_change_password = true;
await sortedPublic.refresh();
assert.equal(publicNodes.get('status-session-link').textContent, 'Change password');
assert.equal(publicNodes.get('status-session-link').getAttribute('href'), '/login');
console.log('Collapsible/searchable inventory, project panel preview and public login indicators passed.');
