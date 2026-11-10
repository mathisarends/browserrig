/* global document, Option */
const report = JSON.parse(document.querySelector('#report-data').textContent);
const tasks = report.tasks;
const labels = {
  pass: 'Bestanden',
  fail: 'Fehlgeschlagen',
  error: 'Lauffehler',
  pending: 'Ausstehend',
  blocked: 'Infrastruktur-blockiert',
};
const nf = new Intl.NumberFormat('de-DE');
const q = (selector) => document.querySelector(selector);
const count = (status) => tasks.filter((task) => task.status === status).length;
const el = (tag, text = '', className = '') => {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
};
const number = (value) =>
  value === null || value === undefined ? '—' : nf.format(value);
const badge = (status) => el('span', labels[status] || status, `tag ${status}`);
const evaluated = count('pass') + count('fail');
const complete = evaluated + count('error');
q('#metadata').textContent =
  `${report.model} · ${report.provider} · ${report.max_steps} Schritte / ${report.timeout}s je Aufgabe · Commit ${report.revision} · ${new Date(report.generated).toLocaleString('de-DE')}`;
q('#coverage').textContent =
  `${complete}/48 ausgeführt · ${count('pending')} ausstehend · ${count('blocked')} Infrastruktur-blockiert. ${report.name}. Die Erfolgsquote bezieht sich auf die ${evaluated} fachlich bewerteten Aufgaben; Lauf-/Evaluatorfehler und nicht ausgeführte Aufgaben sind gesondert ausgewiesen. Dies ist ein Entwicklungs-Subset, kein Score auf allen 258 offiziellen Hard-Aufgaben.`;
const tokenTasks = tasks.filter((task) => task.input_tokens !== null);
const totalTokens = tokenTasks.reduce((sum, task) => sum + task.input_tokens, 0);
const totalOutput = tokenTasks.reduce(
  (sum, task) => sum + (task.output_tokens || 0),
  0,
);
const cards = [
  [
    'Erfolgsquote',
    evaluated
      ? `${((100 * count('pass')) / evaluated).toFixed(1).replace('.', ',')} %`
      : '—',
    `${count('pass')} bestanden / ${evaluated} bewertet`,
  ],
  [
    'Noch zu untersuchen',
    count('fail'),
    `${count('error')} zusätzliche Lauf-/Evaluatorfehler`,
  ],
  [
    'Abdeckung',
    `${complete}/48`,
    `${count('blocked')} blockiert · ${count('pending')} ausstehend`,
  ],
  [
    'Eingabetokens',
    number(totalTokens),
    `${number(totalOutput)} Ausgabetokens · Usage für ${tokenTasks.length}/${complete} Läufe`,
  ],
  [
    'Gesamtdauer',
    `${Math.round(tasks.reduce((sum, task) => sum + (task.record?.seconds || 0), 0) / 60)} min`,
    'Agent + Website-Reset + Login + Evaluator',
  ],
];
const traceTasks = tasks.filter((task) => task.record?.session_id);
const traceCount = (coverage) =>
  traceTasks.filter((task) => task.metrics.trace_coverage === coverage).length;
cards.push([
  'Trace-Abdeckung',
  `${traceCount('complete')}/${traceTasks.length}`,
  `${traceCount('partial')} teilweise · ${traceCount('missing')} fehlen · ${traceCount('unknown')} ungeprüft`,
]);
cards.forEach(([label, value, subtitle]) => {
  const card = el('div', '', 'card');
  card.append(el('div', label, 'label'), el('strong', value), el('small', subtitle));
  q('#cards').append(card);
});
const unique = (values) => [...new Set(values)].sort();
const patternNames = unique(tasks.flatMap((task) => task.patterns));
unique(tasks.flatMap((task) => task.sites)).forEach((site) =>
  q('#site').append(new Option(site, site)),
);
patternNames.forEach((pattern) => q('#pattern').append(new Option(pattern, pattern)));
const showPattern = (name) => {
  q('#pattern').value = name;
  renderTasks();
  q('#tasks').scrollIntoView({behavior: 'smooth', block: 'start'});
};
const patternRows = patternNames
  .map((name) => {
    const seen = tasks.filter((task) => task.patterns.includes(name));
    const scored = seen.filter((task) => ['pass', 'fail'].includes(task.status));
    const passed = scored.filter((task) => task.status === 'pass').length;
    const names = new Set(report.pattern_tools?.[name] || []);
    const calls = seen
      .flatMap((task) => task.tools)
      .filter((tool) => names.has(tool.name));
    return {
      name,
      seen: seen.length,
      scored: scored.length,
      passed,
      errors: calls.filter((tool) => tool.error).length,
      calls: calls.length,
      rate: scored.length ? passed / scored.length : 0,
    };
  })
  .sort((a, b) => a.rate - b.rate || b.scored - a.scored);
