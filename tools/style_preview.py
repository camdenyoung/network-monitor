"""Local-only CSS regression fixtures; never connects to a monitoring database.

Run: python3 -m tools.style_preview --baseline main --port 18080
Open /matrix to compare the baseline HTML against the working tree in one browser.
The same deterministic fixture script populates both versions. This tests CSS and
layout, not application authorization; the ordinary dashboard/API suites test that.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index.html', 'status.html', 'login.html', 'change-password.html')
CSS = ('base.css', 'dashboard.css', 'status.css', 'auth.css')

FIXTURE = r'''
const options = new URLSearchParams(location.search);
const scenario = options.get('case');
const page = options.get('page');
const el = id => document.getElementById(id);
for(const version of document.querySelectorAll('.app-version')) version.textContent='v0.5.8 · Build 101';
const show = id => { if(el(id)) el(id).hidden = false; };
const fill = (id, html) => { if(el(id)) el(id).innerHTML = html; };
document.body.dataset.role = scenario === 'operator' ? 'operator' : scenario === 'viewer' ? 'viewer' : 'admin';
const name = scenario === 'long' ? 'Long equipment and project name to exercise wrapping of realistic deployment descriptions' : 'Event network';
for(const id of ['project','run-status']) if(el(id) && el(id).tagName !== 'SELECT') el(id).textContent = name;
for(const node of document.querySelectorAll('select')) {
  if(!node.options.length) node.add(new Option('Example reusable service', '1'));
}
for(const node of document.querySelectorAll('input:not([type=password]):not([type=checkbox]):not([type=file]):not([type=number]):not([type=datetime-local])')) node.value = 'Example';
for(const node of document.querySelectorAll('input[type=checkbox]')) node.checked = true;
if(scenario.startsWith('attention-')) document.documentElement.classList.add('issue-attention', 'issue-attention-' + scenario.slice(10));
const status = ['warning','critical','blocked','paused'].includes(scenario) ? scenario : 'healthy';
const issue = `<div class="metric"><div class="metric-header"><strong>Issue #1 · SW001 - ${name}</strong><span class="${status}">${status}</span></div><span class="issue-value">RSSI: -65 dBm</span><small>Opened today · acknowledged by Example User</small><button class="issue-action">Acknowledge</button></div>`;
for(const id of ['incidents','acknowledged-incidents','resolved-incidents','suppressed-incidents']) fill(id, issue);
const service = `<div class="metric"><div class="metric-header"><div><strong>RSSI</strong><small class="metric-status ${status}">${status}</small></div><div class="service-controls"><button>Pause</button><details class="action-menu" ${scenario==='menu'?'open':''}><summary>Actions</summary><div class="menu-buttons"><button>History</button><button>Edit</button><button>Copy to host</button></div></details></div></div><div class="metric-value">-65 dBm</div></div>`;
const host = `<article class="host-card incident-${status}"><div class="host-heading"><h2>SW001 - ${name}</h2><button>Edit alias</button></div><span class="${status}">${status}</span>${scenario==='host-only'?'':service}</article>`;
const rows = `<div class="scroll"><table class="host-list"><tbody><tr class="host-row incident-${status}"><td><h2>SW001 - ${name}</h2></td><td>${service}</td></tr></tbody></table></div>`;
for(const id of ['dashboard','devices']) {
  fill(id, scenario==='list' ? rows : host.repeat(4));
  if(el(id)) el(id).className = scenario==='list' ? '' : 'grid';
}
if(scenario !== 'anonymous') {
  for(const id of ['live-status-panel','live-host-panel','host-controls','toggle-hosts','status-logout']) show(id);
  if(el('toggle-hosts')) el('toggle-hosts').disabled = false;
  if(el('status-session-link')) el('status-session-link').textContent = 'Admin Dashboard';
}
for(const id of ['signed-in','status-session']) if(el(id)) el(id).textContent = scenario==='anonymous' ? 'Not signed in' : 'Example User · Admin';
for(const id of ['toggle-acknowledged','toggle-hosts']) if(el(id) && scenario==='long') el(id).textContent = id==='toggle-hosts' ? 'Hide host cards' : 'Hide acknowledged issues';
if(scenario==='logo') {
  show('project-logo');
  if(el('project-logo')) el('project-logo').src='data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="160" height="80"%3E%3Crect width="160" height="80" fill="teal"/%3E%3C/svg%3E';
}
if(scenario==='paused') for(const id of ['monitoring-toggle','notifications-toggle']) if(el(id)) el(id).className = id==='monitoring-toggle'?'monitoring-paused':'notifications-paused';
if(scenario==='below') for(const id of ['project-actions','deployment-actions','account-actions']) el(id)?.classList.add('controls-below');
if(scenario.startsWith('panel:')) {
  const node=el(scenario.slice(6)); if(node) { node.hidden=false; node.querySelectorAll('details').forEach(n=>n.open=true); }
}
if(scenario.startsWith('dialog:')) {
  const dialog=el(scenario.slice(7)); if(dialog) dialog.showModal();
}
if(scenario.startsWith('protocol:')) {
  const stateMode=scenario==='protocol:state';
  const kind=stateMode?'snmp':scenario.slice(9);
  if(stateMode) for(const node of document.querySelectorAll('[data-state]')) node.hidden=false;
  show('user-management-panel'); show('project-configuration');
  for(const node of document.querySelectorAll('input[name=community]')) node.disabled=kind!=='snmp';
  for(const node of document.querySelectorAll('input[name=unit]')) node.disabled=kind!=='modbus';
  for(const node of document.querySelectorAll('select[name=kind]')) node.value=kind;
  if(el('service-editor')) el('service-editor').showModal();
}
if(page==='change-password.html') show('password-form');
if(scenario==='mandatory') { if(el('password-reason')) el('password-reason').textContent='Change your temporary password before continuing.'; if(el('back-dashboard')) el('back-dashboard').hidden=true; }
else show('back-dashboard');
if(scenario==='error' && el('message')) el('message').textContent='The request could not be completed. Please check the supplied values.';
if(scenario==='toast') { show('save-toasts'); fill('save-toasts','<div class="save-toast"><div class="save-toast-content"><span class="save-toast-message">Settings updated</span><button>×</button></div><div class="save-toast-progress"></div></div>'); }
if(scenario==='hidden-hosts') { for(const id of ['live-status-panel','live-host-panel']) if(el(id)) el(id).hidden=true; }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='main')
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    before = {name: subprocess.check_output(['git', 'show', f'{args.baseline}:app/{name}'], cwd=ROOT).decode() for name in PAGES}
    cases = []
    for name in PAGES:
        scenarios = ['healthy','long','error'] if name in PAGES[2:] else [
            'healthy','warning','critical','blocked','paused','list','host-only','hidden-hosts',
            'anonymous','operator','viewer','logo','long','below','menu','toast','attention-warning','attention-critical',
        ]
        if name == 'change-password.html':
            scenarios += ['mandatory']
        if name == 'index.html':
            scenarios += ['panel:' + panel for panel in re.findall(r'<div data-admin id="([^"]+)"', before[name])]
            scenarios += ['protocol:snmp','protocol:modbus','protocol:tcp','protocol:state']
        if name in PAGES[:2]:
            scenarios += ['dialog:' + dialog for dialog in re.findall(r'<dialog id="([^"]+)"', before[name])]
        cases.extend({'page':name,'case':scenario} for scenario in scenarios)

    # Force only the authored reduced-motion media rules, without changing OS settings.
    for page in PAGES[:2]:
        for scenario in ('paused','toast','attention-warning','attention-critical','dialog:connection-lost'):
            cases.append({'page': page, 'case': scenario, 'motion': 'reduce'})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            mime = 'text/html; charset=utf-8'
            if url.path == '/matrix':
                body = (ROOT / 'tests/style_matrix.html').read_bytes()
            elif url.path == '/cases':
                body = json.dumps(cases).encode()
                mime = 'application/json'
            elif url.path.startswith('/static/css/') and url.path.rsplit('/',1)[-1] in CSS:
                body = (ROOT / 'app/static/css' / url.path.rsplit('/',1)[-1]).read_bytes()
                if parse_qs(url.query).get('motion') == ['reduce']:
                    body = body.replace(b'prefers-reduced-motion: reduce', b'min-width: 0px')
                mime = 'text/css; charset=utf-8'
            elif url.path in ('/before','/after'):
                query = parse_qs(url.query)
                name = query.get('page',[''])[0]
                if name not in PAGES:
                    self.send_error(404)
                    return
                text = before[name] if url.path == '/before' else (ROOT / 'app' / name).read_text()
                text = re.sub(r'<script>[\s\S]*?</script>', '', text)
                if query.get('motion') == ['reduce']:
                    text = text.replace('prefers-reduced-motion: reduce', 'min-width: 0px')
                    text = re.sub(r'(/static/css/[^\"?]+\.css\?v=\d+)', r'\1&motion=reduce', text)
                # Freeze animations at the same point in both documents for comparisons.
                text = text.replace('</head>', '<style>*,*::before,*::after{animation-play-state:paused!important;caret-color:transparent!important}</style></head>')
                text = text.replace('</body>', '<script>' + FIXTURE + '</script></body>')
                body = text.encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f'CSS-only before/after comparison: http://127.0.0.1:{args.port}/matrix ({len(cases)} scenarios)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
