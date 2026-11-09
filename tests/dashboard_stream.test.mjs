/** Tab identity arbitration and lifecycle, without a browser or external modules. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

for (const filename of ['index.html', 'status.html']) {
    const html = await readFile(new URL('../app/' + filename, import.meta.url), 'utf8');
    const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
    const identity = script.match(/let dashboardConnection = \(\(\) => \{[\s\S]+?\n    \}\)\(\);/)[0];
    const lifecycle = script.slice(script.indexOf('    // A duplicated tab'),
        script.indexOf('    async function refreshDashboard()'));
    const channels = new Set();
    const messages = [];
    let serial = 0;

    class BroadcastChannel {
        constructor(name) { this.name = name; channels.add(this); }
        postMessage(data) {
            for (const peer of channels) {
                if (peer !== this && peer.name === this.name) messages.push({peer, data});
            }
        }
        close() { channels.delete(this); }
    }

    function pump() {
        while (messages.length) {
            const {peer, data} = messages.shift();
            if (channels.has(peer)) peer.onmessage?.({data});
        }
    }

    function storage(initial = null) {
        let value = initial;
        return {getItem: () => value, setItem: (key, item) => { value = item; }};
    }

    function document(sessionStorage) {
        const events = new Map();
        const timers = new Map();
        const sources = [];
        const context = vm.createContext({sessionStorage, BroadcastChannel,
            crypto: {randomUUID: () => 'dashboard-document-' + String(++serial).padStart(8, '0')},
            document: {addEventListener() {}},
            addEventListener: (type, handler) => events.set(type, handler),
            setTimeout(callback) { const timer = ++serial; timers.set(timer, callback); return timer; },
            clearTimeout(timer) { timers.delete(timer); },
            refresh: async () => {}, report() {}, reportLiveRefreshError() {},
            EventSource: class {
                constructor(url) { this.url = url; this.closed = false; sources.push(this); }
                close() { this.closed = true; }
            },
        });
        new vm.Script(identity + '\n' + lifecycle).runInContext(context);
        return {context, events, timers, sources,
            id: () => vm.runInContext('dashboardConnection', context),
            open: () => context.connectAcknowledgementUpdates(),
            settle() {
                pump();
                for (const [timer, callback] of [...timers]) { timers.delete(timer); callback(); }
                pump();
            }};
    }

    const originalStorage = storage();
    const original = document(originalStorage);
    original.open();
    assert.equal(original.sources.length, 0);
    original.settle();
    const originalID = original.id();
    assert.equal(original.sources.length, 1);
    assert.equal(original.sources[0].url, '/api/ack-events?connection=' + originalID);
    original.open();
    assert.equal(original.sources.length, 1);

    // A duplicated browser tab inherits the stored ID, then claims its own slot.
    const duplicated = document(storage(originalID));
    duplicated.open();
    duplicated.settle();
    assert.notEqual(duplicated.id(), originalID);
    assert.equal(original.sources[0].closed, false);
    assert.equal(duplicated.sources.length, 1);

    // Reload closes the old claimant and retains the ID in the replacement URL.
    original.events.get('pagehide')();
    assert.equal(original.sources[0].closed, true);
    const reloaded = document(originalStorage);
    reloaded.open();
    reloaded.settle();
    assert.equal(reloaded.id(), originalID);
    assert.equal(reloaded.sources[0].url, original.sources[0].url);

    // Even simultaneous cloned documents choose distinct identities.
    const firstClone = document(storage('simultaneous-dashboard-id'));
    const secondClone = document(storage('simultaneous-dashboard-id'));
    firstClone.open();
    secondClone.open();
    firstClone.settle();
    secondClone.settle();
    assert.notEqual(firstClone.id(), secondClone.id());

    // Navigating away before arbitration finishes cannot open a late stream.
    const cancelled = document(storage());
    cancelled.open();
    cancelled.events.get('pagehide')();
    cancelled.settle();
    assert.equal(cancelled.sources.length, 0);
    cancelled.events.get('pageshow')({persisted: true});
    cancelled.settle();
    assert.equal(cancelled.sources.length, 1);

    // Restoring a cached page rechecks ownership if another live tab has its ID.
    reloaded.events.get('pagehide')();
    const current = document(originalStorage);
    current.open();
    current.settle();
    reloaded.events.get('pageshow')({persisted: true});
    reloaded.settle();
    assert.notEqual(reloaded.id(), current.id());
    assert.equal(current.sources[0].closed, false);
    for (const page of [duplicated, reloaded, current, firstClone, secondClone, cancelled]) {
        page.events.get('pagehide')();
    }
    assert.equal(channels.size, 0);
}
console.log('Both dashboards preserve refresh identities, separate duplicated tabs and clean up claims across navigation/cache restore.');
