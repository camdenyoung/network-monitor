/** Run production save handlers against disposable DOM/network doubles. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../app/index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function functionSource(name) {
    const match = new RegExp(`^    (?:async )?function ${name}\\(`, 'm').exec(script);
    assert.ok(match, name);
    const end = script.indexOf('\n    }', match.index);
    return script.slice(match.index, end + 6);
}

function handlerSource(id, event = 'onsubmit') {
    const start = script.indexOf(`    el('${id}').${event} = async`);
    assert.ok(start >= 0, id);
    const end = script.indexOf('\n    };', start);
    return script.slice(start, end + 7);
}

function bindingsSource(startText, endText) {
    const start = script.indexOf(startText);
    const end = script.indexOf(endText, start);
    assert.ok(start >= 0 && end > start);
    return script.slice(start, end);
}

const userBindings = bindingsSource('    for (const [formId, action, feedbackId] of [',
    "    document.body.addEventListener('click'");
const retryBindings = bindingsSource("    for (const channel of ['telegram', 'whatsapp']) {",
    "    configureSignOut('logout'");
const helpers = ['notify', 'setFormFeedback', 'confirmSaved', 'refreshAfterSave',
    'performAction', 'changeDeviceDefaults'].map(functionSource).join('\n');

function fixture(options = {}) {
    const nodes = new Map(), posts = [], toasts = [], navigations = [];
    let reads = 0;
    function element(id) {
        if (!nodes.has(id)) {
            const classes = new Set(), fields = new Map();
            const node = {
                value: 'Review deployment', textContent: '', disabled: false, open: true,
                resets: 0, classes, fields,
                classList: {
                    add(name) { classes.add(name); },
                    remove(name) { classes.delete(name); },
                    toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
                },
                elements: {namedItem(name) {
                    if (!fields.has(name)) fields.set(name, {
                        value: name === 'user' ? '2' : '20', checked: true,
                    });
                    return fields.get(name);
                }},
                reset() { this.resets++; },
                close() { this.open = false; },
                querySelector() { return element(id + '-submit'); },
                querySelectorAll() { return [element(id + '-submit')]; },
            };
            nodes.set(id, node);
        }
        return nodes.get(id);
    }
    const request = async (path, body) => {
        posts.push({path, body});
        if (options.reject) throw new Error('Save rejected');
        if (options.post) return options.post();
        return {added: 1, skipped: 0, replaced: 2, total: 1};
    };
    const reload = async () => {
        reads++;
        if (options.reload) return options.reload();
        if (options.refreshFails) throw new Error('Follow-up GET failed');
    };
    const browser = vm.createContext({
        el: element, request, refresh: reload, loadAdmin: reload,
        showSaveToast: message => toasts.push(message),
        location: {assign: destination => navigations.push(destination)},
        FormData: class {
            constructor(form) { this.form = form; }
            *[Symbol.iterator]() { for (const [name, field] of this.form.fields) yield [name, field.value]; }
            get() { return {type: 'image/png', size: 100}; }
        },
        createImageBitmap: async () => ({width: 16, height: 16, close() {}}),
        dashboardFetch: async (path, settings) => {
            await request(path, settings.body);
            return {ok: true};
        },
        currentUser: {id: 1, csrf: 'mock-csrf'}, selectedProject: '1', defaultsDevice: 1,
        state: {settings: {notifications_paused: '1'}},
        reminderSettingsLoaded: true, sessionSettingsLoaded: true, connectionSettingsLoaded: true,
        pendingLibraryImport: {mode: 'merge', services: []}, pendingDeploymentProject: 1,
    });
    vm.runInContext(helpers + '\nfunction report(error) { notify(error.message); }', browser);
    return {browser, element, posts, toasts, navigations, options, readCount: () => reads};
}

const forms = [
    ['reminder-settings-form', 'reminder-settings-feedback'],
    ['session-settings-form', 'session-settings-feedback'],
    ['connection-settings-form', 'connection-settings-feedback'],
    ['telegram-form', 'telegram-feedback'],
    ['whatsapp-form', 'whatsapp-feedback'],
    ['project-edit-form', 'project-feedback'],
    ['project-duplicate-form', 'project-feedback'],
    ['project-status-form', 'project-feedback'],
    ['project-logo-form', 'project-feedback'],
    ['host-stability-form', 'host-stability-feedback'],
];
const cases = forms.map(([id, feedback]) => ({
    name: id, feedback, source: handlerSource(id),
    run: f => f.element(id).onsubmit({preventDefault() {}, target: f.element(id)}),
}));
for (const id of ['user-form', 'user-edit-form']) cases.push({
    name: id, feedback: id === 'user-form' ? 'user-feedback' : 'user-edit-feedback',
    source: userBindings,
    run: f => {
        f.element(id).elements.namedItem('user');
        return f.element(id).onsubmit({preventDefault() {}, target: f.element(id)});
    },
});
for (const [id, feedback] of [
    ['remove-project-logo', 'project-feedback'], ['notifications-toggle', 'message'],
    ['telegram-test', 'telegram-feedback'], ['whatsapp-test', 'whatsapp-feedback'],
    ['confirm-library-import', 'library-import-error'],
]) cases.push({
    name: id, feedback, source: handlerSource(id, 'onclick'),
    run: f => f.element(id).onclick(),
});
for (const channel of ['telegram', 'whatsapp']) cases.push({
    name: channel + '-retry', feedback: channel + '-feedback', source: retryBindings,
    run: f => f.element(channel + '-retry').onclick(),
});
cases.push({
    name: 'inventory default from library', feedback: 'device-default-feedback', source: '',
    run: f => f.browser.changeDeviceDefaults('device-default-from-template',
        {template: 1, name: 'Copied definition'}, f.element('default-submit')),
});

for (const test of cases) {
    for (const options of [{}, {refreshFails: true}, {reject: true}]) {
        const f = fixture(options);
        vm.runInContext(test.source, f.browser);
        await test.run(f);
        assert.equal(f.posts.length, 1, test.name + ': exactly one mutation');
        assert.equal(f.toasts.length, options.reject ? 0 : 1,
            test.name + ': one confirmed-success toast, none on rejection');
        if (options.reject) {
            assert.equal(f.readCount(), 0, test.name + ': rejected writes do not refresh');
            assert.match(f.element(test.feedback).textContent, /Save rejected/, test.name);
        } else if (options.refreshFails && f.readCount()) {
            assert.match(f.element('message').textContent, /Dashboard refresh failed/, test.name);
            assert.doesNotMatch(f.element(test.feedback).textContent, /Follow-up GET failed/, test.name);
        }
    }
}

// A rejected later save must remove success styling without creating another toast.
const laterFailure = fixture();
vm.runInContext(handlerSource('connection-settings-form'), laterFailure.browser);
const settingsForm = laterFailure.element('connection-settings-form');
await settingsForm.onsubmit({preventDefault() {}, target: settingsForm});
assert.equal(laterFailure.element('connection-settings-feedback').classes.has('success'), true);
laterFailure.options.reject = true;
await settingsForm.onsubmit({preventDefault() {}, target: settingsForm});
assert.equal(laterFailure.element('connection-settings-feedback').classes.has('success'), false);
assert.equal(laterFailure.toasts.length, 1);

// No confirmation before the POST resolves; repeated pending Settings submits
// must not queue a second write or confirmation.
for (const [id] of forms.slice(0, 3)) {
    let completeWrite;
    const pending = fixture({post: () => new Promise(resolve => { completeWrite = resolve; })});
    vm.runInContext(handlerSource(id), pending.browser);
    const form = pending.element(id);
    const saving = form.onsubmit({preventDefault() {}, target: form});
    assert.equal(pending.toasts.length, 0);
    await form.onsubmit({preventDefault() {}, target: form});
    assert.equal(pending.posts.length, 1);
    completeWrite({ok: true});
    await saving;
    assert.equal(pending.toasts.length, 1);
}

// Confirmations are retired at POST success, before a slow/failing refresh.
let failReload;
const activation = fixture({reload: () => new Promise((resolve, reject) => { failReload = reject; })});
vm.runInContext(handlerSource('confirm-deployment', 'onclick'), activation.browser);
const first = activation.element('confirm-deployment').onclick();
await new Promise(resolve => setImmediate(resolve));
assert.equal(activation.posts.length, 1);
assert.equal(activation.element('deployment-confirmation').open, false);
assert.equal(activation.browser.pendingDeploymentProject, null);
assert.equal(activation.toasts.length, 1);
await activation.element('confirm-deployment').onclick();
assert.equal(activation.posts.length, 1);
failReload(new Error('Follow-up GET failed'));
await first;
await activation.element('confirm-deployment').onclick();
assert.equal(activation.posts.length, 1, 'Stale Continue cannot create a second deployment');
assert.equal(activation.element('confirm-deployment').disabled, false);
assert.match(activation.element('message').textContent, /New deployment selected.*Dashboard refresh failed/);

const rejectedActivation = fixture({reject: true});
vm.runInContext(handlerSource('confirm-deployment', 'onclick'), rejectedActivation.browser);
await rejectedActivation.element('confirm-deployment').onclick();
assert.equal(rejectedActivation.toasts.length, 0);
assert.equal(rejectedActivation.element('deployment-confirmation').open, true);
assert.equal(rejectedActivation.browser.pendingDeploymentProject, 1);
assert.match(rejectedActivation.element('deployment-confirmation-feedback').textContent, /Save rejected/);

// Helpers and navigation/issue exceptions never automatically replay a mutation.
const operational = fixture({refreshFails: true});
await operational.browser.performAction('pause', {});
assert.equal(operational.posts.length, 1);
assert.equal(operational.toasts.length, 1);
assert.match(operational.element('message').textContent, /Changes saved.*Dashboard refresh failed/);

const selfEdit = fixture();
vm.runInContext(userBindings, selfEdit.browser);
selfEdit.element('user-edit-form').elements.namedItem('user').value = '1';
await selfEdit.element('user-edit-form').onsubmit({preventDefault() {}, target: selfEdit.element('user-edit-form')});
assert.deepEqual(selfEdit.navigations, ['/login']);
assert.equal(selfEdit.toasts.length, 0);
assert.equal(selfEdit.readCount(), 0);

console.log(`${cases.length} save/queue paths confirm once, preserve failures and tolerate failed refreshes; deployment retry and self-edit navigation checks passed.`);
