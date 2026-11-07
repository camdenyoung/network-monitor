/** Account-page workflow tests; browser/extension interaction still needs real Chrome QA. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const loginPage = await readFile(new URL('../app/login.html', import.meta.url), 'utf8');
const passwordPage = await readFile(new URL('../app/change-password.html', import.meta.url), 'utf8');
assert.equal((loginPage.match(/<form /g) || []).length, 1);
assert.doesNotMatch(loginPage, /password-form|form\.reset\(/);
assert.match(loginPage, /<button type="submit">Sign in/);
assert.equal((passwordPage.match(/<form /g) || []).length, 1);
assert.match(passwordPage, /name="username" readonly autocomplete="username"/);
assert.match(passwordPage, /<button type="submit">Save password/);

function harness(page, { search = '', mandatory = false, authenticated = true, reject = false } = {}) {
    const nodes = new Map();
    const requests = [];
    const redirects = [];
    let busyRelease;
    const element = id => {
        if (!nodes.has(id)) {
            const fields = new Map();
            const button = { disabled: false };
            nodes.set(id, {
                hidden: true, textContent: '', fields, button, attributes: {},
                querySelector: () => button,
                elements: { namedItem(name) {
                    if (!fields.has(name)) fields.set(name, { value: '' });
                    return fields.get(name);
                } },
                setAttribute(key, value) { this.attributes[key] = value; },
                reset() { throw new Error('Do not clear credentials before navigation.'); },
            });
        }
        return nodes.get(id);
    };
    const context = vm.createContext({
        document: { getElementById: element }, URLSearchParams,
        location: { search, assign: path => redirects.push(path) },
        FormData: class {
            constructor(form) { this.entries = [...form.fields].map(([key, field]) => [key, field.value]); }
            [Symbol.iterator]() { return this.entries[Symbol.iterator](); }
        },
        fetch: async (path, options) => {
            requests.push({ path, options });
            if (path === '/api/me') return {
                ok: authenticated, status: authenticated ? 200 : 401,
                json: async () => ({ username: 'operator', csrf: 'test-csrf', must_change_password: mandatory }),
            };
            if (busyRelease) await new Promise(resolve => { busyRelease.resolve = resolve; });
            if (reject) return { ok: false, status: 400, json: async () => ({ error: 'Rejected credentials' }) };
            return { ok: true, status: 200, json: async () => ({ ok: true }) };
        },
    });
    new vm.Script(page.match(/<script>([\s\S]*?)<\/script>/)[1]).runInContext(context);
    return {
        element, requests, redirects, context,
        block() { busyRelease = {}; },
        release() { busyRelease.resolve(); busyRelease = null; },
    };
}
const event = form => ({ preventDefault() {}, target: form });
for (const [search, destination] of [
    ['', '/'], ['?next=%2Fstatus', '/status'], ['?next=%2F', '/'],
    ['?next=https%3A%2F%2Fevil.example', '/'], ['?next=%2F%2Fevil.example', '/'], ['?next=%2Funknown', '/'],
]) {
    for (const mandatory of [false, true]) {
        const h = harness(loginPage, { search, mandatory });
        const form = h.element('login-form');
        form.elements.namedItem('username').value = 'operator';
        form.elements.namedItem('password').value = 'Dummy-password-123';
        h.block();
        const submission = form.onsubmit(event(form));
        await form.onsubmit(event(form));
        assert.equal(h.requests.filter(r => r.path === '/api/login').length, 1);
        h.release();
        await submission;
        assert.deepEqual(h.redirects, [mandatory
            ? '/change-password' + (destination === '/status' ? '?next=%2Fstatus' : '') : destination]);
        assert.equal(form.elements.namedItem('password').value, 'Dummy-password-123');
        assert.equal(form.button.disabled, false);
    }
    const h = harness(passwordPage, { search, mandatory: true });
    // Complete the asynchronous session lookup before submitting the change.
    await new Promise(resolve => setImmediate(resolve));
    const form = h.element('password-form');
    assert.equal(form.hidden, false);
    assert.equal(form.elements.namedItem('username').value, 'operator');
    assert.equal(h.element('back-dashboard').hidden, true);
    form.elements.namedItem('current_password').value = 'Dummy-password-123';
    form.elements.namedItem('password').value = 'New-password-123';
    form.elements.namedItem('confirm').value = 'Mismatch';
    await form.onsubmit(event(form));
    assert.equal(h.requests.length, 1);
    assert.equal(h.element('message').textContent, 'New passwords do not match.');
    form.elements.namedItem('confirm').value = 'New-password-123';
    h.block();
    const submission = form.onsubmit(event(form));
    await form.onsubmit(event(form));
    h.release();
    await submission;
    assert.equal(h.requests.length, 2);
    assert.equal(h.requests[1].options.headers['X-CSRF-Token'], 'test-csrf');
    assert.deepEqual(h.redirects, [destination]);
}
const rejected = harness(loginPage, { reject: true });
await rejected.element('login-form').onsubmit(event(rejected.element('login-form')));
assert.equal(rejected.element('message').textContent, 'Rejected credentials');
assert.deepEqual(rejected.redirects, []);
assert.equal(rejected.element('login-form').button.disabled, false);
const voluntary = harness(passwordPage, { search: '?next=%2Fstatus' });
await new Promise(resolve => setImmediate(resolve));
assert.equal(voluntary.element('back-dashboard').hidden, false);
assert.equal(voluntary.element('back-dashboard').attributes.href, '/status');
const expired = harness(passwordPage, { search: '?next=%2Fstatus', authenticated: false });
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(expired.redirects, ['/login?next=%2Fstatus']);
assert.equal(expired.element('password-form').hidden, true);
console.log('Separate login/password pages preserve return destinations, credentials, CSRF and single submissions.');
