/** Exercise the production connection guard with a fake clock and network. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const pages = await Promise.all(['index.html','status.html'].map(name =>
  readFile(new URL('../app/' + name, import.meta.url), 'utf8')));
const helpers = pages.map(page => page.match(/\/\/ BEGIN dashboard connection recovery[\s\S]*?\/\/ END dashboard connection recovery\./)[0]);
assert.equal(helpers[0],helpers[1]);

for (const helper of helpers) {
  let clock = 100000;
  let mode = 'healthy';
  let calls = 0;
  let serial = 0;
  const timers = new Map();
  const listeners = new Map();
  const form = {inert:false, draft:'Keep this edit'};
  const preexistingInert = {inert:true};
  const dialog = {open:false,showModal(){this.open=true;},close(){this.open=false;}};
  const notice = {hidden:true,textContent:''};
  const message = {textContent:''};
  const elements = {'connection-lost':dialog,'connection-notice':notice,message};
  const browser = vm.createContext({
    Date:{now:() => clock}, AbortController,
    document:{body:{children:[form,preexistingInert,dialog]},
      getElementById:id => elements[id],addEventListener:(type,listener) => listeners.set(type,listener)},
    setInterval(callback,delay){assert.equal(delay,1000);},
    setTimeout(callback,delay){timers.set(++serial,{callback,delay});return serial;},
    clearTimeout:id => timers.delete(id),
    fetch:async () => {
      calls += 1;
      if (mode === 'failure') throw new TypeError('Failed to fetch');
      if (mode === 'hang') return new Promise(() => {});
      return {ok:true,json:() => mode === 'body-hang' ? new Promise(() => {}) : Promise.resolve({fresh:true})};
    },
  });
  new vm.Script(helper).runInContext(browser);
  const guard = vm.runInContext('connectionGuard',browser);
  guard.healthy();
  mode = 'failure';
  await assert.rejects(browser.dashboardFetch('/api/state'),/Failed to fetch/);
  message.textContent = 'Failed to fetch';
  assert.equal(notice.hidden,false);
  clock += 29999;
  guard.check();
  assert.equal(dialog.open,false);
  clock += 1;
  guard.check();
  assert.equal(dialog.open,true);
  assert.equal(form.inert,true);
  let cancelled = false;
  dialog.oncancel({preventDefault(){cancelled=true;}});
  assert.equal(cancelled,true);
  let blocked = 0;
  listeners.get('click')({preventDefault(){blocked++;},stopImmediatePropagation(){blocked++;}});
  assert.equal(blocked,2);
  const beforeWrite = calls;
  await assert.rejects(browser.dashboardFetch('/api/ack',{method:'POST',body:'{}'}),/Wait for the dashboard to reconnect/);
  assert.equal(calls,beforeWrite);
  mode = 'healthy';
  const response = await browser.dashboardFetch('/api/state');
  assert.equal((await response.json()).fresh,true);
  assert.equal(guard.isLocked(),true); // Fetch alone cannot unlock stale controls.
  guard.healthy(); // The dashboard calls this after a completed render.
  assert.equal(dialog.open,false);
  assert.equal(form.inert,false);
  assert.equal(preexistingInert.inert,true);
  assert.equal(form.draft,'Keep this edit');
  assert.equal(message.textContent,'');
  assert.equal(notice.hidden,true);
  message.textContent = 'Enter a deployment description';
  guard.healthy();
  assert.equal(message.textContent,'Enter a deployment description');

  // Bound a hung request and a hung JSON body, so polling can retry either one.
  for (const [stalled,path,options,timeout] of [
    ['hang','/api/status',undefined,8000], ['body-hang','/api/status',undefined,8000],
    ['hang','/api/history?service=1',undefined,30000], ['hang','/api/ack',{method:'POST'},60000],
  ]) {
    mode = stalled;
    const request = browser.dashboardFetch(path,options);
    const operation = stalled === 'body-hang' ? (await request).json() : request;
    // Attach the rejection handler before firing the simulated timeout.
    const rejected = assert.rejects(operation,/timed out/);
    const timer = [...timers.values()].find(item => item.delay === timeout);
    assert.ok(timer);
    timer.callback();
    await rejected;
    mode = 'healthy';
    await (await browser.dashboardFetch('/api/status')).json();
    guard.healthy();
  }
  assert.equal(timers.size,0);
}
console.log('Both dashboards lock after 30s, block writes/controls, recover cleanly, preserve drafts, and time out hung headers/bodies.');
