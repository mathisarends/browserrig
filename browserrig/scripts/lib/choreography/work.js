function createChoreographyWork(ui, cursor, caption, panels) {
  // Effects play once per receipt, even when facts enrich the same receipt again.
  const played = new Set();
  const scan = ui.node('scan');
  const name = (path) => path.split(/[\\/]/).pop();
  const host = (url) => {
    try {
      return new URL(url).host || url;
    } catch {
      return url;
    }
  };
  const firstLine = (text) =>
    (text || '')
      .split('\n')
      .find((line) => line.trim())
      ?.trim() || '';
  const summary = (item) => {
    const {phases: phase, actions: action} = ui.options();
    if (item.phase === phase.FAILED || item.phase === phase.CANCELLED) {
      return firstLine(item.preview) || item.detail;
    }
    if (item.kind === action.JAVASCRIPT) {
      // A status, not the code: finished receipts carry the returned value.
      return item.detail;
    }
    if (item.kind === action.WRITE_FILE || item.kind === action.EDIT_FILE) {
      return name(item.artifact_path || item.source_path || item.detail);
    }
    const source =
      (item.source_path && name(item.source_path)) ||
      (item.kind === action.EXTRACT_CONTENT && host(item.source_url || ''));
    if (!source) {
      return item.detail;
    }
    const parts = [source];
    if (item.page_number && item.page_count) {
      parts.push(`page ${item.page_number} / ${item.page_count}`);
    }
    if (item.characters !== null && item.characters !== undefined) {
      parts.push(`${item.characters.toLocaleString('en')} characters`);
    }
    if (item.next_offset !== null && item.next_offset !== undefined) {
      parts.push('continues');
    }
    return parts.join(' · ');
  };
  const hold = (event) => {
    const phase = ui.options().phases;
    if (event.phase === phase.RUNNING) {
      return null;
    }
    const limit = event.phase === phase.FAILED ? 6 : 2.6;
    return Math.min(event.retention, limit) * 1000;
  };
  const once = (event, effect) => {
    const key = `${event.work_id}:${effect}`;
    if (played.has(key)) {
      return false;
    }
    if (played.size > 256) {
      played.clear();
    }
    played.add(key);
    return true;
  };
  const read = (event) => {
    const phase = ui.options().phases;
    if (event.phase === phase.RUNNING) {
      ui.cancel('scan');
      ui.bounds(scan, 0, 0, innerWidth, innerHeight);
      scan.dataset.partial = 'false';
      scan.dataset.state = 'scanning';
      return;
    }
    if (event.phase !== phase.COMPLETED && event.phase !== phase.WARNING) {
      scan.dataset.state = 'hidden';
      return;
    }
    if (event.region) {
      // Narrow from the whole viewport to the part that was actually read.
      const {x, y, width, height} = event.region;
      ui.bounds(scan, x, y, width, height);
      scan.dataset.partial = String(event.phase === phase.WARNING);
      scan.dataset.state = 'focus';
    }
    ui.later(
      'scan',
      () => {
        scan.dataset.state = 'hidden';
      },
      event.region ? 700 : 0,
    );
  };
  const capture = (region) => {
    const frame = ui.node('viewfinder');
    ui.bounds(frame, region.x, region.y, region.width, region.height);
    frame.animate(
      [
        {opacity: 0, transform: 'scale(1.04)'},
        {opacity: 1, transform: 'none', offset: 0.25},
        {opacity: 1, transform: 'none', offset: 0.75},
        {opacity: 0, transform: 'none'},
      ],
      {duration: 1100, easing: 'ease-out'},
    );
    frame.animate([{opacity: 0.32}, {opacity: 0}], {
      duration: 360,
      pseudoElement: '::after',
    });
  };
  const effects = (event) => {
    const {phases: phase, actions: action} = ui.options();
    const finished = event.phase === phase.COMPLETED || event.phase === phase.WARNING;
    switch (event.kind) {
      case action.EXTRACT_CONTENT:
        read(event);
        break;
      case action.SCREENSHOT:
        if (event.region && event.image_url && once(event, 'capture')) {
          capture(event.region);
        }
        break;
      case action.GO_BACK:
      case action.GO_FORWARD:
      case action.RELOAD:
        if (event.phase === phase.RUNNING && once(event, 'press')) {
          const control = {
            [action.GO_BACK]: 'back',
            [action.GO_FORWARD]: 'forward',
            [action.RELOAD]: 'reload',
          }[event.kind];
          panels.press(control, event.source_url);
        }
        break;
      case action.WRITE_FILE:
      case action.EDIT_FILE:
        if (finished && cursor.visible() && once(event, 'fly')) {
          ui.fly(cursor.point(), caption.anchor());
        }
        break;
      default:
        break;
    }
    if (event.phase === phase.FAILED && once(event, 'failed')) {
      cursor.shake();
    }
  };
  const visibleHere = (event) =>
    !event.restoring &&
    !ui.reduced() &&
    event.target_id === ui.options().target_id &&
    event.document_id === ui.options().document_id;
  // File reading and JavaScript use the cursor label; the caption is left for problems
  // and for runs it already started to show, such as before the cursor appeared.
  const captioned = new Set();
  const atCursor = (event) => {
    const {phases: phase, actions: action} = ui.options();
    if (
      ![action.JAVASCRIPT, action.READ_FILE].includes(event.kind) ||
      event.target_id !== ui.options().target_id
    ) {
      return false;
    }
    if (event.kind === action.READ_FILE) {
      cursor.reading(
        event.work_id,
        event.source_path,
        event.phase === phase.RUNNING,
        event.phase === phase.COMPLETED,
      );
    } else {
      cursor.work(event.work_id, event.phase === phase.RUNNING);
    }
    const quiet =
      !captioned.has(event.work_id) &&
      cursor.visible() &&
      event.phase !== phase.FAILED &&
      event.phase !== phase.WARNING &&
      event.phase !== phase.CANCELLED;
    if (!quiet) {
      if (captioned.size > 64) {
        captioned.clear();
      }
      captioned.add(event.work_id);
    }
    return quiet;
  };
  const show = (event) => {
    const kinds = ui.options().events;
    switch (event.type) {
      case kinds.WORK_PRESENTED:
        if (atCursor(event)) {
          break;
        }
        caption.put(
          {
            id: event.work_id,
            kind: event.kind,
            phase: event.phase,
            title: event.title,
            detail: summary(event),
            image: event.image_url,
          },
          hold(event),
        );
        if (visibleHere(event)) {
          effects(event);
        }
        break;
      case kinds.READING_SWEEP:
        if (visibleHere(event)) {
          ui.cancel('scan');
          ui.bounds(scan, 0, 0, innerWidth, innerHeight);
          scan.dataset.state = 'sweeping';
        }
        break;
      case kinds.ACTIVITY_STARTED:
      case kinds.ACTIVITY_FINISHED:
        if (event.kind === ui.options().activities.HANDOFF) {
          // The person is asked to act: the viewport edge marks that control is theirs.
          ui.node('edge').dataset.visible = String(
            event.type === kinds.ACTIVITY_STARTED,
          );
        }
        break;
      default:
        break;
    }
  };
  const reset = () => {
    caption.reset();
    ui.cancel('scan');
    scan.dataset.state = 'hidden';
    ui.node('edge').dataset.visible = 'false';
  };
  return {show, reset};
}
