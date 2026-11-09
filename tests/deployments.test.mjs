/** Exercise the production rename editor with isolated DOM/network doubles. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../app/index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const editor = script.slice(script.indexOf('    let pendingDeploymentRename = null;'),
    script.indexOf('    let pendingDeploymentProject = null;'));
assert.ok(editor.includes("request('rename-deployment'"));
function functionSource(name) {
    const match = new RegExp(`^    (?:async )?function ${name}\\(`, 'm').exec(script);
    assert.ok(match, name);
    return script.slice(match.index, script.indexOf('\n    }', match.index) + 6);
}
const helpers = ['notify', 'setFormFeedback', 'confirmSaved', 'refreshAfterSave',
    'updatePreviousDeploymentDetails'].map(functionSource).join('\n');

function fixture(options = {}) {
    const nodes = new Map(), posts = [], toasts = [];
    const state = {
        projects: [{id: 1, name: '<Festival project>'}, {id: 2, name: 'Other project'}],
        runs: [{id: 1, project: 1, started: 1234, description: options.name ?? 'Original name'},
            {id: 2, project: 2, started: 5678, description: 'Other deployment'}],
        settings: {active_run: '1'},
    };
    function element(id) {
        if (!nodes.has(id)) nodes.set(id, {
            value: '', textContent: '', open: false, disabled: false,
            classList: {add() {}, toggle() {}},
            setAttribute() {}, focus() { this.focused = true; },
            showModal() { this.open = true; },
            close() { this.open = false; this.onclose?.(); },
        });
        return nodes.get(id);
    }
    element('previous-deployment').value = '1';
    const browser = vm.createContext({
        el: element, state, currentUser: {role: options.role || 'admin'}, selectedProject: '1',
        date: value => String(value), showSaveToast: message => toasts.push(message),
        report: error => { element('message').textContent = error.message; },
        request: async (path, body) => {
            posts.push({path, body});
            if (options.reject) throw new Error('Deployment name changed. Close and reopen the editor to review it.');
            if (options.post) return options.post();
            return {ok: true};
        },
        refresh: async () => {
            if (options.reload) return options.reload();
            if (options.refreshFails) throw new Error('Follow-up GET failed');
        },
    });
    vm.runInContext(helpers + '\n' + editor, browser);
    browser.updatePreviousDeploymentDetails();
    const submit = () => element('rename-deployment-form').onsubmit({preventDefault() {}});
    return {browser, element, state, posts, toasts, submit, options};
}

const resume = html.indexOf('id="resume-selected-deployment"');
const rename = html.indexOf('id="rename-selected-deployment"');
const remove = html.indexOf('id="delete-selected-deployment"');
assert.ok(resume < rename && rename < remove, 'Rename sits between Resume and Delete');
assert.match(html, /<button data-admin id="rename-selected-deployment"[^>]*>Rename selected deployment/);
assert.match(html, /id="deployment-description"[^>]*maxlength="40"/);
assert.match(html, /id="rename-deployment-name"[^>]*maxlength="40"/);

const creating = fixture();
const creation = script.slice(script.indexOf('    let pendingDeploymentProject = null;'),
    script.indexOf("    el('monitoring-toggle').onclick"));
vm.runInContext(creation, creating.browser);
creating.element('activate').onclick();
for (const value of ['   ', 'x'.repeat(41)]) {
    creating.element('deployment-description').value = value;
    await creating.element('confirm-deployment').onclick();
    assert.equal(creating.posts.length, 0);
    assert.match(creating.element('deployment-confirmation-feedback').textContent, /1–40/);
}
creating.element('deployment-description').value = 'x'.repeat(40);
await creating.element('confirm-deployment').onclick();
assert.equal(creating.posts.length, 1);
assert.equal(creating.posts[0].body.description.length, 40);

const cancelled = fixture();
assert.equal(cancelled.element('rename-selected-deployment').disabled, false, 'Active run can be renamed');
cancelled.element('rename-selected-deployment').onclick();
assert.equal(cancelled.posts.length, 0);
assert.equal(cancelled.element('rename-deployment-name').value, 'Original name');
assert.match(cancelled.element('rename-deployment-context').textContent, /Deployment #1.*<Festival project>/);
assert.equal(cancelled.element('rename-deployment-name').focused, true);
cancelled.element('cancel-deployment-name').onclick();
await cancelled.submit();
assert.equal(cancelled.posts.length, 0, 'Cancel/closed-dialog submits are inert');
cancelled.element('rename-selected-deployment').onclick();
cancelled.element('rename-deployment-dialog').oncancel({preventDefault() { assert.fail('Idle Escape should close'); }});
cancelled.element('rename-deployment-dialog').close();
await cancelled.submit();
assert.equal(cancelled.posts.length, 0);

for (const role of ['operator', 'viewer']) {
    const restricted = fixture({role});
    assert.equal(restricted.element('rename-selected-deployment').disabled, true);
    restricted.element('rename-selected-deployment').onclick();
    await restricted.submit();
    assert.equal(restricted.element('rename-deployment-dialog').open, false);
    assert.equal(restricted.posts.length, 0);
}

for (const value of ['', '   ', 'x'.repeat(41)]) {
    const invalid = fixture();
    invalid.element('rename-selected-deployment').onclick();
    invalid.element('rename-deployment-name').value = value;
    await invalid.submit();
    assert.equal(invalid.posts.length, 0);
    assert.match(invalid.element('rename-deployment-feedback').textContent, /1–40/);
    assert.equal(invalid.element('rename-deployment-name').value, value);
}

// Legacy text is shown intact and requires an explicit shorter replacement.
const legacy = fixture({name: 'Older description '.repeat(20)});
legacy.element('rename-selected-deployment').onclick();
assert.equal(legacy.element('rename-deployment-name').value, legacy.state.runs[0].description);
await legacy.submit();
assert.equal(legacy.posts.length, 0);
legacy.element('rename-deployment-name').value = 'x'.repeat(40);
await legacy.submit();
assert.equal(legacy.posts[0].body.description.length, 40);
assert.equal(legacy.posts[0].body.expected_description, legacy.state.runs[0].description);

// Refresh/selection changes preserve the draft and the target captured on open.
const captured = fixture({reject: true});
captured.element('rename-selected-deployment').onclick();
captured.element('rename-deployment-name').value = 'Unsaved draft';
captured.state.runs[0].description = 'Renamed by another Admin';
captured.element('previous-deployment').value = '2';
vm.runInContext("selectedProject = '2'", captured.browser);
captured.browser.updatePreviousDeploymentDetails();
assert.equal(captured.element('rename-deployment-name').value, 'Unsaved draft');
await captured.submit();
assert.deepEqual(JSON.parse(JSON.stringify(captured.posts[0])), {
    path: 'rename-deployment', body: {project: 1, run: 1,
        expected_description: 'Original name', description: 'Unsaved draft'},
});
assert.equal(captured.element('rename-deployment-dialog').open, true);
assert.equal(captured.element('rename-deployment-name').value, 'Unsaved draft');
assert.match(captured.element('rename-deployment-feedback').textContent, /name changed/);
assert.equal(captured.toasts.length, 0);

let completeWrite, failRefresh;
const pending = fixture({post: () => new Promise(resolve => { completeWrite = resolve; }),
    reload: () => new Promise((resolve, reject) => { failRefresh = reject; })});
pending.element('rename-selected-deployment').onclick();
pending.element('rename-deployment-name').value = '  Short new name  ';
const saving = pending.submit();
await pending.submit();
pending.element('cancel-deployment-name').onclick();
let blockedEscape = false;
pending.element('rename-deployment-dialog').oncancel({preventDefault() { blockedEscape = true; }});
assert.equal(blockedEscape, true);
assert.equal(pending.element('rename-deployment-dialog').open, true);
assert.equal(pending.posts.length, 1);
assert.equal(pending.toasts.length, 0);
completeWrite({ok: true});
await new Promise(resolve => setImmediate(resolve));
assert.equal(pending.element('rename-deployment-dialog').open, false);
assert.equal(pending.toasts.length, 1);
assert.equal(pending.posts[0].body.description, 'Short new name');
failRefresh(new Error('Follow-up GET failed'));
await saving;
await pending.submit();
assert.equal(pending.posts.length, 1, 'Stale Save cannot replay the rename');
assert.equal(pending.element('save-deployment-name').disabled, false);
assert.match(pending.element('message').textContent, /Deployment name saved.*Dashboard refresh failed/);

console.log('Deployment rename preserves captured targets/drafts, blocks restricted/stale/repeat actions, retains legacy names and confirms writes before refresh.');
