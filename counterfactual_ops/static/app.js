const app = document.querySelector('#app');
const toast = document.querySelector('#toast');
const dialog = document.querySelector('#decision-dialog');
const decisionJson = document.querySelector('#decision-json');
const formError = document.querySelector('#form-error');

const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const label = value => String(value).replaceAll('-', ' ');
const status = value => `<span class="pill ${escapeHtml(value)}">${escapeHtml(label(value))}</span>`;
const showToast = message => {
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2600);
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}

const decisionTemplate = {
  schema: 'cfo/v1', id: 'new-replay-decision',
  objective: 'State the operational objective and success requirement',
  choices: ['enable-replay', 'repair-idempotency', 'keep-manual-recovery'],
  status_quo: 'keep-manual-recovery',
  claim: {id: 'replay-single-effect', statement: 'Replaying one logical job produces exactly one durable database-local effect under the specified schedules.', kind: 'requirement', predicate: 'exactly-one-durable-effect-per-logical-job'},
  context: {implementation: 'atomic', implementation_version: 'worker-v1', effect_type: 'database-local', identity: 'logical-job-id', retention_ticks: 10, replay_window_ticks: 9, workload: 'one-job-serial-replay', observation_horizon_ticks: 9, dependencies: {database: 'sqlite', 'transaction-mode': 'single-process-serial', clock: 'controlled-logical-ticks'}},
  challenges: ['crash-gap', 'lost-ack', 'expired-identity'],
  experiments: [
    ['normal','crash-gap','none',0,1], ['crash-gap','crash-gap','after_effect',0,2],
    ['lost-ack','lost-ack','after_commit',0,2], ['replay-at-9','expired-identity','none',9,3]
  ].map(([id, challenge, fault, delay_ticks, cost]) => ({id, challenge, fault, delay_ticks, cost, outcomes: {supported: 'enable-replay', counterexample: 'repair-idempotency', inconclusive: 'keep-manual-recovery'}, measurement: {authority: 'sqlite-effects-table', population: 1, detection_limit: 'every durable row for job-1 at end of schedule'}})),
  recovery: {abort: 'Stop further worker invocations; existing effects remain.', restore_configuration: 'Disable replay; this does not undo durable effects.', restore_data: 'Not established by this adapter.', compensate_effects: 'Not established; requires a separate decision.'}
};

function dashboard(data) {
  const counts = data.counts;
  app.innerHTML = `
    <section class="hero">
      <div><p class="eyebrow">Operational decision laboratory</p><h1>Resolve the uncertainty that could change the decision.</h1><p class="lede">Design bounded experiments, observe authoritative state, and reuse results only while their conditions still apply.</p></div>
      <button data-new>New decision</button>
    </section>
    <section class="stats">
      ${[['Decisions',counts.decisions],['Supported',counts.supported],['Counterexamples',counts.counterexamples],['Reassessment',counts.reassessment],['Open obligations',counts.open_obligations]].map(([name, value]) => `<div class="stat"><strong>${value}</strong><span>${name}</span></div>`).join('')}
    </section>
    <div class="section-head"><div><p class="eyebrow">Decision portfolio</p><h2>Evidence in context</h2></div><span class="muted">${counts.events} ledger events</span></div>
    <section class="decision-grid">
      ${data.decisions.map(item => `<a class="card" href="#/decisions/${encodeURIComponent(item.id)}"><div class="card-top"><div><h3>${escapeHtml(item.objective)}</h3><p class="muted">${escapeHtml(item.claim)}</p></div>${status(item.status)}</div><div class="meta"><span><code>${escapeHtml(item.implementation)}</code> · ${escapeHtml(item.implementation_version)}</span><span>${item.obligations} obligations →</span></div></a>`).join('') || '<div class="empty">No committed decisions found.</div>'}
    </section>`;
  document.querySelector('[data-new]')?.addEventListener('click', openDecision);
}

