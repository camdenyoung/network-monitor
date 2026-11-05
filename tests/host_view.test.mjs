/** Responsive view policy: intrinsic list measurement, preferences and hysteresis. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const pages = await Promise.all(['index.html','status.html'].map(name =>
  readFile(new URL('../app/' + name, import.meta.url),'utf8')));
const helpers = pages.map(page => page.match(/\/\/ BEGIN responsive host view[\s\S]*?\/\/ END responsive host view\./)[0]);
assert.equal(helpers[0],helpers[1]);

for (const helper of helpers) {
  let width = 1200;
  let required = 900;
  let changed = 0;
  let built = 0;
  let removedPopups = 0;
  const removedAttributes = [];
  const container = {get clientWidth(){return width;}};
  let probe;
  const observed = new Set();
  const browser = vm.createContext({
    document:{getElementById:() => container,body:{appendChild(node){probe=node;}},
      createElement(){return {inert:false,attributes:{},setAttribute(key,value){this.attributes[key]=value;},
        set innerHTML(value){built++;this.firstElementChild={
          getBoundingClientRect:() => ({width:required}),get scrollWidth(){return required;}};},
        querySelectorAll(selector){return selector === '.menu-buttons'
          ? [{remove(){removedPopups++;}}] : [{removeAttribute(name){removedAttributes.push(name);}}];}};}},
    ResizeObserver:class {constructor(callback){this.callback=callback;}observe(node){observed.add(node);}unobserve(node){observed.delete(node);}},
    localStorage:{setItem(){throw new Error('Automatic fallback must not write preferences');}},
    changed(){changed++;},
  });
  new vm.Script(helper + "\nconst fit = createHostViewFit('hosts',changed);").runInContext(browser);
  const fit = vm.runInContext('fit',browser);
  assert.equal(fit.choose('list','wide list').view,'list');
  assert.equal(probe.inert,true);
  assert.equal(probe.attributes['aria-hidden'],'true');
  assert.ok(removedPopups > 0);
  assert.ok(removedAttributes.includes('data-menu-key'));
  assert.ok(removedAttributes.includes('id'));
  width=890; fit.checkWidth();
  assert.equal(changed,1);
  assert.equal(fit.choose('list','wide list').unavailable,true);
  assert.equal(fit.choose('list','wide list').view,'cards');
  const builtBeforeResize = built;
  width=910;
  assert.equal(fit.choose('list','wide list').view,'cards');
  width=924;
  assert.equal(fit.choose('list','wide list').view,'list');
  assert.equal(built,builtBeforeResize); // Resize reuses the inert measurement DOM.
  width=700;
  assert.equal(fit.choose('cards','wide list').unavailable,true);
  required=650;
  assert.equal(fit.choose('list','host-only or filtered list').view,'list');
  assert.equal(fit.choose('cards','host-only or filtered list').view,'cards');
  width=0;
  assert.equal(fit.choose('list','hidden host panel').unavailable,false);
  fit.checkWidth();
  width=600; fit.checkWidth();
  assert.ok(changed >= 2);
  assert.equal(fit.choose('list','shown again').view,'cards');
  const previousChanges=changed;
  required=800; fit.checkWidth(); // A content/font change can change intrinsic width.
  assert.ok(changed > previousChanges);
  assert.ok(observed.has(container));
  assert.ok(observed.has(probe.firstElementChild));
}
console.log('Both host views preserve preferences, force Cards below intrinsic list width, restore with hysteresis, and isolate measurement menus.');