patternRows.forEach((pattern) => {
  const row = el('div', '', 'pattern');
  const name = el('div');
  const button = el('button', pattern.name);
  button.addEventListener('click', () => showPattern(pattern.name));
  name.append(
    button,
    el(
      'small',
      `${pattern.seen} Aufgaben · ${pattern.errors}/${pattern.calls} Toolfehler`,
    ),
  );
  const bar = el('div', '', 'bar');
  const fill = el('span');
  fill.style.width = `${pattern.rate * 100}%`;
  bar.append(fill);
  row.append(
    name,
    bar,
    el(
      'div',
      `${pattern.passed}/${pattern.scored} · ${Math.round(pattern.rate * 100)} %`,
      'rate',
    ),
  );
  q('#patterns').append(row);
});
if (!patternRows.length) {
  q('#patterns').append(
    el('p', 'Noch keine ausgewerteten Tool-Verläufe vorhanden.', 'empty'),
  );
}
const categories = new Map();
tasks.forEach((task) =>
  task.findings.forEach((finding) => {
    const group = categories.get(finding.category) || {
      ...finding,
      ids: [],
      failures: 0,
    };
    group.ids.push(task.task_id);
    group.failures += Number(['fail', 'error'].includes(task.status));
    categories.set(finding.category, group);
  }),
);
const findingGroups = [...categories.values()].sort(
  (a, b) =>
    Number(b.source === 'Trace-Review') - Number(a.source === 'Trace-Review') ||
    b.failures - a.failures ||
    b.ids.length - a.ids.length,
);
findingGroups.forEach((finding, index) => {
  const card = el('div', '', 'finding');
  if (index >= 5) {
    card.hidden = true;
    card.classList.add('extra-finding');
  }
  card.append(
    el('h4', finding.title),
    el('span', finding.confidence, 'tag'),
    el('span', finding.source || 'Regel', 'tag'),
    el('span', `${finding.ids.length} Aufgaben`, 'tag'),
    el('p', finding.fix),
  );
  const links = el('div');
  finding.ids.slice(0, 12).forEach((id) => {
    const button = taskLink(id);
    links.append(button, document.createTextNode(' '));
  });
  card.append(links);
  q('#findings').append(card);
});
if (findingGroups.length > 5) {
  const more = el(
    'button',
    `Weitere ${findingGroups.length - 5} Befundgruppen anzeigen`,
    'button',
  );
  more.addEventListener('click', () => {
    document.querySelectorAll('.extra-finding').forEach((node) => {
      node.hidden = false;
    });
    more.remove();
  });
  q('#findings').append(more);
}
if (!findingGroups.length) {
  q('#findings').append(
    el(
      'p',
      'Bisher keine diagnostizierten Auffälligkeiten. Erfolgreiche Läufe bleiben zur Effizienzanalyse einzeln einsehbar.',
      'empty',
    ),
  );
}
function taskLink(id) {
  const task = tasks.find((item) => item.task_id === id);
  const button = el('button', `#${id}`, 'button');
  button.addEventListener('click', () => showTask(task));
  return button;
}

