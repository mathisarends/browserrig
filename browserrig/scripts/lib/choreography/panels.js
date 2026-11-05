function createChoreographyPanels(ui) {
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
        node.className = 'match' + (mark.index === event.active ? ' active' : '');
        ui.bounds(node, ...rect);
        return node;
      }),
    );
    ui.node('matches').replaceChildren(...nodes);
    ui.node('find-text').textContent = event.query;
    ui.node('find-count').textContent = `${event.active} / ${event.total}`;
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
  const show = (event) => {
    switch (event.type) {
      case 'browser.element.highlight':
        highlight(event);
        break;
      case 'browser.bar.typed':
        if (event.browser_bar === 'address') {
          ui.node('address-text').textContent = event.text;
          ui.panel('address', true);
          const bounds = ui.node('address').getBoundingClientRect();
          highlight({
            x: bounds.x,
            y: bounds.y,
            width: bounds.width,
            height: bounds.height,
          });
          ui.hide('address', event.key === 'Enter' ? 550 : 1800);
        } else {
          ui.node('find-text').textContent = event.text;
        }
        break;
      case 'browser.find.bar':
        ui.panel('find', event.visible);
        if (!event.visible) {
          ui.node('matches').replaceChildren();
        }
        break;
      case 'browser.find.results':
        matches(event);
        break;
      case 'browser.tab.pressed':
        tab(event);
        break;
      case 'browser.waiting':
        ui.node('status-text').textContent = `Waiting · ${event.duration.toFixed(1)} s`;
        ui.panel('status', true);
        ui.hide('status', event.duration * 1000);
        break;
      default:
        break;
    }
  };
  return {show};
}
