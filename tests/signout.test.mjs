/** Manual logout must never happen merely by opening or cancelling its dialog. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

let reference;
for (const page of ['index.html','status.html']) {
    const html = await readFile(new URL('../app/' + page, import.meta.url), 'utf8');
    const helper = html.match(/    function configureSignOut\(triggerId, performLogout\) \{[\s\S]+?\n    \}/)[0];
    if (reference) assert.equal(helper, reference);
    reference = helper;
    assert.match(html, /id="cancel-signout"[^>]*autofocus/);
    const nodes = new Map();
    const node = id => {
        if (!nodes.has(id)) nodes.set(id, {
            open:false,disabled:false,textContent:'',
            showModal() { this.open=true; },
            close() { this.open=false; this.onclose?.(); },
        });
        return nodes.get(id);
    };
    const context = vm.createContext({ document:{getElementById:node} });
    new vm.Script(helper).runInContext(context);
    let calls=0, reject=false, release;
    context.configureSignOut('trigger', async () => {
        calls++;
        await new Promise(resolve => {release=resolve;});
        if (reject) throw new Error('Server rejected logout');
    });
    const dialog=node('signout-confirmation'), confirm=node('confirm-signout'), cancel=node('cancel-signout');
    node('trigger').onclick();
    assert.equal(dialog.open,true);
    assert.equal(calls,0);
    cancel.onclick();
    await confirm.onclick();
    assert.equal(calls,0);
    node('trigger').onclick();
    let prevented=false;
    dialog.oncancel({preventDefault(){prevented=true;}});
    assert.equal(prevented,false);
    dialog.close();
    await confirm.onclick();
    assert.equal(calls,0);
    node('trigger').onclick();
    reject=true;
    const pending=confirm.onclick();
    assert.equal(confirm.disabled,true);
    assert.equal(cancel.disabled,true);
    assert.equal(node('trigger').disabled,true);
    await confirm.onclick();
    assert.equal(calls,1);
    prevented=false;
    dialog.oncancel({preventDefault(){prevented=true;}});
    assert.equal(prevented,true);
    cancel.onclick();
    assert.equal(dialog.open,true);
    release(); await pending;
    assert.equal(dialog.open,true);
    assert.equal(confirm.disabled,false);
    assert.equal(node('signout-feedback').textContent,'Server rejected logout');
    reject=false;
    const retry=confirm.onclick();
    release(); await retry;
    assert.equal(calls,2);
    assert.equal(dialog.open,false);
    assert.equal(node('trigger').disabled,false);
    if (page === 'index.html') {
        const posted = [], destinations = [];
        context.request = async (path, body) => { posted.push({path,body}); };
        context.location = {assign:path=>destinations.push(path)};
        const binding = html.match(/    configureSignOut\('logout', async \(\) => \{[\s\S]+?\n    \}\);/)[0];
        new vm.Script(binding).runInContext(context);
        node('logout').onclick();
        assert.equal(posted.length,0);
        await node('confirm-signout').onclick();
        assert.equal(posted.length,1);
        assert.equal(posted[0].path,'logout');
        assert.deepEqual(destinations,['/login']);
    }
}
console.log('Both sign-out dialogs require confirmation, preserve Cancel/Escape, block duplicates and retain retryable failures.');