function visibleTasks() {
  const query = q('#search').value.toLowerCase();
  return tasks
    .filter((task) => {
      const text =
        `${task.task_id} ${task.intent} ${task.record?.error || ''} ${task.findings.map((finding) => finding.title).join(' ')}`.toLowerCase();
      return (
        (!q('#status').value || task.status === q('#status').value) &&
        (!q('#site').value || task.sites.includes(q('#site').value)) &&
        (!q('#pattern').value || task.patterns.includes(q('#pattern').value)) &&
        text.includes(query)
      );
    })
    .sort(sortTasks);
}
function sortTasks(a, b) {
  const sort = q('#sort').value;
  if (sort === 'tokens') {
    return (b.input_tokens || 0) - (a.input_tokens || 0);
  }
  if (sort === 'time') {
    return (b.record?.seconds || 0) - (a.record?.seconds || 0);
  }
  if (sort === 'id') {
    return a.task_id - b.task_id;
  }
  const rank = {fail: 0, error: 1, pending: 2, pass: 3, blocked: 4};
  return rank[a.status] - rank[b.status] || a.task_id - b.task_id;
}
function renderTasks() {
  q('#tasks').replaceChildren();
  visibleTasks().forEach((task) => {
    const row = el('tr');
    const id = el('td');
    const button = el('button', `#${task.task_id}`, 'task-button');
    button.addEventListener('click', () => showTask(task));
    id.append(button);
    const status = el('td');
    status.append(badge(task.status));
    const intent = el('td', task.intent, 'task-intent');
    intent.append(el('small', `${task.sites.join(' + ')} · ${task.action}`));
    const diagnosis =
      task.findings.map((finding) => finding.title).join(' · ') || task.reason;
    if (diagnosis) {
      intent.append(el('small', diagnosis));
    }
    row.append(
      id,
      status,
      intent,
      el('td', number(task.metrics.steps), 'number'),
      el('td', number(task.input_tokens), 'number'),
      el('td', task.record ? `${Math.round(task.record.seconds)}s` : '—', 'number'),
    );
    q('#tasks').append(row);
  });
}
function disclosure(title, content) {
  const details = el('details');
  details.append(
    el('summary', title),
    el('pre', typeof content === 'string' ? content : JSON.stringify(content, null, 2)),
  );
  return details;
}
function showTask(task) {
  q('#detail-title').textContent = `Aufgabe #${task.task_id}`;
  const body = q('#detail-body');
  body.replaceChildren(
    badge(task.status),
    el('span', `${task.sites.join(' + ')} · ${task.action}`, 'tag'),
    el('p', task.intent),
  );
  if (task.reason) {
    body.append(el('p', task.reason, 'notice'));
  }
  const record = task.record;
  if (record) {
    body.append(
      el(
        'p',
        `${Math.round(record.seconds)}s · ${number(task.input_tokens)} Tokens in / ${number(task.output_tokens)} out · ${number(task.metrics.steps)} Modellschritte · Stop: ${record.stop_reason || '—'}`,
      ),
    );
  }
  const links = el('div', '', 'links');
  Object.entries(task.links).forEach(([name, href]) => {
    const link = el('a', name, 'button');
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener';
    links.append(link);
  });
  body.append(links);
  if (task.trace_id) {
    body.append(
      el('pre', `Phoenix trace_id: ${task.trace_id}\nsession_id: ${record.session_id}`),
    );
  }
  if (task.trace_error) {
    body.append(el('p', `Trace-Hinweis: ${task.trace_error}`, 'notice'));
  }
  if (task.findings.length) {
    body.append(el('h3', 'Belege und nächste Schritte'));
  }
  task.findings.forEach((finding) => {
    const card = el('div', '', 'finding');
    card.append(
      el('h4', finding.title),
      el('span', finding.confidence, 'tag'),
      el('span', finding.source || 'Regel', 'tag'),
      el('pre', finding.evidence.join('\n\n')),
      el('p', finding.fix),
    );
    body.append(card);
  });
  if (record?.error) {
    body.append(disclosure(`Lauffehler · Phase ${record.error_phase}`, record.error));
  }
  if (Object.keys(task.grade).length) {
    body.append(
      disclosure('Offizielle Evaluator-Assertions: erwartet / tatsächlich', task.grade),
    );
  }
  if (record?.answer) {
    body.append(disclosure('Strukturierte Agentenantwort', record.answer));
  }
  if (task.requests?.length) {
    body.append(
      disclosure('Gesendete Änderungsrequests und Formularfelder', task.requests),
    );
  }
  if (task.documents?.length) {
    const trail = task.documents
      .map(
        (visit) =>
          `${visit.time} · ${visit.method} ${visit.status} · ${visit.title}\n${visit.url}`,
      )
      .join('\n\n');
    body.append(
      disclosure(
        `Geladene HTML-Dokumente / Navigationsverlauf (${task.documents.length})`,
        trail,
      ),
    );
  }
  if (task.tools.length) {
    body.append(el('h3', 'Tatsächlicher Tool-Verlauf'));
  }
  const timeline = el('ol', '', 'timeline');
  task.tools.forEach((tool) => {
    const item = el('li', '', tool.error ? 'failed' : '');
    item.append(
      el('strong', `${tool.name}${tool.error ? ' · FEHLER' : ''}`),
      el('pre', JSON.stringify(tool.args)),
      el('pre', tool.preview),
    );
    timeline.append(item);
  });
  body.append(timeline);
  if (task.metrics.steps_detail?.length) {
    body.append(el('h3', 'Kontext pro Modellschritt'));
  }
  const steps = el('ol', '', 'timeline');
  (task.metrics.steps_detail || []).forEach((step) => {
    const item = el('li');
    item.append(
      el(
        'strong',
        `Schritt ${step.step} · ${number(step.prompt)} Prompt-Tokens · ${step.calls.join(', ') || 'Antwort'}`,
      ),
      el(
        'pre',
        `Neue Kontextzeichen: ${JSON.stringify(step.added)}\nNicht gecachte Tokens: ${number(step.uncached)}`,
      ),
    );
    steps.append(item);
  });
  body.append(steps);
  q('#detail').showModal();
  q('#detail').scrollTop = 0;
}
q('#close').addEventListener('click', () => q('#detail').close());
['#search', '#status', '#site', '#pattern', '#sort'].forEach((selector) =>
  q(selector).addEventListener('input', renderTasks),
);
q('#reset').addEventListener('click', () => {
  ['#search', '#status', '#site', '#pattern'].forEach((selector) => {
    q(selector).value = '';
  });
  q('#sort').value = 'status';
  renderTasks();
});
q('#footnote').textContent =
  `Datenstand: ${report.generated}. SHA-256: ${report.dataset_sha256}. ${report.runs.length} kompatible Laufdateien. Kein LLM-Judge und keine zusätzlichen Modellaufrufe für diesen Bericht. Muster-Raten sind Aufgaben-Raten; konkrete Toolfehler stehen im Verlauf. Wiederholte Toolargumente sind beobachtete Wiederholungen, nicht automatisch bewiesene Schleifen. Tokenwerte bei abgebrochenen Läufen können laufende Requests auslassen. Artefaktlinks funktionieren mit den benachbarten Ergebnisordnern; die Berichtansicht selbst ist eigenständig und lädt keine externen Ressourcen.`;
const setupLinks = Object.entries(report.setup_attempts || {});
if (setupLinks.length) {
  const paragraph = el(
    'p',
    `${setupLinks.length} korrigierte Setup-Anläufe ohne Agentensession oder Modellverbrauch sind separat archiviert: `,
    'footnote',
  );
  setupLinks.forEach(([name, href]) => {
    const link = el('a', name);
    link.href = href;
    paragraph.append(link, document.createTextNode(' '));
  });
  q('#footnote').after(paragraph);
}
if (Object.keys(report.runtime || {}).length) {
  q('#footnote').after(disclosure('Versionen und Reproduzierbarkeit', report.runtime));
}
const auditTasks = tasks.filter((task) =>
  task.findings.some((finding) => finding.category === 'review-benchmark-sensitivity'),
);
if (auditTasks.length) {
  q('#coverage').append(
    el(
      'strong',
      ` ${auditTasks.length} Aufgaben enthalten separat markierte Referenz-/Evaluator-Prüffälle. Der offizielle Score wird dadurch nicht verändert.`,
    ),
  );
}
renderTasks();
