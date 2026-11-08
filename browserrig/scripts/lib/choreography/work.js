function createChoreographyWork(ui) {
  const receipts = new Map();
  const activities = new Map();
  const host = ui.node('work');
  const text = (tag, value, className = '') => {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = value;
    return node;
  };
  const card = (item) => {
    const phase = ui.options().phases;
    const element = text('section', '', 'work-card');
    element.dataset.workId = item.work_id;
    element.dataset.kind = item.kind;
    element.dataset.phase = item.phase;
    const header = text('div', '', 'work-heading');
    const symbols = {
      [phase.RUNNING]: '◌',
      [phase.COMPLETED]: '✓',
      [phase.WARNING]: '!',
      [phase.FAILED]: '×',
      [phase.CANCELLED]: '−',
    };
    header.append(
      text('span', symbols[item.phase], 'work-symbol'),
      text('b', item.title),
    );
    header.append(
      text(
        'span',
        (item.phase === phase.RUNNING ? 'In progress' : item.phase) +
          (item.elapsed ? ` · ${item.elapsed.toFixed(1)} s` : ''),
        'work-phase',
      ),
    );
    element.append(header);
    if (item.detail) {
      element.append(text('p', item.detail, 'work-detail'));
    }
    if (item.preview) {
      element.append(text('p', 'Preview · first lines', 'work-caption'));
      element.append(text('pre', item.preview, 'work-preview'));
    }
    if (item.limitations?.length) {
      element.append(text('p', item.limitations.join('\n'), 'work-limitations'));
    }
    if (item.artifact_path) {
      element.append(text('p', `Saved: ${item.artifact_path}`, 'work-artifact'));
    }
    // Preview content is always text. Only owned inline screenshot images are allowed.
    if (/^data:image\/(png|jpeg|webp);base64,/.test(item.image_url || '')) {
      const image = document.createElement('img');
      image.src = item.image_url;
      image.alt = 'Captured screenshot';
      image.className = 'work-thumbnail';
      element.append(image);
    }
    return element;
  };
  const draw = () => {
    const runningPhase = ui.options().phases.RUNNING;
    const items = [...receipts.values()];
    const running = items.filter((item) => item.phase === runningPhase);
    const recent = items.filter((item) => item.phase !== runningPhase).slice(-2);
    // Keep the newest result visible even while other work remains active.
    const visible = [...recent.reverse(), ...running.slice(-3).reverse()];
    host.replaceChildren(...visible.map(card));
    if (running.length > 3) {
      host.prepend(
        text('div', `${running.length} operations in progress`, 'work-overflow'),
      );
    }
    host.dataset.visible = String(visible.length > 0);
  };
  const put = (event) => {
    const timer = `work:${event.work_id}`;
    ui.cancel(timer);
    receipts.delete(event.work_id);
    if (event.phase !== ui.options().phases.RUNNING && event.retention <= 0) {
      draw();
      return;
    }
    receipts.set(event.work_id, event);
    if (event.phase !== ui.options().phases.RUNNING) {
      ui.later(
        timer,
        () => {
          receipts.delete(event.work_id);
          draw();
        },
        event.retention * 1000,
      );
    }
    while (receipts.size > 64) {
      const ended = [...receipts].find(
        ([, item]) => item.phase !== ui.options().phases.RUNNING,
      );
      receipts.delete(ended ? ended[0] : receipts.keys().next().value);
    }
    draw();
  };
  const activity = () => {
    const labels = {
      llm: 'Thinking',
      compaction: 'Organizing context',
      paused: 'Paused',
      tool: 'Executing tool',
      readiness: 'Waiting for page readiness',
      handoff: 'Waiting for human input',
    };
    ui.node('activity-text').textContent = [...new Set(activities.values())]
      .map((kind) => labels[kind] || kind)
      .join(' · ');
    ui.panel('activity', activities.size > 0);
  };
  const show = (event) => {
    const kinds = ui.options().events;
    switch (event.type) {
      case kinds.WORK_PRESENTED:
        put(event);
        if (
          event.region &&
          !event.restoring &&
          event.target_id === ui.options().target_id &&
          event.document_id === ui.options().document_id
        ) {
          const frame = ui.node('capture-frame');
          ui.bounds(
            frame,
            event.region.x,
            event.region.y,
            event.region.width,
            event.region.height,
          );
          frame.dataset.visible = 'true';
          ui.later(
            'capture-frame',
            () => {
              frame.dataset.visible = 'false';
            },
            900,
          );
        }
        break;
      case kinds.ACTIVITY_STARTED:
        activities.set(event.interval_id, event.kind);
        activity();
        break;
      case kinds.ACTIVITY_FINISHED:
        activities.delete(event.interval_id);
        activity();
        break;
      default:
        break;
    }
  };
  const reset = () => {
    for (const id of receipts.keys()) {
      ui.cancel(`work:${id}`);
    }
    receipts.clear();
    activities.clear();
    draw();
    activity();
  };
  return {show, reset};
}