function obligationCards(assessment) {
  const entries = [
    ['Unresolved assumptions', assessment.unresolved_material_assumptions],
    ['Incomplete windows', assessment.incomplete_observation_windows],
    ['Changed conditions', assessment.changed_conditions],
    ['Counterexamples awaiting change', assessment.counterexamples_awaiting_change],
    ['Unexpected effects', assessment.unexpected_consequences_awaiting_review]
  ];
  return entries.filter(([, values]) => values.length).map(([name, values]) => `<div class="scope-item"><span>${escapeHtml(name)}</span><strong>${values.length}</strong></div>`).join('') || '<div class="scope-item"><span>Obligations</span><strong>None under current conditions</strong></div>';
}

async function decisionPage(id) {
  const data = await api(`/api/v1/decisions/${encodeURIComponent(id)}`);
  const {decision, assessment, experiments} = data;
  const context = decision.context;
  app.innerHTML = `
    <a class="back" href="#/">← All decisions</a>
    <section class="detail-head"><div><p class="eyebrow">${escapeHtml(data.path)}</p><h1>${escapeHtml(decision.objective)}</h1><p class="lede">${escapeHtml(decision.claim.statement)}</p></div>${status(assessment.status)}</section>
    <div class="section-head"><div><p class="eyebrow">Applicability</p><h2>Conditions of support</h2></div></div>
    <section class="scope-grid">
      ${[['Implementation',context.implementation],['Version',context.implementation_version],['Effect',context.effect_type],['Identity',context.identity],['Replay window',`${context.replay_window_ticks} ticks`],['Retention',`${context.retention_ticks} ticks`]].map(([key,value]) => `<div class="scope-item"><span>${key}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}
    </section>
    <div class="section-head"><div><p class="eyebrow">Operational view</p><h2>Open obligations</h2></div></div>
    <section class="obligation-grid">${obligationCards(assessment)}</section>
    <div class="section-head"><div><p class="eyebrow">Executable challenges</p><h2>Experiments</h2></div><button data-run-all class="quiet">Run full suite</button></div>
    <section class="experiment-list">
      ${experiments.map(experiment => `<article class="experiment"><div><h3>${escapeHtml(label(experiment.id))}</h3><p>${escapeHtml(experiment.challenge)} · ${escapeHtml(experiment.fault)} · delay ${experiment.delay_ticks}</p></div><span class="cost">cost ${experiment.cost}</span><button data-run="${escapeHtml(experiment.id)}">Run</button></article>`).join('')}
    </section>
    <div class="section-head"><div><p class="eyebrow">Append-only history</p><h2>Decision evidence</h2></div><div class="actions"><button data-hypothesis class="quiet">Add hypothesis</button><button data-unexpected class="quiet">Record unexpected effect</button></div></div>
    <section id="timeline" class="timeline"><div class="loading"><span></span></div></section>`;
  document.querySelectorAll('[data-run]').forEach(button => button.addEventListener('click', () => execute(id, {experiment: button.dataset.run}, button)));
  document.querySelector('[data-run-all]').addEventListener('click', event => execute(id, {all: true}, event.currentTarget));
  document.querySelector('[data-hypothesis]').addEventListener('click', () => recordAnnotation(id, 'hypothesis'));
  document.querySelector('[data-unexpected]').addEventListener('click', () => recordAnnotation(id, 'unexpected'));
  renderTimeline(await api(`/api/v1/events?decision=${encodeURIComponent(id)}`), decision.choices, id);
}

function eventTitle(event) {
  if (event.kind === 'plan') return `Plan ${event.data.experiment_ids.join(', ')}`;
  if (event.kind === 'result') return `${label(event.data.experiment_id)}: ${label(event.data.outcome)}`;
  if (event.kind === 'resolution') return `Resolution: ${event.data.choice}`;
  return event.data.note || label(event.kind);
}

function renderTimeline(data, choices = [], decisionId = null) {
  const timeline = document.querySelector('#timeline') || app;
  const resolvedTargets = new Set(data.events.filter(event => event.kind === 'resolution').map(event => event.data.target));
  timeline.innerHTML = data.events.map(event => {
    const resolvable = choices.length && !resolvedTargets.has(event.id) && (event.kind === 'unexpected' || (event.kind === 'result' && event.data.outcome === 'counterexample'));
    return `<article class="event"><div><span class="event-kind">${escapeHtml(event.kind)}</span><p class="muted">${new Date(event.time).toLocaleString()}</p></div><div><h3>${escapeHtml(eventTitle(event))}</h3><p class="muted mono">${escapeHtml(event.id)}</p>${event.data.explanation_status ? `<p>${status(event.data.explanation_status)}</p>` : ''}${(event.data.artifacts || []).map(ref => `<a class="artifact" href="/api/v1/artifacts/${ref}">↓ ${ref.slice(0,12)}.sqlite</a>`).join('')}${resolvable ? `<div><button class="quiet" data-resolve="${escapeHtml(event.id)}">Record decision response</button></div>` : ''}</div></article>`;
  }).join('') || '<div class="empty">No evidence recorded for this decision.</div>';
  timeline.querySelectorAll('[data-resolve]').forEach(button => button.addEventListener('click', () => resolveEvent(button.dataset.resolve, choices, decisionId)));
}

async function evidencePage() {
  const data = await api('/api/v1/events');
  app.innerHTML = `<a class="back" href="#/">← Decisions</a><section class="detail-head"><div><p class="eyebrow">Verified append-only ledger</p><h1>Evidence history</h1><p class="lede">Plans, observations, explanations, and resolutions remain visible in the order they occurred.</p></div><span class="pill unresolved">${data.events.length} events</span></section><section id="timeline" class="timeline"></section>`;
  renderTimeline(data);
}

async function execute(decision, options, button) {
  button.disabled = true;
  const old = button.textContent;
  button.textContent = 'Running…';
  try {
    const result = await api('/api/v1/runs', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({decision, ...options})});
    showToast(`Plan ${result.plan.slice(0, 8)} completed`);
    await decisionPage(decision);
  } catch (error) {
    showToast(error.message);
    button.disabled = false;
    button.textContent = old;
  }
}

async function recordAnnotation(decision, kind) {
  const events = await api(`/api/v1/events?decision=${encodeURIComponent(decision)}`);
  const plan = events.events.find(event => event.kind === 'plan');
  if (!plan) return showToast('Run an experiment plan first');
  const note = window.prompt(kind === 'unexpected' ? 'What unexpected consequence was observed?' : 'What explanation should be challenged?');
  if (!note) return;
  try {
    await api('/api/v1/annotations', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kind, target:plan.id, note})});
    showToast(kind === 'unexpected' ? 'Unexpected consequence retained' : 'Hypothesis retained as suspected');
    await decisionPage(decision);
  } catch (error) { showToast(error.message); }
}

async function resolveEvent(target, choices, decision) {
  const choice = window.prompt(`Which choice follows?\n${choices.join('\n')}`, choices[0]);
  if (!choice) return;
  const note = window.prompt('What decision or implementation response was taken?');
  if (!note) return;
  try {
    await api('/api/v1/annotations', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kind:'resolution', target, choice, note})});
    showToast('Decision response retained');
    await decisionPage(decision);
  } catch (error) { showToast(error.message); }
}

function openDecision() {
  formError.textContent = '';
  decisionJson.value = JSON.stringify(decisionTemplate, null, 2);
  dialog.showModal();
}

document.querySelector('#new-decision').addEventListener('click', openDecision);
document.querySelector('#decision-form').addEventListener('submit', async event => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  try {
    const result = await api('/api/v1/decisions', {method:'POST', headers:{'Content-Type':'application/json'}, body:decisionJson.value});
    dialog.close();
    showToast(`Saved ${result.path}; commit before running`);
    location.hash = `#/decisions/${encodeURIComponent(result.id)}`;
  } catch (error) { formError.textContent = error.message; }
});

async function route() {
  app.innerHTML = '<section class="loading"><span></span><p>Reading the evidence ledger…</p></section>';
  try {
    const parts = location.hash.slice(2).split('/').filter(Boolean);
    if (parts[0] === 'decisions' && parts[1]) await decisionPage(decodeURIComponent(parts[1]));
    else if (parts[0] === 'evidence') await evidencePage();
    else dashboard(await api('/api/v1/overview'));
  } catch (error) {
    app.innerHTML = `<section class="empty"><h2>Could not load this view</h2><p>${escapeHtml(error.message)}</p><a href="#/">Return to decisions</a></section>`;
  }
}

window.addEventListener('hashchange', route);
route();
