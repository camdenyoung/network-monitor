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
    const networkEvents = [];
    const streams = new Map();
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
        let delivered = 0;
        while (messages.length) {
            assert.ok(++delivered < 500, 'Tab arbitration must converge without a message loop');
            const {peer, data} = messages.shift();
            if (channels.has(peer)) peer.onmessage?.({data});
        }
        while (networkEvents.length) networkEvents.shift()();
    }

    function storage(initial = null) {
        let value = initial;
        return {getItem: () => value, setItem: (key, item) => { value = item; }};
    }

    function document(sessionStorage, {started = 100000 + serial, owner = null, mode = 'healthy'} = {}) {
        const events = new Map();
        const timers = new Map();
        const sources = [];
        let refreshes = 0;
        let generated = 0;
        let channelType = BroadcastChannel;
        if (mode === 'absent') channelType = undefined;
        if (mode === 'constructor-fails') channelType = class {constructor() {throw new Error('Blocked');}};
        if (mode === 'post-fails') channelType = class extends BroadcastChannel {
            postMessage() {throw new Error('Cannot coordinate');}
        };
        const context = vm.createContext({sessionStorage, BroadcastChannel: channelType,
            Date: class extends Date {static now() {return started;}},
            crypto: {randomUUID: () => (++generated === 1 && owner) ||
                'dashboard-document-' + String(++serial).padStart(8, '0')},
            document: {addEventListener() {}},
            addEventListener: (type, handler) => events.set(type, handler),
            setTimeout(callback) { const timer = ++serial; timers.set(timer, callback); return timer; },
            clearTimeout(timer) { timers.delete(timer); },
            refresh: async () => {refreshes += 1;}, report() {}, reportLiveRefreshError() {},
            EventSource: class {
                constructor(url) {
                    this.url = url; this.closed = false; sources.push(this);
                    this.key = new URL(url, 'http://monitor.test').searchParams.get('connection');
                    const previous = streams.get(this.key);
                    if (!previous && streams.size >= 20) {
                        this.refused = true;
                        networkEvents.push(() => this.onerror?.());
                    } else {
                        streams.set(this.key, this);
                        if (previous) networkEvents.push(() => previous.onerror?.());
                    }
                }
                close() {
                    this.closed = true;
                    if (streams.get(this.key) === this) streams.delete(this.key);
                }
            },
        });
        new vm.Script(identity + '\n' + lifecycle).runInContext(context);
        return {context, events, timers, sources,
            id: () => vm.runInContext('dashboardConnection', context),
            channel: () => vm.runInContext('dashboardTabChannel', context),
            polling: () => vm.runInContext('dashboardTabPollingOnly', context),
            refreshes: () => refreshes,
            open: () => context.connectAcknowledgementUpdates(),
            retry() {vm.runInContext('acknowledgementRetryAt = 0', context); context.connectAcknowledgementUpdates();},
            fireTimers() {
                for (const [timer, callback] of [...timers]) {timers.delete(timer); callback();}
            },
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

    // A reply arriving after startup still resolves the collision. Simulate
    // server takeover too, so this verifies actual streams as well as tab IDs.
    const lateClone = document(storage(originalID));
    lateClone.open();
    lateClone.fireTimers(); // The 150ms timer fires before any channel messages.
    assert.equal(lateClone.sources[0].url, original.sources[0].url);
    lateClone.settle();
    assert.notEqual(lateClone.id(), originalID);
    assert.equal(lateClone.sources[0].closed, true);
    assert.equal(lateClone.sources.length, 2);
    original.retry();
    pump();
    assert.equal(streams.get(originalID), original.sources.at(-1));
    assert.equal(streams.get(lateClone.id()), lateClone.sources.at(-1));
    const settledIdentity = lateClone.id();
    const settledSources = lateClone.sources.length;
    const refreshes = lateClone.refreshes();
    lateClone.sources[0].onerror();
    lateClone.sources[0].onmessage();
    lateClone.channel().onmessage({data:{type:'occupied',connection:originalID,
        owner:'stale-owner',started:0,target:'unknown'}});
    lateClone.open();
    assert.equal(lateClone.id(), settledIdentity);
    assert.equal(lateClone.sources.length, settledSources);
    assert.equal(lateClone.refreshes(), refreshes);
    lateClone.events.get('pagehide')();

    // Reload closes the old claimant and retains the ID in the replacement URL.
    original.events.get('pagehide')();
    assert.equal(original.sources.at(-1).closed, true);
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

    // Older-document priority overrides UUID ordering; repeated/out-of-order
    // probe and occupied messages must not make the winner change identity.
    const older = document(storage('ordered-dashboard-identity'), {started:100,owner:'zzzz-older-document'});
    const younger = document(storage('ordered-dashboard-identity'), {started:200,owner:'aaaa-younger-document'});
    older.open(); younger.open();
    older.fireTimers(); younger.fireTimers();
    messages.reverse();
    const repeated = [...messages];
    messages.push(...repeated, ...repeated);
    older.settle(); younger.settle();
    older.retry(); pump();
    assert.equal(older.id(), 'ordered-dashboard-identity');
    assert.notEqual(younger.id(), older.id());
    const youngerSourceCount = younger.sources.length;
    messages.push(...repeated);
    pump();
    assert.equal(older.id(), 'ordered-dashboard-identity');
    assert.equal(younger.sources.length, youngerSourceCount);

    // Equal timestamps use the owner ID consistently, including late messages.
    const tieWinner = document(storage('tied-dashboard-identity'), {started:300,owner:'aaaa-tie-document'});
    const tieLoser = document(storage('tied-dashboard-identity'), {started:300,owner:'zzzz-tie-document'});
    tieWinner.open(); tieLoser.open();
    tieWinner.fireTimers(); tieLoser.fireTimers();
    messages.reverse();
    tieWinner.settle(); tieLoser.settle();
    assert.equal(tieWinner.id(), 'tied-dashboard-identity');
    assert.notEqual(tieLoser.id(), tieWinner.id());

    // Legacy Build 115 replies have no timestamp. Yield to that existing peer;
    // malformed/new-protocol messages cannot force arbitrary identity changes.
    const legacy = document(storage('legacy-dashboard-identity'));
    legacy.open(); legacy.settle();
    const previousLegacySource = legacy.sources[0];
    legacy.channel().onmessage({data:{type:'occupied',connection:legacy.id(),
        owner:'legacy-document-owner',target:vm.runInContext('dashboardDocumentOwner', legacy.context)}});
    legacy.settle();
    assert.notEqual(legacy.id(), 'legacy-dashboard-identity');
    assert.equal(previousLegacySource.closed, true);
    const validIdentity = legacy.id();
    for (const started of [NaN, Infinity, -1, '100', null]) {
        legacy.channel().onmessage({data:{type:'probe',connection:validIdentity,
            owner:'invalid-document-owner',started}});
    }
    legacy.channel().onmessage({data:{type:'occupied',connection:validIdentity,
        owner:'wrong-target-owner',started:0,target:'another-document'}});
    assert.equal(legacy.id(), validIdentity);

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
    current.settle();
    assert.equal(reloaded.id(), originalID); // The restored older document wins.
    assert.notEqual(reloaded.id(), current.id());
    assert.equal(current.sources[0].closed, true);
    for (const page of [duplicated, reloaded, current, firstClone, secondClone, cancelled,
        older, younger, tieWinner, tieLoser, legacy]) {
        page.events.get('pagehide')();
    }
    assert.equal(channels.size, 0);
    assert.equal(streams.size, 0);

    // Missing/blocked coordination never opens an unsafe stream with a copied
    // identity. Normal refresh and navigation remain usable in polling mode.
    for (const mode of ['absent', 'constructor-fails', 'post-fails']) {
        const page = document(storage('copied-dashboard-identity'), {mode});
        page.open(); page.settle();
        assert.equal(page.polling(), true);
        assert.equal(page.sources.length, 0);
        assert.equal(page.timers.size, 0);
        await page.context.refresh();
        page.open();
        assert.equal(page.refreshes(), 1);
        assert.equal(page.sources.length, 0);
        page.events.get('pagehide')();
        page.events.get('pageshow')({persisted:true});
        page.settle();
        assert.equal(page.polling(), true);
        assert.equal(page.sources.length, 0);
        page.events.get('pagehide')();
        assert.equal(channels.size, 0);
    }

    // A channel failure after a stream opened also releases it and cancels
    // timers. Old callbacks cannot revive the stream or alter the new claim.
    const runtimeFailure = document(storage());
    runtimeFailure.open(); runtimeFailure.settle();
    const failedChannel = runtimeFailure.channel();
    const failedSource = runtimeFailure.sources[0];
    failedChannel.onmessageerror();
    assert.equal(runtimeFailure.polling(), true);
    assert.equal(failedSource.closed, true);
    failedSource.onerror(); failedSource.onmessage();
    runtimeFailure.open();
    assert.equal(runtimeFailure.sources.length, 1);
    runtimeFailure.events.get('pagehide')();
    runtimeFailure.events.get('pageshow')({persisted:true});
    runtimeFailure.settle();
    assert.equal(runtimeFailure.polling(), false);
    assert.equal(runtimeFailure.sources.length, 2);
    failedChannel.onmessageerror();
    assert.equal(runtimeFailure.polling(), false);
    runtimeFailure.events.get('pagehide')();
    assert.equal(channels.size, 0);
    assert.equal(streams.size, 0);

    const sendFailure = document(storage());
    sendFailure.open(); sendFailure.settle();
    const brokenChannel = sendFailure.channel();
    brokenChannel.postMessage = () => {throw new Error('Channel closed unexpectedly');};
    brokenChannel.onmessage({data:{type:'probe',connection:sendFailure.id(),
        owner:'younger-document-owner',started:Number.MAX_SAFE_INTEGER}});
    assert.equal(sendFailure.polling(), true);
    assert.equal(sendFailure.sources[0].closed, true);
    assert.equal(sendFailure.timers.size, 0);
    sendFailure.open();
    assert.equal(sendFailure.sources.length, 1);
    await sendFailure.context.refresh();
    assert.equal(sendFailure.refreshes(), 1);
    sendFailure.events.get('pagehide')();
    assert.equal(channels.size, 0);
    assert.equal(streams.size, 0);

    // Full capacity remains bounded: the old shared identity can be replaced,
    // while a corrected duplicate needs its own slot and falls back on refusal.
    const full = [];
    for (let index = 0; index < 20; index += 1) {
        const page = document(storage('capacity-dashboard-' + index));
        page.open(); page.settle(); full.push(page);
    }
    const overflowClone = document(storage(full[0].id()));
    overflowClone.open(); overflowClone.fireTimers(); overflowClone.settle();
    full[0].retry(); pump();
    assert.notEqual(overflowClone.id(), full[0].id());
    const refusedPage = [full[0], overflowClone].find(page => page.sources.at(-1).refused);
    assert.ok(refusedPage); // Twenty slots cannot admit twenty-one distinct tabs.
    assert.equal(streams.size, 20);
    const refusedSourceCount = refusedPage.sources.length;
    refusedPage.open();
    assert.equal(refusedPage.sources.length, refusedSourceCount);
    for (const page of [...full, overflowClone]) page.events.get('pagehide')();
    assert.equal(channels.size, 0);
    assert.equal(streams.size, 0);
}
console.log('Both dashboards resolve late/out-of-order tab conflicts, use safe polling on coordination failure, and retain bounded lifecycle/capacity handling.');
