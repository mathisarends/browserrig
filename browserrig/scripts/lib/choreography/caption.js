function createChoreographyCaption(ui) {
  const items = new Map();
  const element = ui.node('caption');
  const icon = ui.node('caption-icon');
  const copy = ui.node('caption-copy');
  const state = ui.node('caption-state');
  let shown = '';
  let drawn = '';
  const glyphs = {
    search: 'M8.5 3.5a5 5 0 1 0 0 10a5 5 0 1 0 0-10 M12.25 12.25 16.5 16.5',
    file: 'M5 2.5h7l3 3v12H5Z M12 2.5v3h3 M7.5 10h5 M7.5 13h3.5',
    write: 'M5 2.5h7l3 3v12H5Z M12 2.5v3h3 M10 9v5.5 M7.25 11.75h5.5',
    folder:
      'M2.5 5.5a1 1 0 0 1 1-1h4l2 2h7a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1Z',
    tabs: 'M3 8h14v8.5H3Z M3 8V5.5a1 1 0 0 1 1-1h4.5L10 8',
    download: 'M10 3v9 M6.5 8.5 10 12l3.5-3.5 M4 16h12',
    code: 'M7 5 3 10l4 5 M13 5l4 5-4 5',
    camera:
      'M3 7V3h4 M13 3h4v4 M17 13v4h-4 M7 17H3v-4 M7.5 10a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0',
    back: 'M16 10H4 M9 5l-5 5 5 5',
    forward: 'M4 10h12 M11 5l5 5-5 5',
    reload: 'M16 10a6 6 0 1 1-1.8-4.3 M15.5 3v3.5H12',
    select: 'M4 6h12 M4 10h7 M4 14h7 M13.5 12.5l1.5 1.5 2.5-2.5',
    date: 'M3.5 5h13v11.5h-13Z M3.5 8.5h13 M7 3v3.5 M13 3v3.5',
    dialog: 'M3 4h14v10H9l-4 3v-3H3Z',
    wait: 'M10 3a7 7 0 1 0 0 14a7 7 0 1 0 0-14 M10 6.5V10l2.5 2',
    alert: 'M10 3.5 17.5 16.5h-15Z M10 8.5v3.5 M10 14.25v.25',
  };
  const marks = {
    completed: 'M5 10.5l3.25 3.25L15 7',
    warning: 'M10 5v6 M10 14.5v.5',
    failed: 'M6 6l8 8 M14 6l-8 8',
    cancelled: 'M6 10h8',
  };
  const glyph = (item) => {
    const action = ui.options().actions;
    const named = {
      [action.SEARCH_PAGE]: 'search',
      [action.READ_FILE]: 'file',
      [action.OPEN_FILE]: 'file',
      [action.OPEN_DOWNLOADED_FILE]: 'file',
      [action.WRITE_FILE]: 'write',
      [action.EDIT_FILE]: 'write',
      [action.LIST_FILES]: 'folder',
      [action.LIST_TABS]: 'tabs',
      [action.LIST_DOWNLOADS]: 'download',
      [action.JAVASCRIPT]: 'code',
      [action.SCREENSHOT]: 'camera',
      [action.GO_BACK]: 'back',
      [action.GO_FORWARD]: 'forward',
      [action.RELOAD]: 'reload',
      [action.SELECT]: 'select',
      [action.SELECT_OPTIONS]: 'select',
      [action.SET_DATE]: 'date',
      [action.HANDLE_DIALOG]: 'dialog',
      [action.WAIT]: 'wait',
    };
    return glyphs[named[item.kind] || 'alert'];
  };
  const path = (value) =>
    ui.svg(
      `<path d="${value}" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`,
      '0 0 20 20',
    );
  const paint = (item) => {
    icon.hidden = item.kind === ui.options().actions.READ_FILE;
    // Only owned inline screenshot thumbnails become images; all text stays text.
    const image = /^data:image\/(png|jpeg|webp);base64,/.test(item.image || '')
      ? item.image
      : '';
    const key = image || glyph(item);
    if (key !== drawn) {
      drawn = key;
      if (image) {
        const node = document.createElement('img');
        node.src = image;
        node.alt = 'Captured screenshot';
        icon.replaceChildren(node);
      } else {
        icon.innerHTML = path(key);
      }
    }
    const mark = marks[item.phase] || '';
    if (state.dataset.mark !== mark) {
      state.dataset.mark = mark;
      state.innerHTML = mark ? path(mark) : '';
    }
  };
  const draw = () => {
    const item = [...items.values()].pop();
    if (!item) {
      shown = '';
      ui.panel('caption', false);
      return;
    }
    if (item.id !== shown && !ui.reduced()) {
      copy.animate(
        [
          {opacity: 0, transform: 'translateY(3px)'},
          {opacity: 1, transform: 'none'},
        ],
        {duration: 200, easing: 'ease-out'},
      );
    }
    shown = item.id;
    element.dataset.workId = item.id;
    element.dataset.kind = item.kind || '';
    element.dataset.phase = item.phase;
    ui.node('caption-title').textContent = item.title;
    ui.node('caption-detail').textContent = item.detail;
    paint(item);
    ui.panel('caption', true);
  };
  // `hold` is how long the caption stays in milliseconds; null keeps it until replaced.
  const put = (item, hold) => {
    const timer = `caption:${item.id}`;
    ui.cancel(timer);
    items.delete(item.id);
    if (hold !== null && hold <= 0) {
      draw();
      return;
    }
    items.set(item.id, item);
    while (items.size > 32) {
      items.delete(items.keys().next().value);
    }
    if (hold !== null) {
      ui.later(
        timer,
        () => {
          items.delete(item.id);
          draw();
        },
        hold,
      );
    }
    draw();
  };
  const anchor = () => {
    const box = icon.getBoundingClientRect();
    return [box.left + box.width / 2, box.top + box.height / 2];
  };
  const reset = () => {
    for (const id of items.keys()) {
      ui.cancel(`caption:${id}`);
    }
    items.clear();
    draw();
  };
  return {put, anchor, reset};
}
