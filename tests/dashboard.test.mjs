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
            insertAdjacentHTML(position, markup) { this.innerHTML = position === 'afterbegin' ? markup + this.innerHTML : this.innerHTML + markup; },
            remove() { this.removed = true; },
            classList: { toggle() {}, add() {}, remove() {} },
            querySelectorAll() { return []; },
            querySelector() { return { focus() {} }; },
            attributes: {},
            setAttribute(key, value) { this.attributes[key] = value; },
            getAttribute(key) { return this.attributes[key]; },
            focus() { this.focused = true; },
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
assert.equal(element('assignments').innerHTML, '');
element('assignments-details').open = true;
element('assignments-details').ontoggle();
assert.match(element('assignments').innerHTML, /Device ID - Alias \/ Address/);
assert.match(element('assignments').innerHTML, /SW001 - Stage \/ 127\.0\.0\.1/);
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
const alarmEditLine = context.historyGraph([sample(30,90,'critical',2),sample(20,60)], {...numeric,revision:2});
assert.match(alarmEditLine,/L /);
assert.equal((alarmEditLine.match(/<path /g) || []).length,1);
assert.doesNotMatch(line, /NaN|Infinity/);
const steps = context.historyGraph([sample(30, 2), sample(20, 1), sample(10, 1)], stateService);
assert.match(steps, /H .* V /);
assert.match(steps, />Up<\/text>/);
assert.match(steps, />Down<\/text>/);
const gap = context.historyGraph([sample(30, 2), sample(20, null, 'blocked'), sample(10, 1)], numeric);
assert.equal((gap.match(/<path /g) || []).length, 2);
const oldConfig = context.historyGraph([{...sample(30, 90, 'healthy', 2),measurement_revision:2}], numeric);
assert.match(oldConfig, /No usable readings/);
assert.match(context.historyGraph([], numeric), /No usable readings/);
assert.doesNotMatch(context.historyGraph([sample(10, 0)], numeric), /NaN|Infinity/);
const escaped = context.historyGraph([sample(10, 1)], { ...numeric, name: '<img src=x>' });
assert.doesNotMatch(escaped, /<img/);
context.historyView(false);
assert.equal(element('history-graph').hidden, true);
assert.equal(element('readings').hidden, false);
console.log('Dashboard smoke tests passed: cards, menus, alias/state editors, dependency display, graphs and gaps.');

