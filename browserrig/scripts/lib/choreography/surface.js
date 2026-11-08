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
  let flight = 0;
  // A file icon arcs from one viewport point to another, as files move between places.
  const fly = (from, to, seconds = 0.45) => {
    if (motion.matches) {
      return;
    }
    const generation = ++flight;
    const control = [
      from[0] + (to[0] - from[0]) * 0.75,
      Math.max(8, Math.min(from[1], to[1]) - 48),
    ];
    const element = node('flying-file');
    const started = performance.now();
    element.style.display = 'grid';
    const animate = (now) => {
      if (generation !== flight) {
        return;
      }
      const fraction = Math.min(1, (now - started) / Math.max(1, seconds * 1000));
      const t = fraction * fraction * (3 - 2 * fraction);
      const p = from.map(
        (value, axis) =>
          (1 - t) ** 2 * value + 2 * (1 - t) * t * control[axis] + t ** 2 * to[axis],
      );
      const scale = 1 + Math.sin(t * Math.PI) * 0.2;
      element.style.transform = `translate(${p[0] - 20}px, ${p[1] - 20}px) rotate(${Math.sin(t * Math.PI) * 0.25}rad) scale(${scale})`;
      element.style.opacity = Math.min(1, fraction * 10, (1 - fraction) * 10);
      if (fraction < 1) {
        requestAnimationFrame(animate);
      } else {
        element.style.display = 'none';
      }
    };
    requestAnimationFrame(animate);
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
    fly,
    configure,
    options: () => options,
    reduced: () => motion.matches,
  };
}
