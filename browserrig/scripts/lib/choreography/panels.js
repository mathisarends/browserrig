function createChoreographyPanels(ui, caption) {
  const highlight = (event) => {
    const padding = 4;
    const x = Math.max(1, event.x - padding);
    const y = Math.max(1, event.y - padding);
    const right = Math.min(innerWidth - 1, event.x + event.width + padding);
    const bottom = Math.min(innerHeight - 1, event.y + event.height + padding);
    ui.bounds(
      ui.node('highlight'),
      x,
      y,
      Math.max(0, right - x),
      Math.max(0, bottom - y),
    );
    ui.node('highlight').dataset.visible = 'true';
    ui.later(
      'highlight',
      () => {
        ui.node('highlight').dataset.visible = 'false';
      },
      1200,
    );
  };
  const matches = (event) => {
    const nodes = (event.marks || []).flatMap((mark) =>
      mark.rects.map((rect) => {
        const node = document.createElement('div');
        node.className = 'match';
        ui.bounds(node, ...rect);
        return node;
      }),
    );
    ui.node('matches').replaceChildren(...nodes);
    // Like the find marks on Chrome's scrollbar: where matches lie beyond the viewport.
    const ticks = (event.ticks || []).map((at) => {
      const tick = document.createElement('i');
      tick.style.top = `${(at * 100).toFixed(2)}%`;
      return tick;
    });
    ui.node('ticks').replaceChildren(...ticks);
    ui.node('find-text').textContent = event.query;
    ui.node('find-count').textContent = event.label;
  };
  const tab = (event) => {
    ui.node('navigation-icon').textContent =
      {open: '+', close: '×', activate: '↗'}[event.gesture] || '↗';
    ui.node('navigation-text').textContent =
      {open: 'Opening tab', close: 'Closing tab', activate: 'Switching tab'}[
        event.gesture
      ] || 'Switching tab';
    ui.panel('navigation', true);
    const bounds = ui.node('navigation').getBoundingClientRect();
    highlight({x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height});
    ui.hide('navigation', event.duration * 1000 + 700);
  };
  const icons = {
    back: 'M16 10H4 M9 5l-5 5 5 5',
    forward: 'M4 10h12 M11 5l5 5-5 5',
    reload: 'M16 10a6 6 0 1 1-1.8-4.3 M15.5 3v3.5H12',
    globe:
      'M10 3a7 7 0 1 0 0 14a7 7 0 1 0 0-14 M3 10h14 M10 3c-2.4 2.6-2.4 11.4 0 14 M10 3c2.4 2.6 2.4 11.4 0 14',
    search: 'M8.5 3.5a5 5 0 1 0 0 10a5 5 0 1 0 0-10 M12.25 12.25 16.5 16.5',
  };
  const icon = (name) =>
    ui.svg(
      `<path d="${icons[name]}" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>`,
      '0 0 20 20',
    );
  // The address bar is only the input a person would type into, like Chrome's omnibox.
  const typed = (event) => {
    const bar = ui.node('address');
    const web =
      /^[a-z][a-z0-9+.-]*:\/\//i.test(event.text) || /^[^\s]+\.[^\s]+/.test(event.text);
    ui.node('address-text').textContent = event.text;
    ui.node('address-icon').innerHTML = icon(web ? 'globe' : 'search');
    bar.dataset.submitted = String(event.key === 'Enter');
    ui.panel('address', true);
    ui.hide('address', event.key === 'Enter' ? 450 : 1800);
  };
  const host = (location) => {
    try {
      return new URL(location).host || location;
    } catch {
      return location || '';
    }
  };
  // Back, forward and reload appear as one short card in the middle of the page.
  const press = (control, location) => {
    ui.node('history-icon').innerHTML = icon(control);
    ui.node('history-title').textContent =
      {back: 'Back', forward: 'Forward', reload: 'Reload'}[control] || '';
    ui.node('history-detail').textContent = host(location);
    ui.panel('history', true);
    ui.hide('history', 900);
  };
  const show = (event) => {
    const kinds = ui.options().events;
    switch (event.type) {
      case kinds.HIGHLIGHT_ELEMENT:
        highlight(event);
        break;
      case kinds.BAR_TYPED:
        if (event.browser_bar === 'address') {
          typed(event);
        } else {
          ui.node('find-text').textContent = event.text;
        }
        break;
      case kinds.FIND_BAR:
        ui.panel('find', event.visible);
        if (!event.visible) {
          ui.node('matches').replaceChildren();
          ui.node('ticks').replaceChildren();
        }
        break;
      case kinds.FIND_RESULTS:
        matches(event);
        break;
      case kinds.TAB_PRESSED:
        tab(event);
        break;
      case kinds.WAITING:
        caption.put(
          {
            id: 'waiting',
            kind: ui.options().actions.WAIT,
            phase: ui.options().phases.RUNNING,
            title: 'Waiting',
            detail: `${event.duration.toFixed(1)} s`,
          },
          event.duration * 1000,
        );
        break;
      default:
        break;
    }
  };
  return {press, show};
}
