function createChoreographySurface() {
  const timers = new Map();
  const node = (id) => document.getElementById(id);
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const dark = matchMedia('(prefers-color-scheme: dark)');
  let options = {name: 'Browserrig', keyboard_layout: 'en', theme: 'dark'};
  const configure = (value) => {
    if (value) {
      options = {...options, ...value};
    }
    let theme = options.theme;
    if (theme === 'auto') {
      theme = dark.matches ? 'dark' : 'light';
    }
    document.documentElement.dataset.theme = theme;
  };
  dark.addEventListener('change', () => configure());
  const later = (id, callback, duration) => {
    clearTimeout(timers.get(id));
    timers.set(id, setTimeout(callback, duration));
  };
  const cancel = (id) => {
    clearTimeout(timers.get(id));
    timers.delete(id);
  };
  const panel = (id, visible) => {
    cancel(id);
    node(id).dataset.visible = String(visible);
  };
  const hide = (id, delay = 700) => later(id, () => panel(id, false), delay);
  const bounds = (element, x, y, width, height) => {
    Object.assign(element.style, {
      left: `${x}px`,
      top: `${y}px`,
      width: `${width}px`,
      height: `${height}px`,
    });
  };
  const svg = (content, box = '0 0 26 32') =>
    `<svg viewBox="${box}" fill="none" aria-hidden="true">${content}</svg>`;
  configure();
  return {
    node,
    later,
    cancel,
    panel,
    hide,
    bounds,
    svg,
    configure,
    options: () => options,
    reduced: () => motion.matches,
  };
}
