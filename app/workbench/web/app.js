const app = document.querySelector('#app');
const palette = document.querySelector('#palette');
const commandSearch = document.querySelector('#command-search');
const commandList = document.querySelector('#commands');
const pages = [
  ['overview', 'Overview', 'layout-dashboard', 'A view of the observation window.'],
  ['detector', 'Detector', 'scan-line', 'Understand the rules behind recorded evidence.'],
  ['traffic', 'Traffic', 'chart-no-axes-combined', 'Explore observed DNS query metadata.'],
  ['history', 'Detection history', 'history', 'Search recorded detection evidence and monitoring sessions.'],
  ['reports', 'Reports', 'file-text', 'Create and retrieve local research reports.'],
  ['settings', 'Settings & about', 'settings-2', 'Configure this local workbench.'],
];
const state = { bootstrap: null, snapshot: null, reports: [], page: 'overview', hours: 24, query: '', source: '', rule: '', flagged: '', offset: 0, limit: 50, error: '', message: '', busy: false, loading: true };
let sidebarCollapsed = false;
const preview = document.querySelector('#preview');
const previewContent = document.querySelector('#preview-content');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<img class="icon" src="./icons/${name}.svg" alt="">`;
const number = value => Number(value ?? 0).toLocaleString();
const date = value => value ? new Date(value).toLocaleString() : '—';
const duration = () => ({1:'Last hour',24:'Last 24 hours',168:'Last 7 days'}[state.hours]);
const options = (values, selected) => values.map(([value, label]) => `<option value="${esc(value)}" ${String(value) === String(selected) ? 'selected' : ''}>${esc(label)}</option>`).join('');
const periodOptions = () => options([[1,'Last hour'],[24,'Last 24 hours'],[168,'Last 7 days']], state.hours);
const button = (label, action, symbol = '', extra = '') => `<button type="button" class="button ${extra}" data-action="${action}" ${state.busy ? 'disabled' : ''}>${symbol ? icon(symbol) : ''}${label}</button>`;
const empty = (title, text) => `<div class="empty"><strong>${esc(title)}</strong>${esc(text)}</div>`;
const api = async (action, payload = {}) => {
  const response = await fetch('./api', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action,payload})});
  if (!response.ok) throw new Error(`Local bridge returned ${response.status}.`);
  const result = await response.json();
  if (!result.ok) throw new Error(result.error || 'The request failed.');
  return result.data;
};
function theme(value) {
  const selected = value || 'dark';
  document.documentElement.dataset.theme = selected === 'system' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : selected;
}
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => theme(state.bootstrap?.settings.theme));
function navigate(page) { location.hash = page; if (location.hash === `#${page}` && state.page !== page) route(); }
function route() {
  const candidate = location.hash.slice(1);
  state.page = pages.some(p => p[0] === candidate) ? candidate : 'overview';
  render();
  document.querySelector('main')?.focus({preventScroll:true});
}
window.addEventListener('hashchange', route);
function status() {
  const m = state.snapshot?.monitor || state.bootstrap?.monitor;
  return `<span class="status ${m?.running ? 'live' : ''}"><span class="status-dot"></span>${m?.running ? 'MONITORING' : 'MONITOR STOPPED'}</span>`;
}
function header() {
  const page = pages.find(p => p[0] === state.page);
  const m = state.snapshot?.monitor || state.bootstrap.monitor;
  return `<div class="page-head"><div><div class="eyebrow">DEFENSIVE WORKBENCH / ${esc(page[1])}</div><h1>${esc(page[1])}</h1><p>${esc(page[3])}</p></div><div class="actions">${status()} ${button(m.running ? 'Stop monitoring' : 'Start monitoring', m.running ? 'stop' : 'start', m.running ? 'square' : 'play', 'primary')}</div></div>`;
}
function notices() {
  const monitorError = state.snapshot?.monitor?.error || state.bootstrap?.monitor?.error;
  return `${state.error ? `<div class="notice error" role="alert"><strong>Unable to complete request.</strong> ${esc(state.error)} ${button('Retry','refresh','refresh-cw')}</div>` : ''}${monitorError ? `<div class="notice error" role="alert"><strong>Monitor error.</strong> ${esc(monitorError)}</div>` : ''}${state.message ? `<div class="notice" role="status">${esc(state.message)}</div>` : ''}`;
}
function shell(content) {
  return `<div class="shell"><aside class="sidebar"><a href="#overview" class="brand"><span class="brand-mark">D</span><span><strong>DNSMuggle</strong><small>WORKBENCH / ${esc(state.bootstrap.version)}</small></span></a><div><div class="nav-label">Workspace</div><nav class="nav" aria-label="Primary navigation">${pages.map(([id,label,ico]) => `<a href="#${id}" ${state.page === id ? 'aria-current="page"' : ''}>${icon(ico)}<span>${esc(label)}</span></a>`).join('')}</nav></div><div class="sidebar-bottom"><strong>Local by design</strong>Defensive observation only</div></aside><div class="workspace"><header class="topbar"><div class="crumb">Workspace &nbsp;/&nbsp; <span>${esc(pages.find(p => p[0] === state.page)[1])}</span></div><div class="top-actions"><button type="button" class="button search-trigger" data-action="palette">${icon('search')} <span>Search commands</span> <kbd>Ctrl K</kbd></button>${button('Refresh','refresh','refresh-cw')}</div></header><main id="main" tabindex="-1">${header()}${notices()}${content}</main></div></div>`;
}
const stat = (label,value,note) => `<div class="card stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-note">${note}</div></div>`;
function chart(s) {
  if (!s.total_queries) return empty('No observations in this window', 'Start monitoring and send DNS queries to the configured endpoint.');
  const max = Math.max(1,...s.series.map(x => x.count));
  return `<div class="chart" role="img" aria-label="Observed query counts across ${esc(duration().toLowerCase())}. ${number(s.total_queries)} queries in total.">${s.series.map(x => `<div class="bar-wrap" title="${esc(date(x.time))}: ${number(x.count)} queries"><div class="bar" style="height:${Math.max(1,x.count/max*100)}%"></div></div>`).join('')}</div><div class="chart-labels"><span>${esc(date(s.series[0]?.time))}</span><span>NOW</span></div>`;
}
function overview() {
  const s = state.snapshot, m = s.monitor;
  return `<div class="toolbar"><label class="sr-only" for="period">Observation period</label><select id="period" data-filter="hours">${periodOptions()}</select></div><div class="grid stats">${stat('Observed queries',number(s.total_queries),duration())}${stat('Flagged queries',number(s.anomalies),'Queries with recorded rule evidence')}${stat('Heuristic flag rate',s.detection_rate === null ? '—' : `${(s.detection_rate*100).toFixed(1)}%`,'Not a measure of detection accuracy')}${stat('Sources',number(s.sources.length),'Unique sources in this window')}</div><div class="grid columns"><section class="card"><div class="card-head"><div><h2>Observation volume</h2><p>Queries delivered to this listener over time</p></div><span class="tag">${esc(duration())}</span></div><div class="card-body">${chart(s)}</div></section><section class="card"><div class="card-head"><div><h2>Listener</h2><p>Local observation endpoint</p></div>${status()}</div><div class="card-body"><div class="eyebrow">CONFIGURED ADDRESS</div><p class="mono">${esc(m.host)}:${esc(m.port)}</p><p class="about-copy">The listener only sees DNS queries deliberately sent to this endpoint.</p><a class="button" href="#settings">Endpoint settings ${icon('arrow-up-right')}</a></div></section></div><div class="grid columns"><section class="card"><div class="card-head"><div><h2>Recent observations</h2><p>Newest first</p></div><a class="button" href="#traffic">View traffic ${icon('arrow-up-right')}</a></div>${observationTable(s.observations.slice(0,5),false)}</section><section class="card"><div class="card-head"><div><h2>Top sources</h2><p>By observed query count</p></div></div><div class="card-body">${s.sources.length ? `<div class="list">${s.sources.slice(0,5).map(x=>`<div class="list-item"><strong class="mono">${esc(x.source)}</strong><span class="mono">${number(x.count)}</span></div>`).join('')}</div>` : empty('No sources yet','Sources appear when queries are observed.')}</div></section></div><div class="notice"><strong>Scope & interpretation.</strong> ${esc(state.bootstrap.coverage)}</div>`;
}
function detector() {
  const counts = Object.fromEntries(state.snapshot.rule_counts.map(x=>[x.rule,x.count]));
  return `<div class="toolbar"><label class="sr-only" for="period">Observation period</label><select id="period" data-filter="hours">${periodOptions()}</select></div><div class="notice"><strong>Evidence, not a verdict.</strong> ${esc(state.bootstrap.coverage)}</div><div class="grid rule-grid">${state.bootstrap.rules.map((r,i)=>`<section class="card rule"><div class="eyebrow">RULE / 0${i+1}</div><h2>${esc(r.title)}</h2><p>${esc(r.description)}</p><div class="rule-count"><span class="big-number">${number(counts[r.id])}</span> <span class="muted">recorded alerts · ${esc(duration().toLowerCase())}</span></div><button type="button" class="button" data-rule="${esc(r.id)}">View matching traffic ${icon('arrow-up-right')}</button></section>`).join('')}</div>`;
}
function observationTable(rows, paging=true) {
  if (!rows.length) return empty('No matching observations', 'Change the filters or start monitoring to collect query metadata.') + (paging && state.offset ? `<div class="pagination"><span>End of available observations</span><button type="button" class="button" data-action="previous">Previous</button></div>` : '');
  return `<div class="table-wrap"><table><thead><tr><th>Observed</th><th>Query name</th><th>Source</th><th>Length / entropy</th><th>Evidence</th></tr></thead><tbody>${rows.map(o=>`<tr><td class="mono">${esc(date(o.timestamp))}</td><td class="mono">${esc(o.qname)}</td><td class="mono">${esc(o.source)}</td><td class="mono">${number(o.length)} / ${Number(o.entropy).toFixed(2)}</td><td>${o.alerts.length ? o.alerts.map(a=>`<span class="tag flagged" title="${esc(a.reason)}">${esc(a.rule)}</span><div class="muted">${esc(a.reason)}</div>`).join('') : `<span class="tag">${o.warning ? 'Warning; no alert' : 'No alert'}</span>`}</td></tr>`).join('')}</tbody></table></div>${paging ? `<div class="pagination"><span>Showing ${number(state.offset+1)}–${number(state.offset+rows.length)} of ${number(state.snapshot.matched)}</span><div class="actions"><button type="button" class="button" data-action="previous" ${state.offset === 0 ? 'disabled' : ''}>Previous</button><button type="button" class="button" data-action="next" ${state.offset+rows.length >= state.snapshot.matched ? 'disabled' : ''}>Next</button></div></div>` : ''}`;
}
function comparison(s) {
  if (!s.total_queries) return empty('No observations to compare', 'Change filters or start monitoring.');
  const rows = [['No recorded alert', s.total_queries - s.anomalies], ['With recorded alert', s.anomalies]];
  return `<div class="comparison" role="img" aria-label="Of ${number(s.total_queries)} matching queries, ${number(s.anomalies)} have recorded alerts and ${number(s.total_queries-s.anomalies)} have no recorded alert.">${rows.map(([label,count]) => `<div class="comparison-row"><span>${label}</span><div class="comparison-track"><div class="comparison-bar" style="width:${count/s.total_queries*100}%"></div></div><strong class="mono">${number(count)}</strong></div>`).join('')}</div><p class="muted">No recorded alert does not mean benign: detector cooldown can suppress evidence. Counts reflect the current filters.</p>`;
}
function traffic() {
  return `<div class="toolbar"><label class="sr-only" for="query">Search query name</label><input id="query" data-filter="query" type="search" maxlength="512" placeholder="Search query names" value="${esc(state.query)}"><label class="sr-only" for="source">Filter source</label><input id="source" data-filter="source" type="search" maxlength="128" placeholder="Filter source" value="${esc(state.source)}"><label class="sr-only" for="rule">Filter rule</label><select id="rule" data-filter="rule">${options([['','All rules'],['length','Length'],['entropy','Entropy'],['rate','Rate']],state.rule)}</select><label class="sr-only" for="flagged">Filter evidence</label><select id="flagged" data-filter="flagged">${options([['','All observations'],['true','With alerts'],['false','Without alerts']],state.flagged)}</select><label class="sr-only" for="period">Observation period</label><select id="period" data-filter="hours">${periodOptions()}</select>${button('Clear filters','clear')}</div><div class="notice">Filters apply to the selected time window. Warning status may be present without recorded alerts due to detector cooldown.</div><section class="card"><div class="card-head"><div><h2>Query observations</h2><p>${number(state.snapshot.matched)} matching queries · newest first</p></div></div>${observationTable(state.snapshot.observations)}</section>`;
}
function history() {
  const sessions = state.snapshot.sessions;
  return `<div class="toolbar"><label class="sr-only" for="query">Search query name</label><input id="query" data-filter="query" type="search" maxlength="512" placeholder="Search query names" value="${esc(state.query)}"><label class="sr-only" for="source">Filter source</label><input id="source" data-filter="source" type="search" maxlength="128" placeholder="Filter source" value="${esc(state.source)}"><label class="sr-only" for="rule">Filter rule</label><select id="rule" data-filter="rule">${options([['','All rules'],['length','Length'],['entropy','Entropy'],['rate','Rate']],state.rule)}</select><label class="sr-only" for="period">Observation period</label><select id="period" data-filter="hours">${periodOptions()}</select>${button('Clear filters','clear')}</div><div class="notice">Detection history contains queries with recorded rule evidence, not every potentially suspicious query.</div><section class="card"><div class="card-head"><div><h2>Detection records</h2><p>${number(state.snapshot.matched)} matching queries · newest first</p></div></div>${observationTable(state.snapshot.observations)}</section><section class="card history-sessions"><div class="card-head"><div><h2>Monitoring sessions</h2><p>Sessions intersecting ${esc(duration().toLowerCase())} · up to 50 shown</p></div></div>${sessions.length ? `<div class="table-wrap"><table><thead><tr><th>Session</th><th>Started</th><th>Stopped</th><th>Endpoint</th><th>State</th></tr></thead><tbody>${sessions.map(x=>`<tr><td class="mono">#${number(x.id)}</td><td>${esc(date(x.started_at))}</td><td>${esc(date(x.stopped_at))}</td><td class="mono">${esc(x.host)}:${esc(x.port)}</td><td><span class="tag">${x.stopped_at ? 'Ended' : 'Open'}</span></td></tr>`).join('')}</tbody></table></div>` : empty('No sessions in this window','Start the monitor to create a session.')}</section>`;
}
function reports() {
  return `<div class="grid columns"><section class="card"><div class="card-head"><div><h2>Generate report</h2><p>Based on all observations in the chosen period, not traffic filters.</p></div></div><div class="card-body"><div class="row"><div class="field"><label for="report-period">Reporting period</label><select id="report-period">${periodOptions()}</select></div><div class="field"><label for="report-format">Format</label><select id="report-format"><option value="txt">Plain text</option><option value="pdf" ${state.bootstrap.pdf_available ? '' : 'disabled'}>PDF${state.bootstrap.pdf_available ? '' : ' (unavailable)'}</option></select></div></div><p class="muted">${state.bootstrap.pdf_available ? 'Reports are saved locally in your workbench data directory.' : 'PDF generation requires ReportLab. Plain text is available.'}</p>${button('Generate report','generate','plus','primary')}</div></section><section class="card"><div class="card-head"><div><h2>Report scope</h2><p>Read before interpreting</p></div></div><div class="card-body about-copy">${esc(state.bootstrap.coverage)}</div></section></div><section class="card"><div class="card-head"><div><h2>Saved reports</h2><p>Generated on this installation</p></div></div><div class="card-body report-list">${state.reports.length ? `<div class="list">${state.reports.map(r=>`<div class="list-item"><div><strong>${esc(r.title)}</strong><span class="muted">${esc(date(r.created_at))} · ${esc(r.format.toUpperCase())} · ${number(r.total_queries)} queries · ${number(r.anomalies)} flagged</span></div><a class="button" href="./reports/${encodeURIComponent(r.id)}" download>${icon('download')} Download</a></div>`).join('')}</div>` : empty('No reports generated','Create a report to save a snapshot of the selected period.')}</div></section>`;
}
function settings() {
  const b = state.bootstrap, s = b.settings;
  return `<section class="card settings-section"><div class="card-head"><div><h2>Observation endpoint</h2><p>Stop monitoring before changing the listening address.</p></div></div><form id="settings-form" class="card-body"><div class="form-grid"><div class="field"><label for="host">Host address</label><input id="host" name="host" required value="${esc(s.host)}" spellcheck="false"><span class="muted">Numeric IPv4 or IPv6 address</span></div><div class="field"><label for="port">UDP port</label><input id="port" name="port" type="number" min="1" max="65535" required value="${esc(s.port)}"></div></div><div class="field"><label for="theme">Appearance</label><select id="theme" name="theme">${options([['dark','Dark'],['light','Light'],['system','System']],s.theme)}</select></div><div class="form-actions"><button class="button primary" type="submit" ${state.busy ? 'disabled' : ''}>Save settings</button></div></form></section><section class="card settings-section"><div class="card-head"><div><h2>About DNSMuggle</h2><p>Defensive workbench · version ${esc(b.version)}</p></div></div><div class="card-body"><div class="about-copy">${esc(b.coverage)}</div><div><div class="eyebrow">LOCAL DATA DIRECTORY</div><p class="mono">${esc(b.data_dir)}</p></div><div>${button('Open lab tools','lab','flask-conical')}</div></div></section>`;
}
function render() {
  if (!state.bootstrap) { app.innerHTML = `<div class="boot" role="${state.error ? 'alert' : 'status'}">${state.error ? `Could not connect to the local workbench: ${esc(state.error)} <button class="button" data-action="retry-bootstrap">Retry</button>` : 'Connecting to the local workbench…'}</div>`; return; }
  if (!state.snapshot) { app.innerHTML = shell(`<div class="card">${empty(state.error ? 'Unable to load observations' : 'Loading observations', state.error ? 'Use Refresh to retry.' : 'Reading the local telemetry store…')}</div>`); return; }
  const views = {overview,detector,traffic,history,reports,settings};
  app.innerHTML = shell(views[state.page]());
  const shellElement = app.querySelector('.shell');
  shellElement.classList.toggle('collapsed', sidebarCollapsed);
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'icon-button sidebar-toggle';
  toggle.dataset.action = 'toggle-sidebar';
  toggle.setAttribute('aria-label', sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
  toggle.setAttribute('aria-expanded', String(!sidebarCollapsed));
  toggle.innerHTML = icon(sidebarCollapsed ? 'panel-left-open' : 'panel-left-close');
  app.querySelector('.topbar').prepend(toggle);
  app.querySelectorAll('.nav a').forEach(link => { link.title = link.textContent.trim(); link.setAttribute('aria-label', link.textContent.trim()); });
  if (state.page === 'traffic') {
    const card = document.createElement('section');
    card.className = 'card comparison-card';
    card.innerHTML = `<div class="card-head"><div><h2>Traffic comparison</h2><p>Recorded evidence in the selected window</p></div></div><div class="card-body">${comparison(state.snapshot)}</div>`;
    app.querySelector('main .toolbar').after(card);
  }
  if (state.page === 'reports') {
    app.querySelectorAll('.report-list .list-item').forEach((item, index) => {
      const control = document.createElement('button');
      control.type = 'button'; control.className = 'button'; control.dataset.preview = state.reports[index].id;
      control.textContent = 'Preview';
      item.insertBefore(control, item.querySelector('a'));
    });
  }
}
let generation = 0;
async function refresh(showLoading = false) {
  const current = ++generation;
  if (showLoading && !state.snapshot) render();
  try {
    const filters = ['traffic','history'].includes(state.page) ? {query:state.query,source:state.source,rule:state.rule,flagged:state.page === 'history' ? true : state.flagged === '' ? null : state.flagged === 'true',offset:state.offset} : {offset:0};
    const [snapshot, reports] = await Promise.all([api('snapshot',{hours:state.hours,limit:state.limit,...filters}),api('reports')]);
    if (current !== generation) return;
    state.snapshot = snapshot; state.reports = reports; state.error = '';
  } catch (error) { if (current !== generation) return; state.error = error.message; }
  const active = document.activeElement;
  const filter = active?.dataset?.filter;
  const selection = filter && active instanceof HTMLInputElement ? [active.selectionStart, active.selectionEnd] : null;
  render();
  if (selection) {
    const input = app.querySelector(`[data-filter="${filter}"]`);
    if (input) { input.focus(); input.setSelectionRange(...selection); }
  }
}
async function bootstrap() {
  try { state.bootstrap = await api('bootstrap'); theme(state.bootstrap.settings.theme); state.error = ''; await refresh(true); }
  catch(error) { state.error = error.message; render(); }
}
async function perform(action, payload, success) {
  state.busy = true; state.error = ''; state.message = ''; render();
  try { const result = await api(action,payload); if (success) success(result); }
  catch(error) { state.error = error.message; }
  state.busy = false;
  if (!state.error) await refresh(); else render();
}
function commands() {
  const entries = [...pages.map(([id,label])=>({label:`Go to ${label}`,run:()=>navigate(id)})),{label:'Refresh data',run:()=>refresh()},{label:'Start monitoring',run:()=>perform('start_monitor',{},m=>{state.bootstrap.monitor=m;})},{label:'Stop monitoring',run:()=>perform('stop_monitor',{},m=>{state.bootstrap.monitor=m;})}];
  const filtered = entries.filter(x=>x.label.toLowerCase().includes(commandSearch.value.toLowerCase()));
  commandList.innerHTML = filtered.length ? filtered.map((x,i)=>`<button type="button" class="button" data-command="${i}">${esc(x.label)}</button>`).join('') : '<div class="empty">No matching commands.</div>';
  commandList.querySelectorAll('[data-command]').forEach(el=>el.addEventListener('click',()=>{palette.close();filtered[Number(el.dataset.command)].run();}));
}
function openPalette(){commandSearch.value='';commands();palette.showModal();commandSearch.focus();}
commandSearch.addEventListener('input',commands);
document.querySelector('[data-close-palette]').addEventListener('click',()=>palette.close());
palette.addEventListener('click',event=>{if(event.target===palette) palette.close();});
document.addEventListener('keydown',event=>{if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase()==='k'){event.preventDefault();if(!palette.open)openPalette();}});
document.querySelector('#close-preview').addEventListener('click', () => preview.close());
preview.addEventListener('click', event => { if (event.target === preview) preview.close(); });
async function showPreview(id) {
  previewContent.textContent = 'Loading report…';
  preview.showModal();
  try {
    const report = await api('report_content', {id});
    if (!preview.open) return;
    previewContent.replaceChildren();
    if (report.format === 'txt') {
      const pre = document.createElement('pre'); pre.textContent = report.text; previewContent.append(pre);
    } else {
      const description = document.createElement('p');
      description.textContent = 'PDF preview is not available in this workbench. Download the saved report to view it in your PDF reader.';
      const link = document.createElement('a'); link.className = 'button'; link.href = `./reports/${encodeURIComponent(id)}`; link.download = ''; link.textContent = 'Download PDF';
      previewContent.append(description, link);
    }
  } catch (error) { if (preview.open) previewContent.textContent = `Unable to load report: ${error.message}`; }
}
app.addEventListener('click',event=>{
  const previewButton = event.target.closest('[data-preview]');
  if (previewButton) { showPreview(Number(previewButton.dataset.preview)); return; }
  const rule = event.target.closest('[data-rule]');
  if (rule) { state.rule=rule.dataset.rule;state.offset=0;state.page='traffic';navigate('traffic');refresh();return; }
  const target = event.target.closest('[data-action]'); if(!target)return;
  const action = target.dataset.action;
  if(action==='palette')openPalette();
  else if(action==='toggle-sidebar'){sidebarCollapsed=!sidebarCollapsed;render();app.querySelector('[data-action="toggle-sidebar"]').focus();}
  else if(action==='retry-bootstrap')bootstrap();
  else if(action==='refresh')refresh();
  else if(action==='start'||action==='stop')perform(`${action}_monitor`,{},m=>{state.bootstrap.monitor=m;state.message=m.error ? '' : `Monitor ${m.running ? 'started' : 'stopped'}.`;});
  else if(action==='lab')perform('open_lab',{},()=>{state.message='Lab tools launched.';});
  else if(action==='clear'){Object.assign(state,{query:'',source:'',rule:'',flagged:'',offset:0});refresh();}
  else if(action==='next'){state.offset+=state.limit;refresh();}
  else if(action==='previous'){state.offset=Math.max(0,state.offset-state.limit);refresh();}
  else if(action==='generate'){const hours=Number(document.querySelector('#report-period').value),format=document.querySelector('#report-format').value;perform('generate_report',{hours,format},()=>{state.message='Report generated and saved locally.';});}
});
let filterTimer;
app.addEventListener('input',event=>{const key=event.target.dataset.filter;if(key==='query'||key==='source'){state[key]=event.target.value;state.offset=0;clearTimeout(filterTimer);filterTimer=setTimeout(()=>refresh(),350);}});
app.addEventListener('change',event=>{const key=event.target.dataset.filter;if(!key || key==='query'||key==='source')return;state[key]=key==='hours'?Number(event.target.value):event.target.value;state.offset=0;refresh();});
app.addEventListener('submit',event=>{if(event.target.id!=='settings-form')return;event.preventDefault();const data=new FormData(event.target);perform('save_settings',{host:data.get('host'),port:Number(data.get('port')),theme:data.get('theme')},settings=>{state.bootstrap.settings=settings;theme(settings.theme);state.message='Settings saved.';});});
window.addEventListener('hashchange',()=>{state.offset=0;refresh();});
setInterval(()=>{if(!state.busy && !palette.open && !preview.open && !['settings','reports'].includes(state.page) && !['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName))refresh();},5000);
route(); bootstrap();