// The anonymous overview must render active issues before equipment cards,
// while escaping operator-controlled names and providing an empty state.
const statusPage = await readFile(new URL('../app/status.html', import.meta.url), 'utf8');
assert.ok(statusPage.indexOf('id="incidents"') < statusPage.indexOf('id="devices"'));
const publicNodes = new Map();
const publicData = {
    project: 'Deployment', updated: now,
    viewer:{username:'reader',role:'viewer',must_change_password:false},can_view_hosts:true,
    devices: [{ name: 'SW001', alias: 'Stage', status: 'unreachable', services: [] }],
    incidents: [{ device: 'SW001', alias: '<img src=x>', service: 'Host ping', status: 'unreachable', opened: now }],
};
const publicStorage = new Map();
const publicContext = vm.createContext({
    localStorage: {getItem: key => publicStorage.get(key), setItem: (key, value) => publicStorage.set(key, value)},
    document: { getElementById(id) {
        if (!publicNodes.has(id)) publicNodes.set(id, { innerHTML: '', textContent: '', open:false, showModal(){this.open=true;}, close(){this.open=false;}, attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }, getAttribute(key) { return this.attributes[key]; } });
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
assert.match(publicNodes.get('incidents').innerHTML, /No active issues/);
console.log('Public incident overview smoke tests passed.');

// Checkbox values must be sent as booleans, including an explicit false when
// an administrator allows the user to keep their assigned password.
let submittedUser;
context.fetch = async (path, options) => {
    if (options?.method === 'POST') submittedUser = { path, body: JSON.parse(options.body) };
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

// User edits use an independent dialog and preserve the add-user draft.
userForm.elements.namedItem('username').value = 'unfinished-new-user';
context.openUserEditor(2);
const userEdit = element('user-edit-form');
assert.equal(element('user-editor').open, true);
assert.equal(userEdit.elements.namedItem('username').value, 'reader');
assert.equal(userEdit.elements.namedItem('email').value, 'reader@example.com');
assert.equal(userEdit.elements.namedItem('must_change_password').checked, false);
assert.equal(userForm.elements.namedItem('username').value, 'unfinished-new-user');
element('cancel-user-edit').onclick();
assert.equal(element('user-editor').open, false);
context.openUserEditor(2);
userEdit.elements.namedItem('full_name').value = 'Changed Full Name';
await context.loadAdmin();
assert.equal(userEdit.elements.namedItem('full_name').value, 'Changed Full Name');
const validUserFetch = context.fetch;
context.fetch = async (path, options) => options
    ? {ok:false,json:async () => ({error:'Invalid account details'})} : validUserFetch(path, options);
await userEdit.onsubmit({preventDefault(){},target:userEdit});
assert.equal(element('user-editor').open, true);
assert.equal(userEdit.elements.namedItem('full_name').value, 'Changed Full Name');
assert.equal(element('user-edit-feedback').textContent, 'Invalid account details');
context.fetch = validUserFetch;
await userEdit.onsubmit({preventDefault(){},target:userEdit});
assert.equal(submittedUser.path, '/api/user-edit');
assert.equal(submittedUser.body.full_name, 'Changed Full Name');
assert.equal(Number(submittedUser.body.user), 2);
assert.equal(element('user-editor').open, false);
assert.equal(userForm.elements.namedItem('username').value, 'unfinished-new-user');
console.log('Separate user editing dialog, cancel, errors and save passed.');

// Operators can acknowledge, but never see configuration actions on the cards.
const previousFetch = context.fetch;
context.fetch = async (path, options) => path === '/api/state'
    ? {ok: true, json: async () => fixture} : previousFetch(path, options);
vm.runInContext('currentUser.role = "operator"', context);
fixture.assignments[0].incident_status = 'warning';
await context.refresh();
assert.match(element('dashboard').innerHTML, /host-card incident-warning/);
assert.match(element('dashboard').innerHTML, /Warning issue/);
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
assert.match(publicNodes.get('devices').innerHTML, /Critical issue/);
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicNodes.get('devices').hidden, true);
assert.equal(publicNodes.get('host-controls').hidden, true);
assert.equal(publicNodes.get('live-host-panel').hidden, true);
assert.equal(publicNodes.get('toggle-hosts').textContent, 'Show host cards');
assert.equal(publicNodes.get('toggle-hosts').attributes['aria-expanded'], 'false');
assert.equal(publicStorage.get('field-monitor.status.hide-hosts'), 'true');
await publicContext.refresh();
assert.equal(publicNodes.get('devices').hidden, true);
assert.equal(publicNodes.get('host-controls').hidden, true);
assert.equal(publicNodes.get('live-host-panel').hidden, true);
assert.match(publicNodes.get('incidents').innerHTML, /No active issues/);
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicNodes.get('devices').hidden, false);
assert.equal(publicNodes.get('host-controls').hidden, false);
assert.equal(publicNodes.get('live-host-panel').hidden, false);
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
assert.equal(publicNodes.get('host-controls').hidden, true);
assert.equal(publicNodes.get('live-host-panel').hidden, true);
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
assert.equal(publicNodes.get('host-controls').hidden, true);
assert.equal(publicNodes.get('live-host-panel').hidden, true);
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
assert.equal(publicNodes.get('host-controls').hidden, true);
assert.equal(publicNodes.get('live-host-panel').hidden, true);
publicNodes.get('toggle-hosts').onclick();
assert.equal(publicNodes.get('devices').hidden, false);
assert.equal(publicNodes.get('host-controls').hidden, false);
assert.equal(publicNodes.get('live-host-panel').hidden, false);
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
for (const marker of ['id="incidents"', 'id="acknowledged-panel"', 'id="suppressed-panel"', 'id="resolved-panel"']) {
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
assert.match(element('dashboard').innerHTML, /Warning issue/);
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
assert.match(publicNodes.get('devices').innerHTML, /Critical issue/);
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
let rejectStatusAcknowledgement = false;
sortedPublic.fetch = async (path, options) => {
    if (path === '/api/status-ack') {
        statusAcknowledgement = {headers:options.headers,body:JSON.parse(options.body)};
        if (rejectStatusAcknowledgement) return {ok:false,json:async () => ({error:'Status acknowledgement failed'})};
        publicData.incidents = [];
        return {ok:true,json:async () => ({ok:true})};
    }
    return {ok:true,json:async () => publicData};
};
await publicNodes.get('incidents').onclick({target:{dataset:{statusAck:'42'},disabled:false}});
assert.equal(statusAcknowledgement, undefined);
assert.equal(publicNodes.get('acknowledgement-dialog').open, true);
assert.match(publicNodes.get('acknowledgement-context').textContent, /SW2 - Zulu/);
assert.match(publicNodes.get('acknowledgement-context').textContent, /Issue #42/);
assert.match(publicNodes.get('incidents').innerHTML, /Issue #42/);
publicNodes.get('cancel-acknowledgement').onclick();
await publicNodes.get('confirm-acknowledgement').onclick();
assert.equal(statusAcknowledgement, undefined);
assert.equal(publicNodes.get('acknowledgement-dialog').open, false);
assert.equal(publicData.incidents.length, 1);
await publicNodes.get('incidents').onclick({target:{dataset:{statusAck:'42'},disabled:false}});
rejectStatusAcknowledgement = true;
await publicNodes.get('confirm-acknowledgement').onclick();
assert.equal(publicNodes.get('acknowledgement-dialog').open, true);
assert.equal(publicNodes.get('acknowledgement-feedback').textContent, 'Status acknowledgement failed');
assert.equal(publicNodes.get('confirm-acknowledgement').disabled, false);
rejectStatusAcknowledgement = false;
await publicNodes.get('confirm-acknowledgement').onclick();
assert.equal(publicNodes.get('acknowledgement-dialog').open, false);
assert.equal(statusAcknowledgement.body.id, '42');
assert.equal(statusAcknowledgement.headers['X-CSRF-Token'], 'status-csrf');
assert.match(publicNodes.get('incidents').innerHTML, /No active issues/);
publicData.can_acknowledge = false;
publicData.incidents = [{id:42,device:'SW2',alias:'Zulu',service:'Host ping',status:'unreachable',opened:now}];
await sortedPublic.refresh();
assert.doesNotMatch(publicNodes.get('incidents').innerHTML, /data-status-ack/);
assert.equal(publicNodes.get('status-ack-note').hidden, false);

let projectSubmission;
hostOnlyMain.fetch = async (path, options) => {
    if (options?.method === 'POST') {
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
assert.equal(publicNodes.get('status-session-link').textContent, 'Admin Dashboard');
publicData.viewer.must_change_password = true;
await sortedPublic.refresh();
assert.equal(publicNodes.get('status-session-link').textContent, 'Change password');
assert.equal(publicNodes.get('status-session-link').getAttribute('href'), '/login?next=%2Fstatus');
console.log('Collapsible/searchable inventory, project panel preview and public login indicators passed.');
// Library search mirrors inventory: collapsed by default, bounded, and refresh-safe.
assert.ok(html.indexOf('id="toggle-project-configuration"') < html.indexOf('id="toggle-permanent-inventory"'));
assert.equal(element('service-library').innerHTML, '');
const savedLibrary = fixture.service_templates;
fixture.service_templates = Array.from({length:60}, (_, id) => ({id:9000+id,
    name:`Voltage ${id}`,kind:'modbus',target:'80',units:'V'}));
context.renderServiceLibrary();
element('library-search').value = 'vOlTaGe';
element('library-search').oninput();
assert.equal(element('library-details').open,true);
assert.equal(element('library-results').textContent,'Showing 50 of 60 matching services');
assert.doesNotMatch(element('service-library').innerHTML,/Voltage 50/);
element('library-more').onclick();
assert.match(element('service-library').innerHTML,/Voltage 59/);
assert.match(element('service-library').innerHTML,/data-apply-template="9059"/);
assert.match(element('service-library').innerHTML,/data-edit-template="9059"/);
assert.match(element('service-library').innerHTML,/data-delete-template="9059"/);
element('library-details').open=false;
element('library-details').ontoggle();
assert.equal(element('service-library').innerHTML,'');
await context.refresh();
assert.equal(element('library-details').open,false);
assert.equal(element('library-search').value,'vOlTaGe');
for (const query of ['MODBUS','80','V']) {
    element('library-search').value=query;
    element('library-search').oninput();
    assert.equal(element('library-results').textContent,'Showing 50 of 60 matching services');
}
element('library-search').value='no match';
element('library-search').oninput();
assert.match(element('service-library').innerHTML,/No library services match/);
element('library-clear').onclick();
assert.equal(element('library-search').value,'');
assert.equal(element('library-results').textContent,'Showing 50 of 60 matching services');
fixture.service_templates=savedLibrary;
element('library-details').open=false;
context.renderServiceLibrary();
console.log('Library search/collapse preserves filters, paging and service actions; project configuration precedes inventory.');


// Section preferences persist independently and remain applied during polling.
for (const [key, panel, initialHidden] of [
    ['acknowledged', 'acknowledged-panel', true],
    ['suppressed', 'suppressed-panel', true],
    ['resolved', 'resolved-panel', true],
    ['live', 'live-status-panel', false],
]) {
    assert.equal(element(panel).hidden, initialHidden);
    element(`toggle-${key}`).onclick();
    assert.equal(element(panel).hidden, !initialHidden);
    assert.equal(mainStorage.get(`field-monitor.main.panel.${key}`), String(initialHidden));
    assert.equal(element(`toggle-${key}`).getAttribute('aria-expanded'), String(initialHidden));
}
await hostOnlyMain.refresh();
assert.equal(element('live-status-panel').hidden, true);
const sectionReload = vm.createContext({
    document: context.document, localStorage: context.localStorage,
    fetch: async path => ({ok:true,json:async () => path === '/api/me'
        ? {id:2,username:'reader',role:'viewer',csrf:'test',must_change_password:0} : fixture}),
    setInterval() {},
});
new vm.Script(script).runInContext(sectionReload);
await sectionReload.initializeSession();
assert.equal(element('live-status-panel').hidden, true);
for (const key of ['acknowledged', 'suppressed', 'resolved']) {
    assert.equal(element(`${key}-panel`).hidden, false);
    assert.match(element(`toggle-${key}`).textContent, /^Hide /);
}
assert.ok(html.indexOf('id="toggle-acknowledged"') < html.indexOf('id="incidents"'));
assert.match(sectionReload.renderIncidents([{acknowledged:123, acknowledged_by_username:'<operator>'}]), /by &lt;operator&gt;/);
assert.match(sectionReload.renderIncidents([{acknowledged:123}]), /Unknown user \(legacy\)/);
console.log('Acknowledgement attribution and persisted section visibility passed.');

publicData.acknowledged_incidents = [{device:'SW1',alias:'<event>',service:'RSSI',status:'critical',acknowledged:now,closed:null,acknowledged_by_username:'<operator>'}];
await sortedPublic.refresh();
assert.equal(publicNodes.get('acknowledged-panel').hidden, true);
publicNodes.get('toggle-acknowledged').onclick();
assert.equal(publicNodes.get('acknowledged-panel').hidden, false);
assert.equal(publicNodes.get('toggle-acknowledged').getAttribute('aria-pressed'), 'true');
assert.equal(publicStorage.get('field-monitor.status.show-acknowledged'), 'true');
assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /RSSI/);
assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /&lt;event&gt;/);
assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /Still open/);
const acknowledgedReload = vm.createContext({document:publicContext.document,localStorage:publicContext.localStorage,
    fetch:async () => ({ok:true,json:async () => publicData}),setInterval(){}});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(acknowledgedReload);
await acknowledgedReload.refresh();
assert.equal(publicNodes.get('acknowledged-panel').hidden, false);
publicNodes.get('toggle-acknowledged').onclick();
assert.equal(publicNodes.get('acknowledged-panel').hidden, true);
assert.equal(publicNodes.get('toggle-acknowledged').getAttribute('aria-pressed'), 'false');
console.log('Public acknowledged issues and persisted visibility passed.');

assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /by &lt;operator&gt;/);
publicData.acknowledged_incidents[0].acknowledged_by_username = null;
await acknowledgedReload.refresh();
assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /Unknown user \(legacy\)/);

assert.match(html, />Status Dashboard<\/a>/);
assert.match(html, /name="full_name"/);
assert.match(sectionReload.renderIncidents([{acknowledged:123, acknowledged_by_username:'login', acknowledged_by_full_name:'<Alex Example>'}]), /by &lt;Alex Example&gt;/);
publicData.viewer = {username:'operator',full_name:'Alex Example',role:'operator',must_change_password:false};
publicData.acknowledged_incidents[0].acknowledged_by_full_name = '<Alex Example>';
await acknowledgedReload.refresh();
assert.equal(publicNodes.get('status-session').textContent, 'Signed in: Alex Example · Operator');
assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /by &lt;Alex Example&gt;/);
const configurationPanels = ['permanent-inventory', 'project-configuration', 'service-library-panel',
    'user-management-panel', 'reminder-panel', 'telegram-panel', 'whatsapp-panel', 'backup-panel'];
for (const panel of configurationPanels) {
    assert.equal(element(panel).hidden, true);
    element(`toggle-${panel}`).onclick();
    assert.equal(element(panel).hidden, false);
    assert.equal(element(`toggle-${panel}`).getAttribute(panel === 'project-configuration' ? 'aria-pressed' : 'aria-selected'), 'true');
    assert.equal(element(`toggle-${panel}`).getAttribute(panel === 'project-configuration' ? 'aria-pressed' : 'aria-selected'), 'true');
    for (const other of configurationPanels.filter(id => id !== panel)) assert.equal(element(other).hidden, true);
    element(`toggle-${panel}`).onclick();
    assert.equal(element(panel).hidden, true, 'Clicking the current tab closes it');
    assert.equal(element(`toggle-${panel}`).getAttribute(panel === 'project-configuration' ? 'aria-pressed' : 'aria-selected'), 'false');
    assert.equal(element(`toggle-${panel}`).getAttribute('tabindex'), '0');
}
element('toggle-permanent-inventory').onclick();
let navigationPrevented = false;
element('toggle-permanent-inventory').onkeydown({key:'ArrowRight',preventDefault(){navigationPrevented=true;}});
assert.equal(navigationPrevented, true);
assert.equal(element('service-library-panel').hidden, false);
assert.equal(element('permanent-inventory').hidden, true);
assert.equal(element('toggle-service-library-panel').focused, true);
element('toggle-permanent-inventory').onclick();
await sectionReload.refresh();
assert.equal(element('permanent-inventory').hidden, false);
const namedMain = vm.createContext({document:context.document,localStorage:context.localStorage,
    fetch:async path => ({ok:true,json:async () => path === '/api/me'
        ? {id:2,username:'reader',full_name:'Sam Example',role:'viewer',csrf:'test',must_change_password:0} : fixture}),setInterval(){}});
new vm.Script(script).runInContext(namedMain);
await namedMain.initializeSession();
assert.equal(element('signed-in').textContent, 'Sam Example · View Only');
console.log('Full names and Status Dashboard navigation passed.');

for (const panel of configurationPanels) {
    assert.equal(element(panel).hidden, true, 'Configuration panel must reset on reload');
    assert.equal(element(`toggle-${panel}`).getAttribute('aria-expanded'), 'false');
    assert.doesNotMatch(element(`toggle-${panel}`).textContent, /^(Show|Hide) /);
}
assert.doesNotMatch(html, /<details data-admin/);
console.log('Exclusive configuration tabs support keyboard navigation and start closed on reload.');

assert.ok(statusPage.indexOf('id="acknowledged-incidents"') < statusPage.indexOf('id="host-controls"'));
assert.ok(statusPage.indexOf('id="host-controls"') < statusPage.indexOf('id="view-cards"'));
assert.ok(statusPage.indexOf('id="view-list"') < statusPage.indexOf('id="devices"'));

fixture.settings.active_run = '0';
fixture.settings.paused_run = '1';
await namedMain.refresh();
assert.equal(element('monitoring-toggle').textContent, 'Resume all monitoring');
assert.equal(element('monitoring-toggle').disabled, false);
assert.equal(element('monitoring-toggle').getAttribute('aria-pressed'), 'false');
assert.match(element('active').textContent, /Test · deployment 1/);
assert.equal(element('monitoring-state').textContent, 'Paused');
assert.equal(element('monitoring-state').className, 'monitoring-badge monitoring-paused');
fixture.settings.active_run = '1';
fixture.settings.paused_run = '0';
await namedMain.refresh();
assert.equal(element('monitoring-toggle').textContent, 'Pause all monitoring');
assert.equal(element('monitoring-toggle').disabled, false);
assert.equal(element('monitoring-toggle').getAttribute('aria-pressed'), 'true');
assert.equal(element('monitoring-state').textContent, 'Active');
assert.equal(element('monitoring-state').className, 'monitoring-badge monitoring-active');
console.log('Resume controls preserve paused deployment identity and display the matching coloured status badge.');

const monitoringRequests = [];
const originalNamedFetch = namedMain.fetch;
namedMain.fetch = async (path, options) => {
    if (options?.method === 'POST') {
        monitoringRequests.push({path,body:JSON.parse(options.body)});
        fixture.settings.active_run = path === '/api/pause' ? '0' : '1';
        fixture.settings.paused_run = path === '/api/pause' ? '1' : '0';
        return {ok:true,json:async () => ({ok:true})};
    }
    return originalNamedFetch(path, options);
};
await element('monitoring-toggle').onclick();
assert.equal(monitoringRequests[0].path, '/api/pause');
assert.equal(element('monitoring-toggle').textContent, 'Resume all monitoring');
await element('monitoring-toggle').onclick();
assert.equal(monitoringRequests[1].path, '/api/resume');
assert.equal(monitoringRequests[1].body.project, '1');
assert.equal(element('monitoring-toggle').textContent, 'Pause all monitoring');
assert.match(html, /@keyframes paused-monitoring/);
assert.match(html, /prefers-reduced-motion: reduce/);

publicData.monitoring_paused = true;
publicData.project = 'Paused event';
publicData.logo_url = '/api/public-logo?project=1&v=paused';
await acknowledgedReload.refresh();
assert.equal(publicNodes.get('project').textContent, 'Paused event');
assert.equal(publicNodes.get('project-logo').hidden, false);
assert.equal(publicNodes.get('summary').textContent, 'Monitoring paused');

// Starting a deployment must wait for explicit confirmation; cancelling is inert.
const deploymentRequests = [];
let rejectDeployment = false;
namedMain.fetch = async (path, options) => {
    if (options?.method === 'POST') {
        deploymentRequests.push({path,body:JSON.parse(options.body)});
        return {ok:!rejectDeployment,json:async () => rejectDeployment
            ? {error:'Cannot start deployment'} : {ok:true}};
    }
    return originalNamedFetch(path, options);
};
element('activate').onclick();
assert.equal(element('deployment-confirmation').open, true);
assert.equal(deploymentRequests.length, 0);
assert.equal(element('deployment-confirmation-project').textContent, 'Project: Test');
element('cancel-deployment').onclick();
element('deployment-confirmation').onclose();
assert.equal(element('deployment-confirmation').open, false);
await element('confirm-deployment').onclick();
assert.equal(deploymentRequests.length, 0);
element('activate').onclick();
await element('confirm-deployment').onclick();
assert.equal(deploymentRequests.length, 0);
assert.match(element('deployment-confirmation-feedback').textContent, /Enter a deployment description/);
element('deployment-description').value = 'Stage setup and testing';
rejectDeployment = true;
await element('confirm-deployment').onclick();
assert.equal(deploymentRequests[0].path, '/api/activate');
assert.equal(deploymentRequests[0].body.project, 1);
assert.equal(deploymentRequests[0].body.description, 'Stage setup and testing');
assert.equal(element('deployment-confirmation').open, true);
assert.equal(element('deployment-confirmation-feedback').textContent, 'Cannot start deployment');
assert.equal(element('confirm-deployment').disabled, false);
rejectDeployment = false;
await element('confirm-deployment').onclick();
assert.equal(deploymentRequests.length, 2);
assert.equal(element('deployment-confirmation').open, false);
console.log('New deployment requires Continue; Cancel sends no request and failures remain reviewable.');

// Login preserves the originating dashboard through normal and forced-password flows.
const loginPage = await readFile(new URL('../app/login.html', import.meta.url), 'utf8');
const loginScript = loginPage.match(/<script>([\s\S]*?)<\/script>/)[1];
async function checkLoginReturn(search, expected, forcePassword = false, rejectLogin = false) {
    const redirects = [];
    let authenticated = false;
    let mustChange = forcePassword;
    const loginContext = vm.createContext({
        document:context.document, FormData:context.FormData, URLSearchParams,
        location:{search,assign:path => redirects.push(path)},
        fetch:async (path, options) => {
            if (path === '/api/me') return {ok:authenticated,json:async () => ({csrf:'login-test',must_change_password:mustChange})};
            if (path === '/api/login') {
                if (rejectLogin) return {ok:false,json:async () => ({error:'Invalid login'})};
                authenticated = true;
            }
            if (path === '/api/password') mustChange = false;
            return {ok:true,json:async () => ({ok:true})};
        },
    });
    new vm.Script(loginScript).runInContext(loginContext);
    await loginContext.session();
    const loginForm = element('login-form');
    loginForm.elements.namedItem('username').value = 'operator';
    loginForm.elements.namedItem('password').value = 'Password-12345';
    await loginForm.onsubmit({preventDefault(){},target:loginForm});
    assert.equal(element('back-dashboard').getAttribute('href'), expected);
    if (rejectLogin) {
        assert.equal(redirects.length, 0);
        assert.equal(element('message').textContent, 'Invalid login');
        return;
    }
    if (forcePassword) {
        assert.equal(redirects.length, 0);
        assert.equal(element('password-section').hidden, false);
        const passwordForm = element('password-form');
        passwordForm.elements.namedItem('password').value = 'New-password-123';
        passwordForm.elements.namedItem('confirm').value = 'New-password-123';
        await passwordForm.onsubmit({preventDefault(){},target:passwordForm});
    }
    assert.deepEqual(redirects, [expected]);
}
await checkLoginReturn('?next=%2Fstatus', '/status');
await checkLoginReturn('?next=%2Fstatus', '/status', true);
await checkLoginReturn('?next=%2F', '/');
await checkLoginReturn('', '/', true);
await checkLoginReturn('?next=https%3A%2F%2Fexample.com', '/');
await checkLoginReturn('?next=%2F%2Fexample.com', '/');
await checkLoginReturn('?next=%2Funknown', '/');
await checkLoginReturn('?next=%2Fstatus', '/status', false, true);
assert.match(statusPage, /href="\/login\?next=%2Fstatus"/);
console.log('Login returns to its originating dashboard, including password changes; external redirects are rejected.');

// Session-duration form saves whole-hour settings without losing unfinished edits on refresh.
const sessionSettingsForm = element('session-settings-form');
sessionSettingsForm.elements.namedItem('hours').value = '24';
await namedMain.refresh();
assert.equal(sessionSettingsForm.elements.namedItem('hours').value, '24');
let savedSessionHours;
namedMain.fetch = async (path, options) => {
    if (path === '/api/session-settings') {
        savedSessionHours = JSON.parse(options.body).hours;
        fixture.settings.session_hours = String(savedSessionHours);
        return {ok:true,json:async () => ({ok:true})};
    }
    return originalNamedFetch(path, options);
};
await sessionSettingsForm.onsubmit({preventDefault(){},target:sessionSettingsForm});
assert.equal(savedSessionHours, 24);
assert.equal(sessionSettingsForm.elements.namedItem('hours').value, '24');
assert.match(element('session-settings-feedback').textContent, /Applies to new sign-ins/);
console.log('Admin session-duration form preserves edits and saves the configured lifetime.');

let adminAcknowledgementRequests = 0;
let rejectAdminAcknowledgement = false;
namedMain.fetch = async (path, options) => {
    if (path === '/api/ack') {
        adminAcknowledgementRequests += 1;
        if (rejectAdminAcknowledgement) return {ok:false,json:async () => ({error:'Admin acknowledgement failed'})};
        assert.equal(JSON.parse(options.body).id, 42);
        return {ok:true,json:async () => ({ok:true})};
    }
    return originalNamedFetch(path, options);
};
namedMain.acknowledgeIssue(42);
assert.equal(adminAcknowledgementRequests, 0);
assert.equal(element('acknowledgement-dialog').open, true);
element('cancel-acknowledgement').onclick();
await element('confirm-acknowledgement').onclick();
assert.equal(adminAcknowledgementRequests, 0);
assert.equal(element('acknowledgement-dialog').open, false);
namedMain.acknowledgeIssue(42);
rejectAdminAcknowledgement = true;
await element('confirm-acknowledgement').onclick();
assert.equal(element('acknowledgement-dialog').open, true);
assert.equal(element('acknowledgement-feedback').textContent, 'Admin acknowledgement failed');
rejectAdminAcknowledgement = false;
await element('confirm-acknowledgement').onclick();
assert.equal(adminAcknowledgementRequests, 2);
assert.equal(element('acknowledgement-dialog').open, false);
console.log('Both dashboards require confirmation before acknowledging; Cancel sends no request.');

const reminderForm = element('reminder-settings-form');
reminderForm.elements.namedItem('minutes').value = '15';
await namedMain.refresh();
assert.equal(reminderForm.elements.namedItem('minutes').value, '15');
let savedReminderMinutes;
namedMain.fetch = async (path, options) => {
    if (path === '/api/reminder-settings') {
        savedReminderMinutes = JSON.parse(options.body).minutes;
        fixture.settings.reminder_minutes = String(savedReminderMinutes);
        return {ok:true,json:async () => ({ok:true})};
    }
    return originalNamedFetch(path, options);
};
await reminderForm.onsubmit({preventDefault(){},target:reminderForm});
assert.equal(savedReminderMinutes, 15);
assert.equal(reminderForm.elements.namedItem('minutes').value, '15');
assert.equal(element('reminder-settings-feedback').textContent, 'Reminder interval saved.');
console.log('Shared issue reminder form saves interval and preserves unfinished edits.');

assert.match(namedMain.renderIncidents([{id:123,status:'critical',opened:now}]), /Issue #123/);
assert.match(namedMain.renderIncidents([{id:124,status:'warning',opened:now,acknowledged:now}]), /Issue #124/);
publicData.acknowledged_incidents = [{id:125,device:'SW1',alias:'Stage',service:'RSSI',status:'critical',acknowledged:now}];
await acknowledgedReload.refresh();
assert.match(publicNodes.get('acknowledged-incidents').innerHTML, /Issue #125/);

assert.match(namedMain.renderIncidents([{id:900,number:1,status:'critical',opened:now}], true), /Issue #1<\/strong>/);
assert.doesNotMatch(namedMain.renderIncidents([{id:900,number:1,status:'critical',opened:now}]), /Issue #900/);
publicData.incidents = [{id:901,number:2,device:'Radio',alias:'Stage',service:'RSSI',status:'critical',opened:now}];
publicData.can_acknowledge = true;
await acknowledgedReload.refresh();
assert.match(publicNodes.get('incidents').innerHTML, /Issue #2<\/strong>/);
assert.match(publicNodes.get('incidents').innerHTML, /data-status-ack="901"/);
fixture.runs[0].description = 'Event setup';
fixture.runs[0].started = now;
await namedMain.refresh();
assert.match(element('deployment-details').textContent, /Event setup/);
assert.match(element('deployment-details').textContent, /Started/);
console.log('Per-deployment issue labels preserve acknowledgement IDs; deployment descriptions are displayed.');

// Inventory defaults use the common configuration editor but a separate API target.
const defaultFixture = {
    ...fixture, projects:[{id:1,name:'First event'},{id:2,name:'Second event'}],
    devices:[{id:1,name:'Radio-01',model:'Radio',address:'192.0.2.1'}],
    assignments:[{id:1,device:1,project:1,alias:'Stage',visible:1,monitoring:1}],
    services:[{id:1,assignment:1,name:'Host ping',kind:'ping'}, {...stateService,id:2,assignment:1}],
    device_service_defaults:[{...stateService,id:7,device:1}],
    service_templates:[{...stateService,id:8,name:'Library RSSI'}],
    incident_lists:{active:[],acknowledged:[],resolved:[],suppressed:[]},
};
let defaultSubmission;
let rejectDefaultSave = false;
const defaultsContext = vm.createContext({
    document:context.document,localStorage:context.localStorage,FormData:context.FormData,
    confirm:() => true,setInterval(){},
    fetch:async (path, options) => {
        if (options?.method === 'POST') {
            defaultSubmission = {path,body:JSON.parse(options.body)};
            return {ok:!rejectDefaultSave,json:async () => rejectDefaultSave ? {error:'Duplicate service name'} : {ok:true}};
        }
        return {ok:true,json:async () => path === '/api/me'
            ? {id:1,username:'admin',role:'admin',csrf:'test',must_change_password:0}
            : path === '/api/users' ? []
            : path === '/api/telegram' || path === '/api/whatsapp' ? {configuration:{},outbox:[]}
            : defaultFixture};
    },
});
new vm.Script(script).runInContext(defaultsContext);
await defaultsContext.initializeSession();
defaultsContext.openDeviceDefaults(1);
assert.equal(element('device-default-manager').open, true);
assert.match(element('device-default-list').innerHTML, /Port status/);
assert.match(element('device-default-source').innerHTML, /First event/);
defaultsContext.openDeviceDefaultEditor(7);
assert.equal(element('service-editor').open, true);
const defaultEdit = element('service-edit-form');
assert.equal(defaultEdit.elements.namedItem('community').value, '');
defaultEdit.elements.namedItem('name').value = 'Changed device default';
await defaultsContext.refresh();
assert.equal(defaultEdit.elements.namedItem('name').value, 'Changed device default');
rejectDefaultSave = true;
await defaultEdit.onsubmit({preventDefault(){},target:defaultEdit});
assert.equal(element('service-editor').open, true);
assert.equal(element('service-edit-feedback').textContent, 'Duplicate service name');
rejectDefaultSave = false;
await defaultEdit.onsubmit({preventDefault(){},target:defaultEdit});
assert.equal(defaultSubmission.path, '/api/device-default-edit');
assert.equal(defaultSubmission.body.device, 1);
assert.equal(String(defaultSubmission.body.default_service), '7');
assert.equal(defaultSubmission.body.name, 'Changed device default');
assert.equal(element('service-editor').open, false);
assert.equal(element('device-default-manager').open, true);
assert.equal(element('device-default-template-name').disabled,true);
element('device-default-template').value = '8';
element('device-default-template').onchange();
assert.equal(element('device-default-template-name').value,'Library RSSI');
assert.equal(element('device-default-template-name').disabled,false);
element('device-default-template-name').value='RSSI';
await defaultsContext.refresh();
assert.equal(element('device-default-template-name').value,'RSSI');
rejectDefaultSave = true;
await element('add-device-default-template').onclick();
assert.equal(element('device-default-template').value,'8');
assert.equal(element('device-default-template-name').value,'RSSI');
assert.equal(element('device-default-feedback').textContent,'Duplicate service name');
rejectDefaultSave = false;
const priorDefaultSubmission = defaultSubmission;
element('device-default-template-name').value='   ';
await element('add-device-default-template').onclick();
assert.equal(defaultSubmission,priorDefaultSubmission);
assert.match(element('device-default-feedback').textContent,/Enter a service name/);
element('device-default-template-name').value='RSSI';
await element('add-device-default-template').onclick();
assert.equal(defaultSubmission.path, '/api/device-default-from-template');
assert.equal(defaultSubmission.body.template, '8');
assert.equal(defaultSubmission.body.name,'RSSI');
assert.equal(element('device-default-template').value,'');
assert.equal(element('device-default-template-name').value,'');
assert.equal(element('device-default-template-name').disabled,true);
element('device-default-source').value = '1';
await element('adopt-device-defaults').onclick();
assert.equal(element('app-confirmation').open, true);
assert.equal(defaultSubmission.path, '/api/device-default-from-template');
await element('confirm-app-action').onclick();
assert.equal(defaultSubmission.path, '/api/device-defaults-from-assignment');
assert.equal(defaultSubmission.body.assignment, '1');
assert.match(element('device-default-feedback').textContent, /Existing projects are unchanged/);
console.log('Inventory service defaults editor, library copy and project adoption preserve project isolation.');

// A fresh active issue attracts attention once; existing/reappearing issues do not.
const pulseClasses = new Set();
let pulseStarts = 0;
let pulseTimerId = 0;
let networkTimerId = 10000;
const pulseTimers = new Map();
const pulseData = {project:'Attention event',deployment:11,monitoring_paused:false,updated:now,devices:[],
    incidents:[{id:1,number:1,status:'critical',opened:now}],acknowledged_incidents:[]};
const pulseContext = vm.createContext({
    document:{...publicContext.document,documentElement:{offsetWidth:1200,classList:{
        add(...names){names.forEach(name => {pulseClasses.add(name);if(name === 'issue-attention')pulseStarts += 1;});},
        remove(...names){names.forEach(name => pulseClasses.delete(name));},
    }}},
    localStorage:publicContext.localStorage,
    fetch:async () => ({ok:true,json:async () => pulseData}),setInterval(){},
    setTimeout(callback, delay){
      if (delay === 2700) {
        pulseTimers.set(++pulseTimerId,callback);
        return pulseTimerId;
      }
      assert.ok([8000,60000].includes(delay));
      return ++networkTimerId;
    },
    clearTimeout(id){pulseTimers.delete(id);},
});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(pulseContext);
await pulseContext.refresh();
assert.equal(pulseStarts,0);
pulseData.incidents.push({id:2,number:2,status:'warning',opened:now});
await pulseContext.refresh();
assert.equal(pulseStarts,1);
assert.equal(pulseClasses.has('issue-attention'),true);
assert.equal(pulseClasses.has('issue-attention-warning'),true);
await pulseContext.refresh();
assert.equal(pulseStarts,1);
pulseData.incidents = [];
await pulseContext.refresh();
pulseData.incidents = [{id:2,number:2,status:'warning',opened:now}];
await pulseContext.refresh();
assert.equal(pulseStarts,1);
pulseTimers.get(pulseTimerId)();
assert.equal(pulseClasses.has('issue-attention'),false);
pulseData.monitoring_paused = true;
pulseData.incidents = [];
await pulseContext.refresh();
pulseData.monitoring_paused = false;
pulseData.incidents = [{id:2,number:2,status:'warning',opened:now}];
await pulseContext.refresh();
assert.equal(pulseStarts,1);
pulseData.incidents.push({id:3,number:3,status:'critical',opened:now});
await pulseContext.refresh();
assert.equal(pulseStarts,2);
assert.equal(pulseClasses.has('issue-attention-critical'),true);
assert.equal(pulseClasses.has('issue-attention-warning'),false);
pulseData.deployment = 12;
pulseData.incidents = [{id:4,number:1,status:'critical',opened:now}];
await pulseContext.refresh();
assert.equal(pulseStarts,2);
assert.equal(pulseClasses.has('issue-attention'),false);
assert.match(statusPage, /new-issue-attention 0\.9s ease-in-out 3/);
assert.match(statusPage, /prefers-reduced-motion: reduce/);
console.log('Status attention pulses trigger only for newly observed active issues and stop after three cycles.');

let notificationPauseRequest;
const beforeNotificationToggle = defaultsContext.fetch;
defaultsContext.fetch = async (path, options) => {
    if (path === '/api/notification-pause') {
        notificationPauseRequest = JSON.parse(options.body);
        defaultFixture.settings.notifications_paused = notificationPauseRequest.paused ? '1' : '0';
        return {ok:true,json:async () => ({ok:true})};
    }
    return beforeNotificationToggle(path, options);
};
await defaultsContext.refresh();
assert.equal(element('notifications-toggle').textContent, 'Pause notifications');
await element('notifications-toggle').onclick();
assert.equal(notificationPauseRequest.paused, true);
assert.equal(element('notifications-toggle').textContent, 'Resume notifications');
assert.equal(element('notifications-toggle').getAttribute('aria-pressed'), 'false');
assert.equal(element('monitoring-toggle').textContent, 'Pause all monitoring');
await element('notifications-toggle').onclick();
assert.equal(notificationPauseRequest.paused, false);
assert.equal(element('notifications-toggle').textContent, 'Pause notifications');
assert.equal(element('notifications-toggle').getAttribute('aria-pressed'), 'true');
console.log('Notification pause toggle operates independently from monitoring.');

defaultFixture.projects[0].logo_url = '/api/project-logo?project=1&v=reuse';
await defaultsContext.refresh();
assert.match(element('new-project-logo').innerHTML, /First event/);
assert.doesNotMatch(element('new-project-logo').innerHTML, /Second event/);
element('new-project-logo').value = '1';
element('new-project-logo').onchange();
assert.equal(element('new-project-logo-preview').hidden, false);
assert.equal(element('new-project-logo-preview').getAttribute('src'), '/api/project-logo?project=1&v=reuse');
await defaultsContext.refresh();
assert.equal(element('new-project-logo').value, '1');
assert.equal(element('new-project-logo-preview').hidden, false);
defaultFixture.projects[0].logo_url = null;
await defaultsContext.refresh();
assert.equal(element('new-project-logo').value, '');
assert.equal(element('new-project-logo-preview').hidden, true);
assert.match(html, /name="logo_project"/);
console.log('New-project logo choices preview existing uploads and survive refreshes.');

// Library import is reviewed in-app before any write, with errors kept in the dialog.
const libraryFile = {format:'network-monitor-service-library',version:3,
    services:[{name:'Imported RSSI',kind:'snmp',target:'.1.2.3',direction:'below',community:'TEST_EXPORT_SECRET'}]};
const libraryForm = element('library-import-form');
libraryForm.elements.namedItem('library').files = [{size:500,text:async () => JSON.stringify(libraryFile)}];
libraryForm.elements.namedItem('mode').value = 'merge';
let libraryImportRequest;
let rejectLibraryImport = false;
const previousLibraryFetch = defaultsContext.fetch;
defaultsContext.fetch = async (path, options) => {
    if (path === '/api/library-import') {
        libraryImportRequest = JSON.parse(options.body);
        return {ok:!rejectLibraryImport,json:async () => rejectLibraryImport
            ? {error:'Invalid service definition'} : {ok:true,added:1,skipped:0,replaced:1,total:1}};
    }
    return previousLibraryFetch(path, options);
};
await libraryForm.onsubmit({preventDefault(){},target:libraryForm});
assert.equal(element('library-import-dialog').open, true);
assert.equal(libraryImportRequest, undefined);
assert.match(element('library-import-summary').textContent, /Merge 1 services/);
element('cancel-library-import').onclick();
await element('confirm-library-import').onclick();
assert.equal(libraryImportRequest, undefined);
assert.equal(element('library-import-dialog').open, false);
libraryForm.elements.namedItem('mode').value = 'replace';
await libraryForm.onsubmit({preventDefault(){},target:libraryForm});
assert.match(element('library-import-summary').textContent, /Replace the current/);
rejectLibraryImport = true;
await element('confirm-library-import').onclick();
assert.equal(element('library-import-dialog').open, true);
assert.equal(element('library-import-error').textContent, 'Invalid service definition');
assert.equal(element('confirm-library-import').disabled, false);
rejectLibraryImport = false;
await element('confirm-library-import').onclick();
assert.equal(libraryImportRequest.mode, 'replace');
assert.equal(libraryImportRequest.library.services[0].community, 'TEST_EXPORT_SECRET');
assert.equal(element('library-import-dialog').open, false);
assert.match(element('library-feedback').textContent, /Replaced 1 library services with 1/);
libraryForm.elements.namedItem('library').files = [{size:10,text:async () => '{invalid-json'}];
await libraryForm.onsubmit({preventDefault(){},target:libraryForm});
assert.match(element('library-feedback').textContent, /valid service-library JSON/);
libraryForm.elements.namedItem('library').files = [{size:6*1024*1024,text:async () => '{}'}];
await libraryForm.onsubmit({preventDefault(){},target:libraryForm});
assert.match(element('library-feedback').textContent, /no larger than 5 MB/);
assert.match(html, /href="\/api\/library-export" download/);
console.log('Portable service library import supports reviewed Merge/Replace, cancellation and inline validation errors.');

// Previous-deployment selection is scoped to the project and requires explicit review.
const deploymentFixture = {...fixture,
    projects:[{id:1,name:'Project One'},{id:2,name:'Project Two'},{id:3,name:'No runs'}],
    runs:[{id:1,project:1,started:now-3600,description:'Original setup'},
          {id:2,project:1,started:now,description:'Second setup'},
          {id:3,project:2,started:now,description:'Other project setup'}],
    settings:{...fixture.settings,active_run:'2',paused_run:'0',notifications_paused:'0'},
    incident_lists:{active:[],acknowledged:[],resolved:[],suppressed:[]},
};
const resumeRequests = [];
let rejectResume = false;
const resumeContext = vm.createContext({document:context.document,localStorage:context.localStorage,
    FormData:context.FormData,setInterval(){},confirm:() => true,
    fetch:async (path, options) => {
        if (path === '/api/resume-deployment') {
            const body = JSON.parse(options.body);
            resumeRequests.push(body);
            if (rejectResume) return {ok:false,json:async () => ({error:'Cannot resume deployment'})};
            deploymentFixture.settings.active_run = '0';
            deploymentFixture.settings.paused_run = String(body.run);
            deploymentFixture.settings.notifications_paused = '1';
            return {ok:true,json:async () => ({ok:true})};
        }
        return {ok:true,json:async () => path === '/api/me'
            ? {id:1,username:'admin',role:'admin',csrf:'test',must_change_password:0}
            : path === '/api/users' ? []
            : path === '/api/telegram' || path === '/api/whatsapp' ? {configuration:{},outbox:[]}
            : deploymentFixture};
    },
});
new vm.Script(script).runInContext(resumeContext);
await resumeContext.initializeSession();
assert.match(element('previous-deployment').innerHTML, /Original setup/);
assert.doesNotMatch(element('previous-deployment').innerHTML, /Other project setup/);
element('previous-deployment').value = '2';
element('previous-deployment').onchange();
assert.equal(element('resume-selected-deployment').disabled, true);
element('previous-deployment').value = '1';
element('previous-deployment').onchange();
assert.equal(element('resume-selected-deployment').disabled, false);
await resumeContext.refresh();
assert.equal(element('previous-deployment').value, '1');
element('resume-selected-deployment').onclick();
assert.equal(element('resume-deployment-dialog').open, true);
assert.match(element('resume-deployment-context').textContent, /Original setup/);
assert.match(element('resume-deployment-current').textContent, /#2/);
assert.equal(resumeRequests.length, 0);
element('cancel-resume-deployment').onclick();
await element('confirm-resume-deployment').onclick();
assert.equal(resumeRequests.length, 0);
element('resume-selected-deployment').onclick();
rejectResume = true;
await element('confirm-resume-deployment').onclick();
assert.equal(element('resume-deployment-dialog').open, true);
assert.equal(element('resume-deployment-feedback').textContent, 'Cannot resume deployment');
assert.equal(resumeRequests[0].run, 1);
assert.equal(resumeRequests[0].project, 1);
assert.equal(resumeRequests[0].expected_active_run, 2);
deploymentFixture.settings.active_run = '3';
await resumeContext.refresh();
await element('confirm-resume-deployment').onclick();
assert.equal(resumeRequests.length, 1);
assert.match(element('resume-deployment-feedback').textContent, /Active deployment changed/);
element('cancel-resume-deployment').onclick();
deploymentFixture.settings.active_run = '2';
await resumeContext.refresh();
element('resume-selected-deployment').onclick();
rejectResume = false;
await element('confirm-resume-deployment').onclick();
assert.equal(element('resume-deployment-dialog').open, false);
assert.equal(element('monitoring-toggle').textContent, 'Resume all monitoring');
assert.equal(element('monitoring-toggle').disabled, false);
assert.equal(element('notifications-toggle').textContent, 'Resume notifications');
assert.match(element('deployment-details').textContent, /Original setup/);
element('project').value = '2';
element('project').onchange();
await resumeContext.refresh();
assert.equal(element('previous-deployment').value, '');
assert.match(element('previous-deployment').innerHTML, /Other project setup/);
assert.doesNotMatch(element('previous-deployment').innerHTML, /Original setup/);
element('project').value = '3';
element('project').onchange();
await resumeContext.refresh();
assert.match(element('previous-deployment').innerHTML, /No previous deployments/);
assert.equal(element('resume-selected-deployment').disabled, true);
console.log('Previous deployments can be reviewed and resumed with project filtering, cancellation and stale-state protection.');

// Model the user explicitly resuming monitoring before testing active-run deletion protection.
deploymentFixture.settings.active_run = '1';
deploymentFixture.settings.paused_run = '0';
const deleteRequests = [];
let rejectDeploymentDelete = false;
const previousDeleteFetch = resumeContext.fetch;
resumeContext.fetch = async (path, options) => {
    if (path === '/api/delete-deployment') {
        const body = JSON.parse(options.body);
        deleteRequests.push(body);
        if (rejectDeploymentDelete) return {ok:false,json:async () => ({error:'Cannot delete deployment'})};
        deploymentFixture.runs = deploymentFixture.runs.filter(row => row.id !== body.run);
        return {ok:true,json:async () => ({ok:true})};
    }
    return previousDeleteFetch(path, options);
};
element('project').value = '1';
element('project').onchange();
await resumeContext.refresh();
element('previous-deployment').value = '1';
element('previous-deployment').onchange();
assert.equal(element('delete-selected-deployment').disabled, true);
element('previous-deployment').value = '2';
element('previous-deployment').onchange();
assert.equal(element('delete-selected-deployment').disabled, false);
element('delete-selected-deployment').onclick();
assert.equal(element('delete-deployment-dialog').open, true);
assert.match(element('delete-deployment-context').textContent, /Second setup/);
assert.equal(deleteRequests.length,0);
element('cancel-delete-deployment').onclick();
await element('confirm-delete-deployment').onclick();
assert.equal(deleteRequests.length,0);
element('delete-selected-deployment').onclick();
rejectDeploymentDelete = true;
await element('confirm-delete-deployment').onclick();
assert.equal(element('delete-deployment-dialog').open,true);
assert.equal(element('delete-deployment-feedback').textContent,'Cannot delete deployment');
assert.equal(deleteRequests[0].run,2);
assert.equal(deleteRequests[0].expected_active_run,1);
deploymentFixture.settings.active_run = '3';
await resumeContext.refresh();
await element('confirm-delete-deployment').onclick();
assert.equal(deleteRequests.length,1);
assert.match(element('delete-deployment-feedback').textContent,/Active deployment changed/);
element('cancel-delete-deployment').onclick();
deploymentFixture.settings.active_run = '1';
await resumeContext.refresh();
element('delete-selected-deployment').onclick();
rejectDeploymentDelete = false;
await element('confirm-delete-deployment').onclick();
assert.equal(element('delete-deployment-dialog').open,false);
assert.equal(element('previous-deployment').value,'');
assert.equal(element('delete-selected-deployment').disabled,true);
assert.doesNotMatch(element('previous-deployment').innerHTML,/Second setup/);
assert.match(html,/permanently deletes the deployment and all its readings, issues, acknowledgement records/);
console.log('Deployment deletion requires explicit review, protects active runs and removes deleted selector entries.');

// Mixed arrivals use critical red; global notification pause never gates visual alerts.
pulseData.notifications_paused = true;
pulseData.incidents.push({id:5,number:2,status:'warning',opened:now});
await pulseContext.refresh();
assert.equal(pulseClasses.has('issue-attention-warning'),true);
pulseData.incidents.push({id:6,number:3,status:'warning',opened:now},{id:7,number:4,status:'unreachable',opened:now});
await pulseContext.refresh();
assert.equal(pulseClasses.has('issue-attention-critical'),true);
assert.equal(pulseClasses.has('issue-attention-warning'),false);
const criticalPulseStarts = pulseStarts;
pulseData.incidents.push({id:8,number:5,status:'warning',opened:now});
await pulseContext.refresh();
assert.equal(pulseStarts,criticalPulseStarts);
assert.equal(pulseClasses.has('issue-attention-critical'),true);
pulseTimers.get(pulseTimerId)();
assert.equal(pulseClasses.has('issue-attention'),false);
assert.equal(pulseClasses.has('issue-attention-critical'),false);
console.log('Status attention uses yellow for warnings and red for critical/unreachable issues, independent of notifications.');

// Opening evidence stays explicit, labelled and escaped on both dashboards.
const evidence = {id:1,number:1,status:'critical',opened:now,trigger_timestamp:now,
  trigger_value:-78,trigger_display:'-78',trigger_units:'dBm'};
assert.match(context.renderIncidents([evidence]), /class="issue-value">-78 dBm<\/span>/);
assert.equal(publicContext.issueCause(evidence), '-78 dBm');
assert.match(context.renderIncidents([{...evidence,trigger_value:2,trigger_display:'<Port Down>',trigger_units:''}]), /&lt;Port Down&gt;/);
assert.equal(publicContext.issueCause({...evidence,trigger_value:null,trigger_display:null,trigger_error:'TimeoutError'}), 'No usable reading (TimeoutError)');
assert.match(context.renderIncidents([{id:1,status:'critical',opened:now}]), /Opening value unavailable/);
console.log('Immutable issue causes show metric units, state labels and safe missing-reading details on both dashboards.');

assert.doesNotMatch(context.renderIncidents([evidence]), /Triggered by/i);
assert.equal(publicContext.issueCause({...evidence,trigger_value:null,trigger_display:'Host unreachable',trigger_error:'CalledProcessError'}), 'Host unreachable');

// The sample selector posts its type and remains reusable after a send.
const sampleRequests = [];
const sampleOriginalFetch = resumeContext.fetch;
resumeContext.fetch = async (path, options) => {
  if (path === '/api/telegram-test') sampleRequests.push(JSON.parse(options.body));
  return sampleOriginalFetch(path, options);
};
element('telegram-sample-type').value = 'flapping';
await element('telegram-test').onclick();
assert.equal(sampleRequests[0].sample_type, 'flapping');
assert.equal(element('telegram-test').disabled, false);
assert.match(element('telegram-feedback').textContent, /Sample notification queued/);
assert.equal(element('telegram-sample-type').value, 'flapping');
resumeContext.fetch = sampleOriginalFetch;
console.log('Telegram sample selector queues the selected example without resetting the selection.');

// Public status must let every signed-in role log out even without acknowledgement CSRF.
const signOutData = {project:'Logout test',devices:[],incidents:[],acknowledged_incidents:[],updated:now,
  acknowledge_enabled:false,can_acknowledge:false,viewer:null};
const signOutRequests = [];
let signOutDenied = false;
let signOutExpired = false;
const signOutContext = vm.createContext({document:publicContext.document,localStorage:publicContext.localStorage,
  setInterval(){},fetch:async (path, options) => {
    if (path === '/api/me') {
      if (signOutExpired) {
        signOutData.viewer = null;
        return {ok:false,status:401,json:async () => ({error:'Login required'})};
      }
      return {ok:true,status:200,json:async () => ({...signOutData.viewer,csrf:'logout-session-token'})};
    }
    if (path === '/api/logout') {
      signOutRequests.push(options);
      if (signOutDenied) return {ok:false,status:403,json:async () => ({error:'Sign out rejected'})};
      signOutData.viewer = null;
      return {ok:true,status:200,json:async () => ({ok:true})};
    }
    return {ok:true,status:200,json:async () => signOutData};
  }});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(signOutContext);
await signOutContext.refresh();
assert.equal(publicNodes.get('status-logout').hidden,true);
for (const role of ['admin','operator','viewer']) {
  for (const mustChangePassword of [false,true]) {
    signOutData.viewer = {username:role,role,must_change_password:mustChangePassword};
    await signOutContext.refresh();
    assert.equal(publicNodes.get('status-logout').hidden,false);
    await publicNodes.get('status-logout').onclick();
    const posted = signOutRequests.at(-1);
    assert.equal(posted.headers['X-CSRF-Token'],'logout-session-token');
    assert.equal(posted.method,'POST');
    assert.equal(publicNodes.get('status-logout').hidden,true);
    assert.equal(publicNodes.get('status-session').textContent,'Not signed in');
    assert.equal(publicNodes.get('status-session-link').textContent,'Sign in');
    assert.equal(publicNodes.get('status-logout').disabled,false);
  }
}
signOutData.viewer = {username:'viewer',role:'viewer'};
signOutDenied = true;
await signOutContext.refresh();
await publicNodes.get('status-logout').onclick();
assert.equal(publicNodes.get('status-logout').hidden,false);
assert.equal(publicNodes.get('status-logout').disabled,false);
assert.equal(publicNodes.get('status-ack-feedback').textContent,'Sign out rejected');
const callsBeforeExpiry = signOutRequests.length;
signOutExpired = true;
await publicNodes.get('status-logout').onclick();
assert.equal(signOutRequests.length,callsBeforeExpiry);
assert.equal(publicNodes.get('status-logout').hidden,true);
console.log('Status sign-out works for all roles and temporary passwords, uses session CSRF, and handles rejection/expiry.');

// Host flap editing must always identify and populate the host just selected.
const firstFlapHost = fixture.services.find(service => service.kind === 'ping');
Object.assign(firstFlapHost, {flap_enabled:1,flap_changes:4,flap_window:5,flap_stable:5});
const firstFlapAssignment = fixture.assignments.find(row => row.id === firstFlapHost.assignment);
const firstFlapDevice = fixture.devices.find(row => row.id === firstFlapAssignment.device);
fixture.devices.push({id:987,name:'<Host B>',address:'10.1.1.2'});
fixture.assignments.push({id:988,project:1,device:987,alias:'Second & alias',monitoring:1,visible:1});
fixture.services.push({id:989,assignment:988,kind:'ping',enabled:1,flap_enabled:0,flap_changes:7,flap_window:8,flap_stable:9});
await context.refresh();
context.openHostStabilityEditor(firstFlapHost.id);
assert.equal(element('host-stability-host').textContent, `${firstFlapDevice.name} - ${firstFlapAssignment.alias}`);
assert.equal(element('host-stability-form').elements.namedItem('service').value,firstFlapHost.id);
assert.equal(element('host-stability-form').elements.namedItem('flap_changes').value,4);
context.openHostStabilityEditor(989);
assert.equal(element('host-stability-host').textContent,'<Host B> - Second & alias');
assert.equal(element('host-stability-form').elements.namedItem('service').value,989);
assert.equal(element('host-stability-form').elements.namedItem('flap_changes').value,7);
assert.equal(element('host-stability-form').elements.namedItem('flap_enabled').checked,false);
context.openHostStabilityEditor(firstFlapHost.id);
assert.equal(element('host-stability-form').elements.namedItem('flap_changes').value,4);
assert.equal(element('host-stability-form').elements.namedItem('flap_enabled').checked,true);
assert.throws(() => context.openHostStabilityEditor(-999), /Host no longer exists/);
fixture.assignments.find(row => row.id === 988).removed = 1;
await context.refresh();
assert.throws(() => context.openHostStabilityEditor(989), /Host no longer exists/);
console.log('Host flap dialog identifies the correct host, safely displays aliases, refreshes policy fields and rejects removed targets.');

// Protocol changes disable irrelevant inputs without clearing draft values.
const protocolForm = element('service-edit-form');
protocolForm.elements.namedItem('community').value = 'unsaved-community';
protocolForm.elements.namedItem('unit').value = '17';
protocolForm.elements.namedItem('modbus_function').value = '4';
for (const [protocol, communityDisabled, unitDisabled] of [
  ['snmp',false,true],['modbus',true,false],['tcp',true,true],['snmp',false,true],
]) {
  protocolForm.elements.namedItem('kind').value = protocol;
  context.updateProtocolFields(protocolForm);
  assert.equal(protocolForm.elements.namedItem('community').disabled,communityDisabled);
  assert.equal(protocolForm.elements.namedItem('unit').disabled,unitDisabled);
  assert.equal(protocolForm.elements.namedItem('community').value,'unsaved-community');
  assert.equal(protocolForm.elements.namedItem('unit').value,'17');
  assert.equal(protocolForm.elements.namedItem('modbus_function').disabled,protocol !== 'modbus');
  assert.equal(protocolForm.elements.namedItem('modbus_function').value,'4');
  assert.equal(element('snmp-community-field').hidden,protocol !== 'snmp');
  assert.equal(element('modbus-register-field').hidden,protocol !== 'modbus');
}
for (const [kind, mode] of [['snmp','service-edit'],['modbus','template-create'],['tcp','device-default-create']]) {
  context.openConfigurationEditor({...stateService,kind,modbus_function:4},mode,null,'Protocol test','Sample configuration');
  assert.equal(protocolForm.elements.namedItem('community').disabled,kind !== 'snmp');
  assert.equal(protocolForm.elements.namedItem('unit').disabled,kind !== 'modbus');
  assert.equal(protocolForm.elements.namedItem('modbus_function').value,'4');
}
console.log('Service protocol fields initialise correctly and retain drafts while switching SNMP, Modbus and TCP.');

// Assignment choices are project-scoped; paused/hidden still means assigned.
fixture.projects.push({id:876,name:'Other assignment project'});
fixture.devices.push({id:877,name:'Elsewhere',address:'10.9.1.1'},
  {id:878,name:'Paused assigned',address:'10.9.1.2'}, {id:879,name:'Removed available',address:'10.9.1.3'});
fixture.assignments.push({id:877,project:876,device:877,alias:'Other project',monitoring:1,visible:1},
  {id:878,project:1,device:878,alias:'Paused',monitoring:0,visible:0},
  {id:879,project:1,device:879,alias:'Removed',removed:1,monitoring:0,visible:0});
vm.runInContext("selectedProject = '1'", context);
await context.refresh();
assert.match(element('device').innerHTML, /value="877"/);
assert.doesNotMatch(element('device').innerHTML, /value="878"/);
assert.match(element('device').innerHTML, /value="879"/);
element('device').value = '879';
await context.refresh();
assert.equal(element('device').value,'879');
fixture.assignments.find(row => row.id === 879).removed = 0;
await context.refresh();
assert.doesNotMatch(element('device').innerHTML, /value="879"/);
assert.equal(element('device').value,'');
vm.runInContext("selectedProject = '876'", context);
await context.refresh();
assert.doesNotMatch(element('device').innerHTML, /value="877"/);
assert.match(element('device').innerHTML, /value="878"/);
console.log('Assign-equipment choices exclude current project assignments and preserve eligible selections across refreshes.');

// Shared Actions menus float independently of rows and remain globally exclusive.
const menuEvents = new Map();
let actionMenus = [];
function actionMenu(key, anchor) {
  const menu = {open:false,dataset:{menuKey:key}};
  const summary = {parentElement:menu,focused:false,focus(){this.focused=true;},
    getBoundingClientRect(){return anchor;},
    closest(selector){return selector === '.action-menu' ? menu : selector === 'summary' ? this : null;}};
  const popup = {style:{},getBoundingClientRect(){return {width:200,height:180};}};
  menu.querySelector = selector => selector === 'summary' ? summary : popup;
  return {menu,summary,popup};
}
const firstAction = actionMenu('hosts:2',{right:400,top:70,bottom:100});
const catalogueAction = actionMenu('catalogue:2',{right:980,top:650,bottom:680});
actionMenus = [firstAction.menu,catalogueAction.menu];
const menuContext = vm.createContext({document:{...context.document,
  documentElement:{clientWidth:1000,clientHeight:700},
  addEventListener(type,handler){menuEvents.set(type,handler);},
  querySelectorAll(selector){
    if (selector === '.action-menu') return actionMenus;
    if (selector === '.action-menu[open]') return actionMenus.filter(menu => menu.open);
    return [];
  }},localStorage:context.localStorage,setInterval(){},
  fetch:async path => ({ok:true,json:async () => path === '/api/me' ? {id:1,username:'admin',role:'admin',csrf:'test'}
    : path === '/api/users' ? [] : ['/api/telegram','/api/whatsapp'].includes(path) ? {configuration:{},outbox:[]} : fixture})});
new vm.Script(script).runInContext(menuContext);
await menuContext.initializeSession();
function clickAction(target) {
  let prevented = false;
  menuEvents.get('click')({target,preventDefault(){prevented=true;}});
  return prevented;
}
assert.equal(clickAction(firstAction.summary),true);
assert.equal(firstAction.menu.open,true);
assert.equal(catalogueAction.menu.open,false);
assert.equal(firstAction.popup.style.left,'200px');
assert.equal(firstAction.popup.style.top,'106px');
clickAction(catalogueAction.summary);
assert.equal(firstAction.menu.open,false);
assert.equal(catalogueAction.menu.open,true);
assert.equal(catalogueAction.popup.style.top,'464px');
assert.equal(catalogueAction.popup.style.left,'780px');
// Clicking menu whitespace or scrolling its own content keeps it usable.
const insideMenu = {closest:selector => selector === '.action-menu' ? catalogueAction.menu : null};
clickAction(insideMenu);
assert.equal(catalogueAction.menu.open,true);
menuEvents.get('scroll')({target:{closest:selector => selector === '.menu-buttons' ? catalogueAction.popup : null}});
assert.equal(catalogueAction.menu.open,true);
// Clicking an action or anywhere else closes it.
clickAction({closest:selector => selector === '.action-menu' ? catalogueAction.menu : selector === 'button' ? {} : null});
assert.equal(catalogueAction.menu.open,false);
clickAction(firstAction.summary);
clickAction({closest:() => null});
assert.equal(firstAction.menu.open,false);
// A poll may replace the selected occurrence, but never open a second occurrence.
clickAction(firstAction.summary);
const replacementAction = actionMenu('hosts:2',{right:400,top:70,bottom:100});
actionMenus = [replacementAction.menu,catalogueAction.menu];
menuContext.restoreActionMenu();
assert.equal(replacementAction.menu.open,true);
assert.equal(catalogueAction.menu.open,false);
let escapePrevented = false;
menuEvents.get('keydown')({key:'Escape',preventDefault(){escapePrevented=true;}});
assert.equal(replacementAction.menu.open,false);
assert.equal(replacementAction.summary.focused,true);
assert.equal(escapePrevented,true);
clickAction(replacementAction.summary);
menuEvents.get('scroll')({target:{closest:() => null}});
assert.equal(replacementAction.menu.open,false);
clickAction(replacementAction.summary);
actionMenus = [];
menuContext.restoreActionMenu();
actionMenus = [replacementAction.menu];
menuContext.restoreActionMenu();
assert.equal(replacementAction.menu.open,false);
console.log('Actions menus stay exclusive, float within the viewport, survive polling once, and close on outside/action clicks, Escape and page scroll.');

// Removing a host service uses reviewable app UI, not a native confirmation.
const removalFixture = {...fixture,projects:[{id:1,name:'Removal project'}],
  devices:[{id:99,name:'Switch <A>',address:'10.0.0.1'}],
  assignments:[{id:101,project:1,device:99,alias:'Stage & alias',visible:1,monitoring:1}],
  services:[{...stateService,id:202,assignment:101,name:'Port <status>',enabled:1}],
  latest:[],runs:[{id:1,project:1}],settings:{active_run:'1',retention_days:'30'},
  incident_lists:{active:[],acknowledged:[],suppressed:[],resolved:[]}};
const removalRequests = [];
let rejectServiceRemoval = false;
const removalContext = vm.createContext({document:context.document,localStorage:context.localStorage,
  setInterval(){},confirm(){throw new Error('Native confirmation must not be used');},
  fetch:async (path,options) => {
    if (path === '/api/remove-service') {
      removalRequests.push({body:JSON.parse(options.body),headers:options.headers});
      if (rejectServiceRemoval) return {ok:false,status:400,json:async () => ({error:'Removal rejected'})};
      removalFixture.services[0].enabled = 0;
      return {ok:true,status:200,json:async () => ({ok:true})};
    }
    return {ok:true,status:200,json:async () => path === '/api/me' ? {id:1,username:'admin',role:'admin',csrf:'remove-token'}
      : path === '/api/users' ? [] : ['/api/telegram','/api/whatsapp'].includes(path) ? {configuration:{},outbox:[]} : removalFixture};
  }});
new vm.Script(script).runInContext(removalContext);
await removalContext.initializeSession();
removalContext.openServiceRemoval(202);
assert.equal(element('remove-service-dialog').open,true);
assert.equal(element('remove-service-context').textContent,'Switch <A> - Stage & alias / Port <status>');
assert.equal(removalRequests.length,0);
element('cancel-remove-service').onclick();
await element('confirm-remove-service').onclick();
assert.equal(removalRequests.length,0);
removalContext.openServiceRemoval(202);
element('remove-service-dialog').onclose();
element('remove-service-dialog').close();
await element('confirm-remove-service').onclick();
assert.equal(removalRequests.length,0);
removalContext.openServiceRemoval(202);
rejectServiceRemoval = true;
await element('confirm-remove-service').onclick();
assert.equal(element('remove-service-dialog').open,true);
assert.equal(element('remove-service-feedback').textContent,'Removal rejected');
assert.equal(element('confirm-remove-service').disabled,false);
assert.equal(element('cancel-remove-service').disabled,false);
assert.equal(removalRequests[0].body.id,202);
assert.equal(removalRequests[0].headers['X-CSRF-Token'],'remove-token');
element('cancel-remove-service').onclick();
removalContext.openServiceRemoval(202);
removalFixture.services[0].enabled = 0;
await removalContext.refresh();
await element('confirm-remove-service').onclick();
assert.equal(removalRequests.length,1);
assert.match(element('remove-service-feedback').textContent,/no longer available/);
element('cancel-remove-service').onclick();
removalFixture.services[0].enabled = 1;
await removalContext.refresh();
removalContext.openServiceRemoval(202);
rejectServiceRemoval = false;
const removalSave = element('confirm-remove-service').onclick();
await element('confirm-remove-service').onclick();
await removalSave;
assert.equal(removalRequests.length,2);
assert.equal(element('remove-service-dialog').open,false);
assert.equal(removalFixture.services[0].enabled,0);
assert.match(element('message').textContent,/Service removed/);
console.log('In-app service removal supports safe cancellation, inline errors, fixed targets and a single confirmed request.');

// Every remaining destructive admin action must be reviewed before any request.
const confirmationFixture = {...removalFixture,
  devices:[{id:99,name:'Device <A>',address:'10.0.0.1'}],
  service_templates:[{id:301,name:'Library <RSSI>',kind:'snmp'}],
  device_service_defaults:[{id:401,device:99,name:'Default & RSSI'}]};
const administrativeRequests = [];
const administrativeRedirects = [];
let rejectAdministrativeAction = false;
const administrativeContext = vm.createContext({document:context.document,localStorage:context.localStorage,
  setInterval(){},confirm(){throw new Error('Native confirmation is forbidden');},
  location:{assign(path){administrativeRedirects.push(path);}},
  FormData:class {constructor(form){this.form=form;}get(){return this.form.backupFile;}},
  fetch:async (path,options) => {
    if (options?.method === 'POST') {
      administrativeRequests.push({path,body:path === '/api/restore' ? options.body : JSON.parse(options.body),headers:options.headers});
      return {ok:!rejectAdministrativeAction,status:rejectAdministrativeAction ? 400 : 200,
        json:async () => rejectAdministrativeAction ? {error:'Operation rejected'} : {ok:true}};
    }
    return {ok:true,status:200,json:async () => path === '/api/me' ? {id:1,username:'admin',role:'admin',csrf:'admin-action-token'}
      : path === '/api/users' ? [{id:1,username:'admin',role:'admin'},{id:2,username:'reader',full_name:'Reader <B>',role:'viewer'}]
      : ['/api/telegram','/api/whatsapp'].includes(path) ? {configuration:{},outbox:[]} : confirmationFixture};
  }});
new vm.Script(script).runInContext(administrativeContext);
await administrativeContext.initializeSession();
for (const [action,selection,path,expectedBody] of [
  ['delete-device',{device:99},'/api/delete-device',{device:99}],
  ['remove-assignment',{assignment:101},'/api/assignment-remove',{assignment:101}],
  ['delete-template',{template:301},'/api/template-delete',{template:301}],
  ['delete-default',{device:99,default_service:401},'/api/device-default-delete',{device:99,default_service:401}],
  ['adopt-defaults',{device:99,assignment:101},'/api/device-defaults-from-assignment',{device:99,assignment:101}],
  ['delete-user',{user:2},'/api/user-delete',{user:2}],
]) {
  const before = administrativeRequests.length;
  administrativeContext.openAdministrativeConfirmation(action,selection);
  assert.equal(element('app-confirmation').open,true);
  assert.equal(administrativeRequests.length,before);
  assert.ok(element('app-confirmation-context').textContent.length);
  assert.ok(element('app-confirmation-description').textContent.length);
  element('cancel-app-action').onclick();
  await element('confirm-app-action').onclick();
  assert.equal(administrativeRequests.length,before);
  administrativeContext.openAdministrativeConfirmation(action,selection);
  element('app-confirmation').close();
  element('app-confirmation').onclose();
  await element('confirm-app-action').onclick();
  assert.equal(administrativeRequests.length,before);
  administrativeContext.openAdministrativeConfirmation(action,selection);
  rejectAdministrativeAction = true;
  await element('confirm-app-action').onclick();
  assert.equal(element('app-confirmation').open,true);
  assert.equal(element('app-confirmation-feedback').textContent,'Operation rejected');
  assert.equal(element('confirm-app-action').disabled,false);
  element('cancel-app-action').onclick();
  rejectAdministrativeAction = false;
  const mutableSelection = {...selection};
  administrativeContext.openAdministrativeConfirmation(action,mutableSelection);
  // Changing external selection data after opening cannot change the approved target.
  for (const key of Object.keys(mutableSelection)) mutableSelection[key] = 9999;
  const save = element('confirm-app-action').onclick();
  let preventedCancel = false;
  element('app-confirmation').oncancel({preventDefault(){preventedCancel=true;}});
  assert.equal(preventedCancel,true);
  await element('confirm-app-action').onclick();
  await save;
  assert.equal(administrativeRequests.length,before+2);
  const request = administrativeRequests.at(-1);
  assert.equal(request.path,path);
  assert.deepEqual(request.body,expectedBody);
  assert.equal(request.headers['X-CSRF-Token'],'admin-action-token');
  assert.equal(element('app-confirmation').open,false);
  assert.equal(element('cancel-app-action').disabled,false);
}
// Backup selection is captured before review; Cancel and errors never upload another file.
const approvedBackup = {name:'backup <A>.sqlite3',size:123};
const replacementBackup = {name:'backup B.sqlite3',size:456};
const restoreForm = element('restore');
restoreForm.backupFile = approvedBackup;
element('restore').onsubmit({preventDefault(){},target:restoreForm});
assert.equal(element('app-confirmation-context').textContent,approvedBackup.name);
const beforeRestore = administrativeRequests.length;
element('cancel-app-action').onclick();
await element('confirm-app-action').onclick();
assert.equal(administrativeRequests.length,beforeRestore);
element('restore').onsubmit({preventDefault(){},target:restoreForm});
rejectAdministrativeAction = true;
await element('confirm-app-action').onclick();
assert.equal(element('app-confirmation').open,true);
assert.match(element('app-confirmation-feedback').textContent,/Restore rejected/);
rejectAdministrativeAction = false;
element('cancel-app-action').onclick();
element('restore').onsubmit({preventDefault(){},target:restoreForm});
restoreForm.backupFile = replacementBackup;
await element('confirm-app-action').onclick();
assert.equal(administrativeRequests.at(-1).body,approvedBackup);
assert.equal(administrativeRequests.at(-1).headers['Content-Type'],'application/octet-stream');
assert.equal(administrativeRequests.at(-1).headers['X-CSRF-Token'],'admin-action-token');
assert.deepEqual(administrativeRedirects,['/login']);
assert.equal(element('app-confirmation').open,false);
assert.doesNotMatch(html,/\b(?:confirm|alert|prompt)\s*\(/);
console.log('All seven admin confirmations support cancellation, target capture, inline rejection, duplicate protection and safe backup selection.');

// Unacknowledgement is confirmed, revision-bound and available to Operators.
const undoIssue = {id:501,number:7,service:202,run:1,status:'critical',opened:now-300,
  acknowledged:now-100,ack_revision:1,acknowledged_by_full_name:'Earlier Operator',closed:null};
const undoFixture = {...removalFixture,services:[{...stateService,id:202,assignment:101,enabled:1}],
  incidents:[undoIssue],incident_lists:{active:[],acknowledged:[undoIssue],suppressed:[],resolved:[]}};
const undoRequests = [];
let rejectUndo = false;
const undoContext = vm.createContext({document:context.document,localStorage:context.localStorage,setInterval(){},
  fetch:async (path,options) => {
    if (path === '/api/unack') {
      undoRequests.push({body:JSON.parse(options.body),headers:options.headers});
      if (rejectUndo) return {ok:false,status:400,json:async () => ({error:'Acknowledgement rejected'})};
      undoIssue.acknowledged = null;
      undoIssue.ack_revision += 1;
      undoFixture.incident_lists.acknowledged = [];
      undoFixture.incident_lists[undoIssue.closed ? 'resolved' : 'active'] = [undoIssue];
      return {ok:true,status:200,json:async () => ({ok:true})};
    }
    return {ok:true,status:200,json:async () => path === '/api/me'
      ? {id:3,username:'operator',role:'operator',csrf:'undo-token'} : undoFixture};
  }});
new vm.Script(script).runInContext(undoContext);
await undoContext.initializeSession();
assert.match(element('acknowledged-incidents').innerHTML,/data-unack="501"/);
undoContext.openUnacknowledgement(501);
assert.equal(element('unacknowledgement-dialog').open,true);
assert.match(element('unacknowledgement-context').textContent,/Issue #7/);
assert.equal(undoRequests.length,0);
element('cancel-unacknowledgement').onclick();
await element('confirm-unacknowledgement').onclick();
assert.equal(undoRequests.length,0);
undoContext.openUnacknowledgement(501);
element('unacknowledgement-dialog').onclose();
element('unacknowledgement-dialog').close();
await element('confirm-unacknowledgement').onclick();
assert.equal(undoRequests.length,0);
undoContext.openUnacknowledgement(501);
rejectUndo = true;
await element('confirm-unacknowledgement').onclick();
assert.equal(element('unacknowledgement-dialog').open,true);
assert.equal(element('unacknowledgement-feedback').textContent,'Acknowledgement rejected');
assert.equal(element('confirm-unacknowledgement').disabled,false);
element('cancel-unacknowledgement').onclick();
rejectUndo = false;
undoContext.openUnacknowledgement(501);
undoIssue.ack_revision = 2;
await undoContext.refresh();
await element('confirm-unacknowledgement').onclick();
assert.equal(undoRequests.length,1);
assert.match(element('unacknowledgement-feedback').textContent,/changed/);
element('cancel-unacknowledgement').onclick();
undoContext.openUnacknowledgement(501);
const toastCountBeforeUndo = vm.runInContext('saveToasts.size',undoContext);
const undoSave = element('confirm-unacknowledgement').onclick();
await element('confirm-unacknowledgement').onclick();
await undoSave;
assert.equal(undoRequests.length,2);
assert.equal(vm.runInContext('saveToasts.size',undoContext),toastCountBeforeUndo);
assert.match(element('incident-feedback').textContent,/Acknowledgement removed/);
assert.equal(undoRequests.at(-1).body.expected_revision,2);
assert.equal(undoRequests.at(-1).headers['X-CSRF-Token'],'undo-token');
assert.equal(element('unacknowledgement-dialog').open,false);
assert.match(element('incidents').innerHTML,/Issue #7/);
undoIssue.acknowledged = now;
undoIssue.ack_revision = 4;
undoFixture.incident_lists.active = [];
undoFixture.incident_lists.acknowledged = [undoIssue];
await undoContext.refresh();
vm.runInContext("currentUser.role='viewer'",undoContext);
assert.doesNotMatch(undoContext.renderIncidents([undoIssue]),/data-unack/);
assert.throws(() => undoContext.openUnacknowledgement(501),/Admin or Operator/);
vm.runInContext("currentUser.role='operator'",undoContext);
undoContext.openUnacknowledgement(501);
undoIssue.closed = now;
await element('confirm-unacknowledgement').onclick();
assert.match(element('unacknowledgement-feedback').textContent,/recovered/);
assert.equal(undoRequests.length,2);
element('cancel-unacknowledgement').onclick();
console.log('Main Unacknowledge supports role checks, Cancel/Escape, inline errors, stale review and recovered routing.');

// Public Unacknowledge follows project opt-in and rechecks it at confirmation.
const publicUndoIssue = {id:601,number:8,device:'Switch',alias:'Stage',service:'RSSI',status:'critical',
  opened:now-300,acknowledged:now-100,ack_revision:1,closed:null};
const publicUndoData = {project:'Undo event',devices:[],incidents:[],acknowledged_incidents:[publicUndoIssue],updated:now,
  acknowledge_enabled:false,can_acknowledge:false,viewer:{username:'operator',role:'operator'}};
const publicUndoRequests = [];
let publicUndoRejected = false;
const publicUndoContext = vm.createContext({document:publicContext.document,localStorage:publicContext.localStorage,setInterval(){},
  fetch:async (path,options) => {
    if (path === '/api/status-unack') {
      publicUndoRequests.push({body:JSON.parse(options.body),headers:options.headers});
      if (publicUndoRejected) return {ok:false,status:400,json:async () => ({error:'Public undo rejected'})};
      publicUndoData.acknowledged_incidents = [];
      if (!publicUndoIssue.closed) publicUndoData.incidents = [publicUndoIssue];
      return {ok:true,status:200,json:async () => ({ok:true})};
    }
    return {ok:true,status:200,json:async () => publicUndoData};
  }});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(publicUndoContext);
await publicUndoContext.refresh();
assert.doesNotMatch(publicNodes.get('acknowledged-incidents').innerHTML,/data-status-unack/);
publicUndoData.acknowledge_enabled = true;
publicUndoData.can_acknowledge = true;
publicUndoData.csrf = 'public-undo-token';
await publicUndoContext.refresh();
assert.match(publicNodes.get('acknowledged-incidents').innerHTML,/data-status-unack="601"/);
publicNodes.get('acknowledged-incidents').onclick({target:{dataset:{statusUnack:'601'}}});
assert.equal(publicNodes.get('unacknowledgement-dialog').open,true);
publicNodes.get('cancel-unacknowledgement').onclick();
await publicNodes.get('confirm-unacknowledgement').onclick();
assert.equal(publicUndoRequests.length,0);
publicUndoContext.openUnacknowledgement(601);
publicUndoRejected = true;
await publicNodes.get('confirm-unacknowledgement').onclick();
assert.equal(publicNodes.get('unacknowledgement-feedback').textContent,'Public undo rejected');
assert.equal(publicNodes.get('unacknowledgement-dialog').open,true);
publicNodes.get('cancel-unacknowledgement').onclick();
publicUndoRejected = false;
publicUndoContext.openUnacknowledgement(601);
publicUndoData.can_acknowledge = false;
await publicUndoContext.refresh();
await publicNodes.get('confirm-unacknowledgement').onclick();
assert.equal(publicUndoRequests.length,1);
assert.match(publicNodes.get('unacknowledgement-feedback').textContent,/project acknowledgement enabled/);
publicNodes.get('cancel-unacknowledgement').onclick();
publicUndoData.can_acknowledge = true;
await publicUndoContext.refresh();
publicUndoContext.openUnacknowledgement(601);
publicUndoIssue.ack_revision = 2;
await publicUndoContext.refresh();
await publicNodes.get('confirm-unacknowledgement').onclick();
assert.equal(publicUndoRequests.length,1);
assert.match(publicNodes.get('unacknowledgement-feedback').textContent,/changed/);
publicNodes.get('cancel-unacknowledgement').onclick();
publicUndoContext.openUnacknowledgement(601);
await publicNodes.get('confirm-unacknowledgement').onclick();
assert.equal(publicUndoRequests.length,2);
assert.equal(publicUndoRequests.at(-1).body.expected_revision,2);
assert.equal(publicUndoRequests.at(-1).headers['X-CSRF-Token'],'public-undo-token');
assert.equal(publicNodes.get('unacknowledgement-dialog').open,false);
assert.match(publicNodes.get('incidents').innerHTML,/Issue #8/);
console.log('Public Unacknowledge requires opt-in, confirms the selected revision, preserves errors and sends the status CSRF token.');

// Separate browser contexts update from server invalidations, not browser-local storage.
let sharedAcknowledged = false;
let sharedRevision = 0;
let holdMainRefresh = false;
let releaseMainRefresh;
let mainRefreshStarted;
let mainReads = 0;
let concurrentMainReads = 0;
let maximumMainReads = 0;
const mainLiveSources = [];
const mainLiveEvents = new Map();
const mainLiveDocumentEvents = new Map();
const liveIssue = () => ({...undoIssue,id:701,number:9,closed:null,
  acknowledged:sharedAcknowledged ? now : null,ack_revision:sharedRevision});
function liveMainData() {
  const issue = liveIssue();
  return {...undoFixture,incidents:[issue],incident_lists:{active:sharedAcknowledged ? [] : [issue],
    acknowledged:sharedAcknowledged ? [issue] : [],suppressed:[],resolved:[]}};
}
const mainLiveContext = vm.createContext({document:{...context.document,
  addEventListener(type,handler){mainLiveDocumentEvents.set(type,handler);}},localStorage:context.localStorage,
  setInterval(){},addEventListener(type,handler){mainLiveEvents.set(type,handler);},
  EventSource:class {constructor(url){this.url=url;this.closed=false;mainLiveSources.push(this);}close(){this.closed=true;}},
  fetch:async path => {
    if (path === '/api/me') return {ok:true,json:async () => ({id:3,username:'Alice',role:'operator',csrf:'alice-token'})};
    const snapshot = liveMainData();
    mainReads += 1;
    concurrentMainReads += 1;
    maximumMainReads = Math.max(maximumMainReads,concurrentMainReads);
    if (holdMainRefresh) {
      holdMainRefresh = false;
      await new Promise(resolve => {releaseMainRefresh=resolve;mainRefreshStarted();});
    }
    concurrentMainReads -= 1;
    return {ok:true,json:async () => snapshot};
  }});
new vm.Script(script).runInContext(mainLiveContext);
await mainLiveContext.initializeSession();
mainLiveContext.connectAcknowledgementUpdates();
assert.equal(mainLiveSources.length,1);
assert.equal(mainLiveSources[0].url,'/api/ack-events');
sharedAcknowledged = true;
sharedRevision = 1;
await mainLiveSources[0].onmessage();
assert.match(element('acknowledged-incidents').innerHTML,/Issue #9/);

const statusLiveSources = [];
const statusLiveContext = vm.createContext({document:publicContext.document,localStorage:publicContext.localStorage,
  setInterval(){},EventSource:class {constructor(url){this.url=url;statusLiveSources.push(this);}close(){}},
  fetch:async () => {
    const issue = {...liveIssue(),device:'Switch',alias:'Stage',service:'Port status'};
    return {ok:true,json:async () => ({project:'Shared project',devices:[],updated:now,
      incidents:sharedAcknowledged ? [] : [issue],acknowledged_incidents:sharedAcknowledged ? [issue] : [],
      viewer:{username:'Bob',role:'viewer'},can_acknowledge:false,acknowledge_enabled:true})};
  }});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(statusLiveContext);
await statusLiveContext.refresh();
statusLiveContext.connectAcknowledgementUpdates();
assert.equal(statusLiveSources.length,1);
assert.match(publicNodes.get('acknowledged-incidents').innerHTML,/Issue #9/);
assert.doesNotMatch(publicNodes.get('acknowledged-incidents').innerHTML,/data-status-unack/);
sharedAcknowledged = false;
sharedRevision = 2;
await Promise.all([mainLiveSources[0].onmessage(),statusLiveSources[0].onmessage()]);
assert.match(element('incidents').innerHTML,/Issue #9/);
assert.match(publicNodes.get('incidents').innerHTML,/Issue #9/);
assert.match(publicNodes.get('acknowledged-incidents').innerHTML,/No acknowledged issues/);
// A server event arriving during a slow old fetch queues a fresh fetch afterwards.
holdMainRefresh = true;
const started = new Promise(resolve => {mainRefreshStarted=resolve;});
const readsBeforeRace = mainReads;
const oldRefresh = mainLiveContext.refresh();
await started;
sharedAcknowledged = true;
sharedRevision = 3;
const latestRefresh = mainLiveSources[0].onmessage();
releaseMainRefresh();
await Promise.all([oldRefresh,latestRefresh]);
assert.equal(mainReads-readsBeforeRace,2);
assert.equal(maximumMainReads,1);
assert.match(element('acknowledged-incidents').innerHTML,/Issue #9/);
// Navigation suspends the old stream; restoring a cached page reconnects once.
mainLiveEvents.get('pagehide')();
assert.equal(mainLiveSources[0].closed,true);
sharedAcknowledged = false;
sharedRevision = 4;
mainLiveEvents.get('pageshow')({persisted:true});
await mainLiveContext.refresh();
assert.equal(mainLiveSources.length,2);
mainLiveEvents.get('pageshow')({persisted:true});
await mainLiveContext.refresh();
assert.equal(mainLiveSources.length,2);
assert.match(element('incidents').innerHTML,/Issue #9/);
sharedAcknowledged = true;
sharedRevision = 5;
mainLiveDocumentEvents.get('visibilitychange')();
await mainLiveContext.refresh();
assert.match(element('acknowledged-incidents').innerHTML,/Issue #9/);
assert.match(mainLiveContext.renderIncidents([liveIssue()]),/class="issue-action" data-unack/);
const mainIssueStyle = html.match(/\.metric \.issue-action \{([^}]+)\}/)[1];
const publicIssueStyle = statusPage.match(/\.metric \.issue-action \{([^}]+)\}/)[1];
assert.equal(mainIssueStyle,publicIssueStyle);
console.log('Live updates synchronise separate viewers, preserve permissions, serialize racing refreshes and reconnect after navigation; issue action buttons share styling.');

// Presence uses one stable per-page header on normal polling, with no extra endpoint.
const presenceRequests = [];
const originalPresenceFetch = mainLiveContext.fetch;
mainLiveContext.fetch = async (path, options) => {
  presenceRequests.push({path, options});
  const response = await originalPresenceFetch(path, options);
  return {ok:true, json:async () => ({...await response.json(),
    dashboard_presence:{logged_in_users:2,connections:4,activity_window_seconds:60}})};
};
await mainLiveContext.refresh();
await mainLiveContext.refresh();
assert.equal(element('dashboard-presence').textContent, 'Logged-in users: 2 · Connections: 4');
const presenceHeaders = presenceRequests.filter(row => row.path === '/api/state')
  .map(row => row.options.headers['X-Dashboard-Connection']);
assert.equal(presenceHeaders.length,2);
assert.equal(presenceHeaders[0],presenceHeaders[1]);
assert.match(presenceHeaders[0],/^[A-Za-z0-9-]{16,80}$/);
assert.match(statusPage,/dashboardFetch\('\/api\/status', \{headers: \{'X-Dashboard-Connection': dashboardConnection\}\}\)/);
console.log('Presence badge shows separate account/tab counts with a stable polling identity.');

// Reload and dashboard navigation share tab storage; independent tabs do not.
const tabIdentity = page => page.match(/const dashboardConnection = \(\(\) => \{[\s\S]+?\n    \}\)\(\);/)[0];
function identityFor(page, storage) {
  const browser = vm.createContext({sessionStorage:storage});
  new vm.Script(tabIdentity(page)).runInContext(browser);
  return vm.runInContext('dashboardConnection', browser);
}
function freshTabStorage() {
  const values = new Map();
  return {getItem:key => values.get(key) ?? null,setItem:(key,value) => values.set(key,value)};
}
const tabStorage = freshTabStorage();
const firstConnection = identityFor(html, tabStorage);
assert.equal(identityFor(html, tabStorage),firstConnection);
assert.equal(identityFor(statusPage, tabStorage),firstConnection);
assert.notEqual(identityFor(html, freshTabStorage()),firstConnection);
tabStorage.setItem('network-monitor.dashboard-connection','invalid<script>');
assert.match(identityFor(statusPage, tabStorage),/^[A-Za-z0-9-]{16,80}$/);
const deniedStorage = {getItem(){throw new Error('Storage denied');}};
assert.match(identityFor(html, deniedStorage),/^[A-Za-z0-9-]{16,80}$/);
assert.match(identityFor(statusPage, deniedStorage),/^[A-Za-z0-9-]{16,80}$/);
console.log('Connection identity survives refresh/navigation, separates fresh tabs and tolerates denied storage.');

// Recovered acknowledgements retain attribution in Resolved without an undo action.
mainLiveContext.recoveredListIssue = {...liveIssue(),closed:now,acknowledged:now-100,
  acknowledged_by_full_name:'Alice Example',acknowledged_by_username:'alice'};
vm.runInContext(`state.incident_lists.acknowledged=[];
  state.incident_lists.resolved=[recoveredListIssue];`,mainLiveContext);
const recoveredMarkup = mainLiveContext.renderIncidents([mainLiveContext.recoveredListIssue]);
assert.match(recoveredMarkup,/Recovered/);
assert.match(recoveredMarkup,/Alice Example/);
assert.doesNotMatch(recoveredMarkup,/data-unack/);
assert.throws(() => mainLiveContext.openUnacknowledgement(mainLiveContext.recoveredListIssue.id),/recovered/);
console.log('Resolved acknowledged issues retain attribution without Unacknowledge controls.');

assert.match(html, /#notifications-toggle\.notifications-paused \{[^}]*animation: paused-monitoring/);
assert.match(html, /#monitoring-toggle\.monitoring-paused, #notifications-toggle\.notifications-paused \{ animation: none;/);
assert.match(html, /Monitoring and notifications start paused/);
console.log('Notification pause pulses with reduced-motion support; selected deployments wait for Resume all monitoring.');

// Exercise full Admin refresh recovery, including clearing the old global error.
const recoveredFetch = mainLiveContext.fetch;
mainLiveContext.fetch = async () => {throw new TypeError('Failed to fetch');};
await mainLiveContext.refresh().catch(mainLiveContext.report);
assert.equal(element('message').textContent,'Failed to fetch — Server connection lost');
const advancedTime = Date.now() + 31000;
mainLiveContext.Date = class extends Date {static now(){return advancedTime;}};
vm.runInContext('connectionGuard.check()',mainLiveContext);
assert.equal(element('connection-lost').open,true);
mainLiveContext.fetch = recoveredFetch;
await mainLiveContext.refresh();
assert.equal(element('connection-lost').open,false);
assert.equal(element('message').textContent,'');
assert.equal(element('connection-notice').hidden,true);
console.log('A successful full Admin refresh clears Failed to fetch and unlocks controls.');

// A failed initial session lookup must recover through ordinary polling too.
vm.runInContext('currentUser=null',mainLiveContext);
mainLiveContext.fetch = async () => {throw new TypeError('Failed to fetch');};
await mainLiveContext.initializeSession().catch(mainLiveContext.report);
mainLiveContext.fetch = recoveredFetch;
await mainLiveContext.refresh();
assert.match(element('signed-in').textContent,/Alice/);
assert.equal(element('message').textContent,'');
console.log('Initial session lookup failures recover without reloading the browser.');

// Admin sorting matches public choices, uses numeric names and survives reload.
const adminSortStorage = new Map();
const adminSortData = {...fixture,
  devices:[{id:1,name:'SW10',address:'127.0.0.1'},{id:2,name:'SW2',address:'127.0.0.2'},{id:3,name:'SW1',address:'127.0.0.3'}],
  assignments:[{id:1,project:1,device:1,alias:'Alpha',visible:1,monitoring:1},
    {id:2,project:1,device:2,alias:'Zulu',visible:1,monitoring:1,incident_status:'critical'},
    {id:3,project:1,device:3,alias:'Bravo',visible:1,monitoring:1,incident_status:'warning'}],
  services:[{id:1,assignment:1,kind:'ping',revision:1},{id:2,assignment:2,kind:'ping',revision:1},
    {id:3,assignment:3,kind:'ping',revision:1},
    {...stateService,id:4,assignment:1,name:'RSSI'},{...stateService,id:5,assignment:3,name:'RSSI'}],
  latest:[{service:1,status:'healthy',timestamp:Date.now()/1000},
    {service:2,status:'unreachable',timestamp:Date.now()/1000}],
  settings:{active_run:'1',retention_days:'30'},
  incident_lists:{active:[],acknowledged:[],suppressed:[],resolved:[]},
};
function createAdminSortContext() {
  const browser = vm.createContext({document:context.document,setInterval(){},
    localStorage:{getItem:key => adminSortStorage.get(key),setItem:(key,value) => adminSortStorage.set(key,value)},
    fetch:async path => ({ok:true,json:async () => path === '/api/me'
      ? {id:1,role:'operator',username:'sorter'} : adminSortData})});
  new vm.Script(script).runInContext(browser);
  return browser;
}
const adminSortContext = createAdminSortContext();
await adminSortContext.initializeSession();
function assertAdminOrder(names) {
  const markup = element('dashboard').innerHTML;
  const positions = names.map(name => markup.indexOf(name + ' -'));
  assert.ok(positions.every(position => position >= 0));
  assert.deepEqual([...positions].sort((a,b) => a-b),positions);
}
assertAdminOrder(['SW1','SW2','SW10']);
for (const [sort, expected] of [
  ['hostname-desc',['SW10','SW2','SW1']], ['alias',['SW10','SW1','SW2']],
  ['status',['SW2','SW1','SW10']], ['status-ok',['SW10','SW1','SW2']],
  ['severity',['SW2','SW1','SW10']], ['hostname',['SW1','SW2','SW10']],
]) {
  element('host-sort').value = sort;
  element('host-sort').onchange();
  assertAdminOrder(expected);
  element('view-list').onclick();
  assertAdminOrder(expected);
  element('view-cards').onclick();
}
element('host-sort').value = 'severity';
element('host-sort').onchange();
element('service-filter').value = 'RSSI';
element('service-filter').oninput();
assertAdminOrder(['SW1','SW10']);
assert.doesNotMatch(element('dashboard').innerHTML,/SW2 -/);
assert.equal(adminSortStorage.get('field-monitor.main.host-sort'),'severity');
assert.equal(adminSortStorage.has('field-monitor.status.host-sort'),false);
const reloadedAdminSort = createAdminSortContext();
await reloadedAdminSort.initializeSession();
assert.equal(element('host-sort').value,'severity');
assertAdminOrder(['SW1','SW10']);
console.log('Admin host sorting supports all six modes in Cards/List, combines with filters and persists independently.');

// Initial project follows the active/paused deployment, independent of list order.
async function projectSelectionContext(settings, projects) {
  const data = {...fixture,projects:projects || [{id:1,name:'First'},{id:2,name:'Running'},{id:3,name:'Paused'}],
    runs:[{id:12,project:2},{id:13,project:3}],settings:{...fixture.settings,...settings}};
  const browser = vm.createContext({document:context.document,setInterval(){},
    localStorage:{getItem(){return null;},setItem(){}},
    fetch:async path => ({ok:true,json:async () => path === '/api/me'
      ? {id:1,role:'operator',username:'selector'} : data})});
  new vm.Script(script).runInContext(browser);
  await browser.initializeSession();
  return {browser,data};
}
for (const [settings, expected] of [
  [{active_run:'12',paused_run:'13'},'2'],
  [{active_run:'0',paused_run:'13'},'3'],
  [{active_run:'0',paused_run:'0'},'1'],
  [{active_run:'0',paused_run:'999'},'1'],
]) {
  const {browser} = await projectSelectionContext(settings);
  assert.equal(element('project').value,expected);
  element('project').value='1';
  element('project').onchange();
  await browser.refresh();
  assert.equal(element('project').value,'1');
}
const unavailableProject = await projectSelectionContext({active_run:'12',paused_run:'13'});
unavailableProject.data.projects = [{id:1,name:'First'},{id:3,name:'Paused'}];
await unavailableProject.browser.refresh();
assert.equal(element('project').value,'3');
await projectSelectionContext({active_run:'0',paused_run:'0'},[]);
assert.equal(element('project').value,'');
console.log('Initial project selection prefers active/paused deployments, preserves manual choices and handles missing/empty projects.');

// Project deletion uses the shared captured-target confirmation and reports a job.
const deleteProjectData = {...fixture, projects:[{id:1,name:'<Delete & project>'},{id:2,name:'Keep project'}],
  settings:{...fixture.settings,active_run:'1',paused_run:'0'},project_deletions:[]};
const projectDeleteRequests = [];
const projectDeleteContext = vm.createContext({document:context.document,setInterval(){},
  localStorage:{getItem(){return null;},setItem(){}},
  fetch:async (path, options) => {
    if (path === '/api/project-delete') {
      projectDeleteRequests.push(JSON.parse(options.body));
      deleteProjectData.project_deletions=[{id:1,project:1,project_name:'<Delete & project>',state:'queued',deleted_samples:0,error:''}];
      return {ok:true,json:async () => ({ok:true,job:1})};
    }
    return {ok:true,json:async () => path === '/api/me' ? {id:1,role:'admin',username:'admin'}
      : path === '/api/users' ? [] : path === '/api/telegram' || path === '/api/whatsapp'
        ? {configuration:{},outbox:[]} : deleteProjectData};
  }});
new vm.Script(script).runInContext(projectDeleteContext);
await projectDeleteContext.initializeSession();
assert.equal(element('delete-project').disabled,true);
assert.throws(() => projectDeleteContext.openAdministrativeConfirmation('delete-project',{project:1}),/Pause monitoring/);
deleteProjectData.settings.active_run='0'; deleteProjectData.settings.paused_run='1';
await projectDeleteContext.refresh();
assert.equal(element('delete-project').disabled,false);
element('delete-project').onclick();
assert.equal(element('app-confirmation-context').textContent,'<Delete & project>');
assert.match(element('app-confirmation-description').textContent,/Permanent inventory, reusable services and other projects are kept/);
element('cancel-app-action').onclick();
assert.equal(projectDeleteRequests.length,0);
element('delete-project').onclick();
element('project').value='2'; element('project').onchange();
await projectDeleteContext.refresh();
await element('confirm-app-action').onclick();
assert.equal(projectDeleteRequests.length,1);
assert.equal(projectDeleteRequests[0].project,1);
assert.equal(projectDeleteRequests[0].expected_name,'<Delete & project>');
assert.equal(element('project-deletion-notice').hidden,false);
assert.match(element('project-deletion-jobs').innerHTML,/&lt;Delete &amp; project&gt;/);
deleteProjectData.projects=[{id:2,name:'Keep project'}];
deleteProjectData.project_deletions[0].state='completed';
await projectDeleteContext.refresh();
assert.equal(element('project-deletion-notice').hidden,true);
console.log('Project deletion confirms a fixed target, protects active projects, preserves shared-data wording and displays progress.');

// History ranges share one deployment/time scope across graph and exact table pages.
const historyRequests = [];
const historyData = {...fixture,settings:{...fixture.settings,active_run:'0',paused_run:'1'},
  services:fixture.services.map(service => service.id === 2 ? {...service,value_type:'metric',units:'dBm',measurement_revision:2} : service)};
let historyGraphReply;
const rangeHistoryContext = vm.createContext({document:context.document,setInterval(){},
  localStorage:{getItem(){return null;},setItem(){}},
  fetch:async path => {
    if (path.startsWith('/api/history?')) {
      const query = new URL(path,'http://monitor.test').searchParams;
      historyRequests.push(query);
      const rows = [{id:2,timestamp:now-30,value:-55,status:'healthy',display_value:'-55',revision:1},
        {id:1,timestamp:now-60,value:-80,status:'critical',display_value:'-80',revision:1}];
      const measurementRevision = Number(query.get('measurement') || 2);
      const measurements = [1,2].map(version => ({...historyData.services.find(service => service.id === 2),
        measurement_revision:version,units:version === 1 ? 'V' : 'dBm'}));
      const data = query.get('mode') === 'graph'
        ? {rows:rows.map(row => ({...row,measurement_revision:measurementRevision})),total:2,
          aggregated:false,retention_days:30,measurements,measurement:measurements[measurementRevision-1]}
        : {rows:query.has('before_id') ? rows.slice(1) : rows,next:query.has('before_id') ? null : {before_id:1,before_time:now-60}};
      if (query.get('mode') === 'graph' && historyGraphReply) await historyGraphReply;
      return {ok:true,json:async () => data};
    }
    return {ok:true,json:async () => path === '/api/me' ? {id:2,role:'viewer',username:'reader'} : historyData};
  }});
new vm.Script(script).runInContext(rangeHistoryContext);
await rangeHistoryContext.initializeSession();
await rangeHistoryContext.openHistory(2);
assert.equal(element('history').open,true);
assert.equal(element('history-deployment').value,'1');
assert.match(element('history-description').textContent,/2 retained graph readings/);
assert.match(element('history-graph').innerHTML,/<svg/);
assert.equal(historyRequests[0].get('run'),'1');
assert.equal(historyRequests[0].get('start'),historyRequests[1].get('start'));
assert.equal(element('history-measurement-field').hidden,false);
assert.equal(element('history-measurement').value,'2');
assert.equal(historyRequests[0].get('measurement'),'2');
assert.equal(historyRequests[1].get('measurement'),null);
element('history-measurement').value='1';
await element('history-measurement').onchange();
assert.equal(historyRequests.at(-2).get('measurement'),'1');
assert.match(element('history-graph').innerHTML,/>V<\/text>/);
assert.match(element('history-description').textContent,/measurement #1/);

element('show-history-table').onclick();
assert.equal(element('history-table').hidden,false);
await element('history-older').onclick();
assert.match(element('history-page').textContent,/Page 2/);
await element('history-newer').onclick();
assert.match(element('history-page').textContent,/Page 1/);
element('history-start').value='2026-11-01T00:00:00';
element('history-end').value='2026-11-02T00:00:00';
element('history-start').oninput();
assert.equal(element('history-period').value,'custom');
await rangeHistoryContext.loadHistoryRange();
assert.equal(historyRequests.at(-1).get('start'),String(new Date('2026-11-01T00:00:00').getTime()/1000));
const beforeInvalidRange = historyRequests.length;
element('history-end').value='2026-10-01T00:00:00';
await rangeHistoryContext.loadHistoryRange();
assert.equal(historyRequests.length,beforeInvalidRange);
assert.match(element('history-feedback').textContent,/Choose valid/);
// Closing a dialog makes an in-flight response ineligible to repaint it.
element('history-end').value='2026-11-02T00:00:00';
let releaseHistory;
historyGraphReply = new Promise(resolve => {releaseHistory=resolve;});
const pendingHistory = rangeHistoryContext.loadHistoryRange();
element('history').close(); element('history').onclose();
const priorGraph = element('history-graph').innerHTML;
releaseHistory(); await pendingHistory;
assert.equal(element('history-graph').innerHTML,priorGraph);
console.log('History presets/custom dates, paused deployment selection, graph/table paging, validation and stale-response cancellation passed.');

// Action groups move together at their measured fit boundary, independently.
let toolbarRight = 1600;
const projectActionWidths = [280,190,180];
const deploymentActionWidths = [220,210];
const toolbarNodes = new Map();
for (const [id,widths] of [['project-actions',projectActionWidths],['deployment-actions',deploymentActionWidths]]) {
  const classes = new Set();
  toolbarNodes.set(id,{classes,classList:{toggle(name,on){if(on)classes.add(name);else classes.delete(name);}},
    querySelectorAll:() => widths.map(width => ({getBoundingClientRect:() => ({width})}))});
}
toolbarNodes.set('deployment-toolbar',{getBoundingClientRect:() => ({right:toolbarRight})});
toolbarNodes.set('project',{getBoundingClientRect:() => ({right:568})});
const toolbarContext = vm.createContext({el:id => toolbarNodes.get(id),
  getComputedStyle:() => ({paddingRight:'16px',borderRightWidth:'1px',columnGap:'12px'})});
const toolbarFunction = script.match(/    function updateToolbarLayout\(\) \{[\s\S]+?\n    \}/)[0];
new vm.Script(toolbarFunction).runInContext(toolbarContext);
const isBelow = id => toolbarNodes.get(id).classes.has('controls-below');
toolbarContext.updateToolbarLayout();
assert.equal(isBelow('project-actions'),false);
assert.equal(isBelow('deployment-actions'),false);
toolbarRight = 1271; // Exactly 674px is available for the three-button group.
toolbarContext.updateToolbarLayout();
assert.equal(isBelow('project-actions'),false);
toolbarRight = 1270;
toolbarContext.updateToolbarLayout();
assert.equal(isBelow('project-actions'),true);
assert.equal(isBelow('deployment-actions'),false);
toolbarRight = 1038;
toolbarContext.updateToolbarLayout();
assert.equal(isBelow('deployment-actions'),true);
toolbarRight = 1300;
toolbarContext.updateToolbarLayout();
assert.equal(isBelow('project-actions'),false);
projectActionWidths[0] = 330; projectActionWidths[1] = 210; projectActionWidths[2] = 195;
toolbarContext.updateToolbarLayout();
assert.equal(isBelow('project-actions'),true);
assert.equal(isBelow('deployment-actions'),false);
console.log('Toolbar groups move below dropdowns at their fit boundaries and react to longer Pause/Resume labels.');

// Account actions stay right-aligned only while the complete row fits.
let accountWidth = 1000;
let presenceWidth = 300;
const accountClasses = new Set();
const accountNodes = {
  'account-nav':{getBoundingClientRect:() => ({width:accountWidth})},
  'signed-in':{getBoundingClientRect:() => ({width:190})},
  'dashboard-presence':{getBoundingClientRect:() => ({width:presenceWidth})},
  'account-actions':{classList:{toggle(name,on){if(on)accountClasses.add(name);else accountClasses.delete(name);}},
    querySelectorAll:() => [160,90].map(width => ({getBoundingClientRect:() => ({width})}))},
};
const accountContext = vm.createContext({el:id => accountNodes[id],
  getComputedStyle:() => ({paddingLeft:'16px',paddingRight:'16px',borderLeftWidth:'1px',borderRightWidth:'1px',columnGap:'12px'})});
new vm.Script(script.match(/    function updateAccountLayout\(\) \{[\s\S]+?\n    \}/)[0]).runInContext(accountContext);
accountContext.updateAccountLayout();
assert.equal(accountClasses.has('controls-below'),false);
accountWidth=809;
accountContext.updateAccountLayout();
assert.equal(accountClasses.has('controls-below'),true);
accountWidth=810;
accountContext.updateAccountLayout();
assert.equal(accountClasses.has('controls-below'),false);
accountWidth=600; presenceWidth=0;
accountContext.updateAccountLayout();
assert.equal(accountClasses.has('controls-below'),false);
presenceWidth=300;
accountContext.updateAccountLayout();
assert.equal(accountClasses.has('controls-below'),true);
console.log('Account actions move to a left-aligned row when space runs out, including presence badge changes.');

// End-to-end controls use the effective view without overwriting a saved List choice.
for (const publicPage of [false,true]) {
  const store = new Map([[`field-monitor.${publicPage ? 'status' : 'main'}.host-view`,'list']]);
  const node = id => publicPage ? publicNodes.get(id) : element(id);
  const data = publicPage ? {project:'Responsive hosts',updated:now,incidents:[],acknowledged_incidents:[],
    viewer:{username:'reader',role:'viewer',must_change_password:false},can_view_hosts:true,
    devices:[{name:'SW1',alias:'Stage',status:'healthy',services:[{name:'RSSI',value:-55,status:'healthy',units:'dBm'}]}]}
    : {...fixture,services:fixture.services.map(service => service.id === 2 ? {...service,name:'RSSI'} : service)};
  const browser = vm.createContext({document:publicPage ? publicContext.document : context.document,setInterval(){},
    localStorage:{getItem:key => store.get(key),setItem:(key,value) => store.set(key,value)},
    fetch:async path => ({ok:true,json:async () => !publicPage && path === '/api/me'
      ? {id:1,username:'reader',role:'viewer'} : data})});
  new vm.Script((publicPage ? statusPage : html).match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(browser);
  browser.forceCards=false;
  vm.runInContext(`hostViewFit.choose = preferred => {
    const unavailable = forceCards && showServices;
    return {view:unavailable ? 'cards' : preferred,unavailable};
  };`,browser);
  if (publicPage) await browser.refresh(); else await browser.initializeSession();
  const display = () => node(publicPage ? 'devices' : 'dashboard').innerHTML;
  const key = `field-monitor.${publicPage ? 'status' : 'main'}.host-view`;
  assert.match(display(),/class="host-list"/);
  browser.forceCards=true;
  browser.renderHosts();
  assert.doesNotMatch(display(),/class="host-list"/);
  assert.equal(node('view-list').disabled,true);
  assert.equal(node('host-view-fit-note').hidden,false);
  assert.equal(node('view-cards').getAttribute ? node('view-cards').getAttribute('aria-pressed') : node('view-cards').attributes['aria-pressed'],'true');
  assert.equal(store.get(key),'list');
  node('view-list').onclick(); // Programmatic attempts are guarded too.
  assert.equal(store.get(key),'list');
  await browser.refresh();
  assert.equal(node('view-list').disabled,true);
  node('toggle-services').onclick();
  assert.equal(node('view-list').disabled,false);
  assert.match(display(),/class="host-list"/);
  assert.equal(store.get(key),'list');
  node('toggle-services').onclick();
  node('view-cards').onclick(); // Explicit Cards is a genuine preference change.
  assert.equal(store.get(key),'cards');
  node('view-list').onclick();
  assert.equal(store.get(key),'cards');
  browser.forceCards=false;
  browser.renderHosts();
  assert.equal(node('view-list').disabled,false);
  assert.doesNotMatch(display(),/class="host-list"/);
  if (publicPage) {
    node('connection-notice').hidden=false;
    node('summary').textContent='Failed to fetch';
    browser.renderHosts();
    assert.equal(node('summary').textContent,'Failed to fetch');
    await browser.refresh();
    assert.doesNotMatch(node('summary').textContent,/Failed to fetch/);
  }
}
console.log('Both dashboards disable List while forced to Cards, preserve List through refresh/service toggles, and honour explicit Cards choices.');

// Project setup stays above issues, keeps a fresh selection through stale refreshes,
// and confirms writes with a dismissible, auto-hiding toast without moving focus.
assert.ok(html.indexOf('id="toggle-project-configuration"') < html.indexOf('id="toggle-acknowledged"'));
assert.ok(html.indexOf('id="toggle-live"') < html.indexOf('id="project-configuration"'));
assert.ok(html.indexOf('id="project-configuration"') < html.indexOf('<h2>Active issues</h2>'));
assert.match(html, /#monitoring-toggle\.monitoring-paused\s*\{[^}]*color: #e8eff8/);
const projectCreationForm = element('project-creation-test');
projectCreationForm.dataset = {action:'project'};
projectCreationForm.after = feedback => {projectCreationForm.feedback = feedback;};
projectCreationForm.addEventListener = (name, listener) => {projectCreationForm.submit = listener;};
let publishedProject = false, rejectProject = false;
const creationCalls = [], toastTimers = new Map();
let toastTimerId = 0;
const creationFixture = {...fixture,projects:[{id:1,name:'Existing',status_ack_enabled:0}],
  settings:{...fixture.settings,active_run:'1'}};
const creationContext = vm.createContext({document:{...context.document,
  querySelectorAll:selector => selector === 'form[data-action]' ? [projectCreationForm] : [],
  createElement:() => element('project-creation-feedback')},
  FormData:context.FormData, setInterval(){},
  setTimeout(callback){toastTimers.set(++toastTimerId,callback);return toastTimerId;},
  clearTimeout(id){toastTimers.delete(id);},
  fetch:async (path,options) => {
    if (options?.method === 'POST') {
      creationCalls.push(path);
      return {ok:!rejectProject,json:async () => rejectProject ? {error:'Project name already used'} : {ok:true,project:97}};
    }
    if (path === '/api/me') return {ok:true,json:async () => ({id:1,role:'admin',csrf:'test'})};
    if (path === '/api/users') return {ok:true,json:async () => []};
    if (path === '/api/telegram' || path === '/api/whatsapp') return {ok:true,json:async () => ({configuration:{},outbox:[]})};
    return {ok:true,json:async () => ({...creationFixture,
      projects:publishedProject ? [...creationFixture.projects,{id:97,name:'New project',status_ack_enabled:1}] : creationFixture.projects})};
  }});
new vm.Script(script).runInContext(creationContext);
await creationContext.initializeSession();
projectCreationForm.elements.namedItem('name').value='New project';
await projectCreationForm.submit({preventDefault(){}});
assert.equal(vm.runInContext('selectedProject',creationContext),'97');
publishedProject = true;
await creationContext.refresh();
assert.equal(element('project').value,'97');
assert.equal(projectCreationForm.elements.namedItem('name').value,'');
assert.deepEqual(creationCalls,['/api/project']);
assert.equal(element('save-toasts').hidden,false);
assert.equal(element('save-toast-message-1').textContent,'Project added successfully.');
assert.match(element('save-toasts').innerHTML,/save-toast-progress/);
assert.match(element('save-toasts').innerHTML,/--toast-duration: 6000ms/);
assert.equal(projectCreationForm.feedback.textContent,'Project added successfully.');
const firstToastTimer = [...toastTimers.values()][0];
creationContext.notify('Second setting saved.',true);
assert.equal(toastTimers.size,2);
assert.equal(vm.runInContext('saveToasts.size',creationContext),2);
assert.equal([...toastTimers.values()][0],firstToastTimer,'New confirmations do not restart earlier timers');
assert.equal(element('save-toast-message-2').textContent,'Second setting saved.');
assert.ok(element('save-toasts').innerHTML.indexOf('id="save-toast-2"') < element('save-toasts').innerHTML.indexOf('id="save-toast-1"'));
firstToastTimer();
assert.equal(element('save-toast-1').removed,true);
assert.equal(element('save-toasts').hidden,false);
assert.equal(vm.runInContext('saveToasts.size',creationContext),1);
[...toastTimers.values()][0]();
assert.equal(element('save-toast-2').removed,true);
assert.equal(element('save-toasts').hidden,true);
creationContext.notify('<Saved safely>',true);
assert.equal(element('save-toast-message-3').textContent,'<Saved safely>');
assert.doesNotMatch(element('save-toasts').innerHTML,/<Saved safely>/);
creationContext.notify('Fourth confirmation',true);
element('save-toasts').onclick({target:{closest:() => ({dataset:{dismissToast:'3'}})}});
assert.equal(element('save-toast-3').removed,true);
assert.equal(vm.runInContext('saveToasts.size',creationContext),1);
assert.equal(toastTimers.size,1);
creationContext.dismissSaveToast(3); // Dismissal is harmless after its timer was cancelled.
[...toastTimers.values()][0]();
assert.equal(element('save-toast-4').removed,true);
assert.equal(element('save-toasts').hidden,true);
rejectProject = true;
projectCreationForm.elements.namedItem('name').value='Duplicate';
await projectCreationForm.submit({preventDefault(){}});
assert.equal(projectCreationForm.elements.namedItem('name').value,'Duplicate');
assert.equal(element('save-toasts').hidden,true);
assert.equal(element('project').value,'97');
assert.equal(projectCreationForm.feedback.textContent,'Project name already used');
element('assignments-details').open=true;
element('assignments-details').ontoggle();
assert.match(element('assignments-count').textContent,/Assigned devices/);
element('assignments-details').open=false;
element('assignments-details').ontoggle();
assert.equal(element('assignments').innerHTML,'');
await creationContext.refresh();
assert.equal(element('assignments-details').open,false);
console.log('Project setup and independent stacked toast timers, countdown markup, safe messages, expiry and dismissal passed.');

// Default resolved list is ten; search spans older data without stale replies repainting it.
const resolvedCalls = [];
const resolvedRows = Array.from({length:15},(_,index) => ({id:900-index,number:900-index,
  service:2,status:'warning',opened:now-100,closed:now-index,trigger_value:24.1,
  trigger_display:'24.1',trigger_units:'V',trigger_timestamp:now-100}));
const resolvedFixture = {...fixture,settings:{...fixture.settings,active_run:'1'},
  incident_lists:{active:[],acknowledged:[],suppressed:[],resolved:resolvedRows}};
let slowResolved;
const resolvedContext = vm.createContext({document:context.document,FormData:context.FormData,setInterval(){},
  fetch:async path => {
    if (path.startsWith('/api/resolved?')) {
      const query = new URL(path,'http://monitor.test').searchParams;
      resolvedCalls.push(query);
      if (query.get('search') === 'slow') await new Promise(resolve => {slowResolved=resolve;});
      if (query.get('search') === 'error') return {ok:false,json:async () => ({error:'Search unavailable'})};
      const older = query.has('before');
      return {ok:true,json:async () => ({rows:query.get('search') === 'none' ? []
        : [{...resolvedRows[0],number:older ? 20 : 42}],
        next:older ? null : {before:40,before_time:now-30},run:1})};
    }
    return {ok:true,json:async () => path === '/api/me' ? {id:1,role:'viewer',csrf:'test'}
      : path === '/api/users' ? [] : path === '/api/telegram' || path === '/api/whatsapp'
        ? {configuration:{},outbox:[]} : resolvedFixture};
  }});
new vm.Script(script).runInContext(resolvedContext);
await resolvedContext.initializeSession();
await resolvedContext.refresh();
assert.equal((element('resolved-incidents').innerHTML.match(/<div class="metric">/g)||[]).length,10);
assert.match(element('resolved-summary').textContent,/Latest 10/);
assert.equal(resolvedCalls.length,0);
element('resolved-search').value='voltage';
await element('resolved-search').oninput();
assert.match(element('resolved-incidents').innerHTML,/Issue #42/);
assert.equal(element('resolved-search-pages').hidden,false);
assert.equal(element('resolved-older').disabled,false);
await element('resolved-older').onclick();
assert.equal(resolvedCalls.at(-1).get('before'),'40');
assert.match(element('resolved-incidents').innerHTML,/Issue #20/);
await resolvedContext.refresh();
await resolvedContext.renderResolvedIssues();
assert.equal(resolvedCalls.at(-1).get('before'),'40');
assert.equal(element('resolved-search').value,'voltage');
await element('resolved-newest').onclick();
assert.equal(resolvedCalls.at(-1).has('before'),false);
element('resolved-search').value='none';
await element('resolved-search').oninput();
assert.match(element('resolved-incidents').innerHTML,/No resolved issues match/);
element('resolved-search').value='error';
await element('resolved-search').oninput();
assert.equal(element('resolved-summary').textContent,'Search unavailable');
element('resolved-search').value='slow';
const pendingResolved = element('resolved-search').oninput();
await element('clear-resolved-search').onclick();
slowResolved();
await pendingResolved;
assert.equal(element('resolved-search').value,'');
assert.equal((element('resolved-incidents').innerHTML.match(/<div class="metric">/g)||[]).length,10);
assert.match(element('resolved-summary').textContent,/Latest 10/);
assert.equal(element('resolved-search-pages').hidden,true);
console.log('Resolved issues show ten latest recoveries; full search, paging, refresh persistence, empty/error states and stale replies passed.');

// Live host inventory is sign-in-only; issue lists remain available anonymously.
assert.match(statusPage,/<div id="live-host-panel"[^>]* hidden>/);
assert.match(statusPage,/<button id="toggle-hosts"[^>]* hidden disabled>/);
const accessStore = new Map([['field-monitor.status.hide-hosts','false']]);
let accessViewer = null, allowLiveHosts = false;
let holdOldStatus = false, releaseOldStatus, oldStatusStarted;
let logoutPosted;
const oldStatusGate = new Promise(resolve => {oldStatusStarted=resolve;});
const logoutGate = new Promise(resolve => {logoutPosted=resolve;});
const accessPayload = () => ({project:'Public event',deployment:1,updated:now,monitoring_paused:false,
  viewer:accessViewer,can_view_hosts:allowLiveHosts,can_acknowledge:false,acknowledge_enabled:true,
  devices:[{name:'Private live host',alias:'Private alias',status:'healthy',services:[{name:'Private reading',status:'healthy',value:'123.45',units:'V'}]}],
  incidents:[{id:800,number:8,device:'Affected host',alias:'Event alias',service:'Ping',status:'unreachable',opened:now,trigger_display:'Host unreachable',trigger_value:null}],
  acknowledged_incidents:[{id:801,number:9,device:'Affected host',alias:'Event alias',service:'Ping',status:'unreachable',opened:now,acknowledged:now,acknowledged_by_full_name:'Alex Example'}]});
const accessBrowser = vm.createContext({document:publicContext.document,setInterval(){},
  localStorage:{getItem:key => accessStore.get(key),setItem:(key,value) => accessStore.set(key,value)},
  fetch:async (path,options) => {
    if (path === '/api/me') return {ok:true,status:200,json:async () => ({...accessViewer,csrf:'logout-token'})};
    if (path === '/api/logout') {
      accessViewer=null;allowLiveHosts=false;logoutPosted();
      return {ok:true,status:200,json:async () => ({ok:true})};
    }
    const payload = JSON.parse(JSON.stringify(accessPayload()));
    if (holdOldStatus) {
      holdOldStatus=false;oldStatusStarted();
      await new Promise(resolve => {releaseOldStatus=resolve;});
    }
    return {ok:true,status:200,json:async () => payload};
  }});
new vm.Script(statusPage.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(accessBrowser);
await accessBrowser.refresh();
const accessNode = id => publicNodes.get(id);
for (const id of ['live-host-panel','host-controls','devices','toggle-hosts']) assert.equal(accessNode(id).hidden,true);
assert.equal(accessNode('toggle-hosts').disabled,true);
assert.equal(accessNode('devices').innerHTML,'');
assert.equal(vm.runInContext('publicState.devices.length',accessBrowser),0);
assert.match(accessNode('incidents').innerHTML,/Affected host/);
assert.match(accessNode('acknowledged-incidents').innerHTML,/Alex Example/);
accessNode('toggle-hosts').onclick();
accessNode('view-list').onclick();
assert.equal(accessStore.get('field-monitor.status.hide-hosts'),'false');
for (const role of ['admin','operator','viewer']) {
  accessViewer={username:role,role,must_change_password:false};allowLiveHosts=true;
  await accessBrowser.refresh();
  assert.equal(accessNode('live-host-panel').hidden,false);
  assert.equal(accessNode('toggle-hosts').hidden,false);
  assert.equal(accessNode('toggle-hosts').disabled,false);
  assert.match(accessNode('devices').innerHTML,/Private live host/);
}
accessViewer.must_change_password=true;
await accessBrowser.refresh();
assert.equal(accessNode('devices').innerHTML,'');
assert.equal(accessNode('live-host-panel').hidden,true);
accessViewer.must_change_password=false;
await accessBrowser.refresh();
accessNode('toggle-hosts').onclick();
assert.equal(accessStore.get('field-monitor.status.hide-hosts'),'true');
accessViewer=null;allowLiveHosts=false;
await accessBrowser.refresh();
accessNode('toggle-hosts').onclick();
assert.equal(accessStore.get('field-monitor.status.hide-hosts'),'true');
assert.equal(accessNode('devices').innerHTML,'');
accessViewer={username:'reader',role:'viewer',must_change_password:false};allowLiveHosts=true;
await accessBrowser.refresh();
assert.equal(accessNode('toggle-hosts').hidden,false);
assert.equal(accessNode('live-host-panel').hidden,true); // Signed-in preference survives.
accessNode('toggle-hosts').onclick();
assert.match(accessNode('devices').innerHTML,/Private live host/);
holdOldStatus=true;
const accessOldRefresh = accessBrowser.refresh();
await oldStatusGate;
const signingOut = accessNode('status-logout').onclick();
await logoutGate;
// Let sign-out finish its async session lookup/POST while the old status GET stays blocked.
for (let step=0;step<40 && !accessNode('live-host-panel').hidden;step++) await Promise.resolve();
assert.equal(accessNode('live-host-panel').hidden,true);
assert.equal(accessNode('devices').innerHTML,'');
releaseOldStatus();
await Promise.all([accessOldRefresh,signingOut]);
assert.equal(accessNode('devices').innerHTML,'');
assert.equal(accessNode('service-filter-options').innerHTML,'');
assert.equal(accessNode('toggle-hosts').hidden,true);
assert.match(accessNode('incidents').innerHTML,/Affected host/);
console.log('Anonymous/expired/temporary-password status hides host data and controls; signed-in roles retain preferences; logout discards stale authenticated replies.');
