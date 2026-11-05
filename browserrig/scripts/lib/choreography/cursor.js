function createChoreographyCursor(ui) {
  const cursor = ui.node('cursor');
  const icon = ui.node('cursor-icon');
  const badge = ui.node('cursor-name');
  const trail = ui.node('trail').querySelector('path');
  const activities = new Map();
  let point = [0, 0];
  let style = 'default';
  let nativeStyle = 'default';
  let browserControl = false;
  let route = 0;
  let scroll = 0;
  let scrolling = false;
  const paths = {
    default: 'M0 0 L1 22 L6.5 16.5 L11 26 L14.5 24 L10 14.5 L18 13 Z',
    pointer:
      'M0 13 V0 C0 -3.5 4 -3.5 4 0 V10 C4 6 8 6 8 10 V11 C8 8 12 8 12 12 C12 9 17 10 17 14 V21 C17 27 14 29 9 29 H6 C3 29 1 26 -1 23 L-6 17 C-8 14 -5 12 -3 14 Z',
    text: 'M-5 -11 H-1 V11 H-5 V12.5 H5 V11 H1 V-11 H5 V-12.5 H-5 Z',
    crosshair: 'M0 -10 V10 M-10 0 H10',
  };
  const wheel = () =>
    ui.svg(
      '<circle cx="8" cy="10" r="10" fill="var(--surface)" stroke="currentColor" stroke-width="1.5"/><g id="wheel-spokes" stroke="currentColor" stroke-width="1.5"><path d="M12 10h3M6 13l-1.5 2.5M6 7 4.5 4.5"/></g><circle cx="8" cy="10" r="2" fill="var(--foreground)"/>',
    );
  const shape = () => {
    cursor.dataset.style = style;
    if (scrolling) {
      icon.innerHTML = wheel();
      return;
    }
    const path = paths[style] || paths.default;
    icon.innerHTML = ui.svg(
      `<path d="${path}" fill="currentColor" stroke="var(--foreground)" stroke-width="1.25" stroke-linejoin="round"/>`,
    );
  };
  const label = () => {
    const values = [...activities.values()];
    let value = ui.options().name;
    if (values.includes('llm')) {
      value += ' is thinking';
    } else if (values.includes('compaction')) {
      value += ' is organizing context';
    } else if (values.includes('paused')) {
      value += ' is paused';
    }
    badge.textContent = value;
    cursor.dataset.thinking = String(values.includes('llm'));
    const width = badge.getBoundingClientRect().width;
    const left = point[0] + width + 25 > innerWidth;
    const preferred = left ? -width - 12 : 17;
    badge.style.left = `${Math.max(8 - point[0], Math.min(preferred, innerWidth - point[0] - width - 8))}px`;
    cursor.dataset.left = String(left);
    cursor.dataset.above = String(point[1] + 54 > innerHeight);
  };
  const place = (next) => {
    point = next;
    cursor.style.display = style === 'none' ? 'none' : 'block';
    cursor.style.transform = `translate(${next[0]}px, ${next[1]}px)`;
    label();
  };
  const mix = (from, to, t) =>
    from.map((value, axis) => value + (to[axis] - value) * t);
  const move = (event) => {
    const generation = ++route;
    const from = event.from_position || point;
    const to = event.to_position;
    const cp1 = event.control_point_1 || from;
    const cp2 = event.control_point_2 || to;
    const duration = ui.reduced() ? 0 : Math.max(0, event.duration || 0) * 1000;
    const started = performance.now();
    const animate = (now) => {
      if (generation !== route) {
        return;
      }
      const fraction = duration ? Math.min(1, (now - started) / duration) : 1;
      const t = fraction < 0.5 ? 4 * fraction ** 3 : 1 - (-2 * fraction + 2) ** 3 / 2;
      const first = mix(from, cp1, t);
      const middle = mix(cp1, cp2, t);
      const last = mix(cp2, to, t);
      const second = mix(first, middle, t);
      const position = mix(second, mix(middle, last, t), t);
      place(position);
      trail.setAttribute('d', `M${from} C${first} ${second} ${position}`);
      if (fraction < 1) {
        requestAnimationFrame(animate);
      } else {
        trail.setAttribute('d', '');
      }
    };
    requestAnimationFrame(animate);
  };
  const click = (event) => {
    place([event.x, event.y]);
    if (ui.reduced()) {
      return;
    }
    const ring = document.createElement('div');
    ring.className = 'click';
    Object.assign(ring.style, {left: `${event.x}px`, top: `${event.y}px`});
    ring.addEventListener('animationend', () => ring.remove(), {once: true});
    document.body.append(ring);
    icon.animate([{scale: 0.8}, {scale: 0.66}, {scale: 0.8}], {duration: 220});
  };
  const endScroll = () => {
    scrolling = false;
    scroll++;
    cursor.dataset.scrolling = 'false';
    shape();
  };
  const startScroll = (event) => {
    const generation = ++scroll;
    scrolling = true;
    place([event.x, event.y]);
    cursor.dataset.scrolling = 'true';
    const horizontal = Math.abs(event.delta_x) > Math.abs(event.delta_y);
    const forward = (horizontal ? event.delta_x : event.delta_y) > 0;
    let direction = forward ? 'down' : 'up';
    if (horizontal) {
      direction = forward ? 'right' : 'left';
    }
    ui.node('scroll-label').textContent = `Scroll ${direction}`;
    const chevron = ui.node('scroll-chevron');
    chevron.innerHTML = ui.svg(
      '<path d="m4 4 4 4 4-4m-8 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
      '0 0 16 18',
    );
    chevron.style.rotate = {down: '0deg', up: '180deg', left: '90deg', right: '-90deg'}[
      direction
    ];
    shape();
    const started = performance.now();
    const duration = Math.max(1, event.duration * 1000);
    const rotate = (now) => {
      if (generation !== scroll || ui.reduced()) {
        return;
      }
      const phase = Math.min(1, (now - started) / duration);
      const angle = (phase * (event.delta_y + event.delta_x)) / 24;
      icon
        .querySelector('#wheel-spokes')
        ?.setAttribute('transform', `rotate(${(angle * 180) / Math.PI} 8 10)`);
      if (phase < 1) {
        requestAnimationFrame(rotate);
      }
    };
    requestAnimationFrame(rotate);
    ui.later('scroll-end', endScroll, duration + 260);
  };
  const address = (event) => {
    if (event.browser_bar !== 'address') {
      return;
    }
    browserControl = true;
    style = 'text';
    shape();
    const element = ui.node('address-text');
    const box = element.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(element);
    place([
      Math.min(box.right - 4, range.getBoundingClientRect().right + 2),
      box.top + box.height / 2,
    ]);
  };
  const show = (event) => {
    label();
    switch (event.type) {
      case 'browser.cursor.moved':
      case 'browser.cursor.entered':
        move(event);
        break;
      case 'browser.cursor.state':
        route++;
        trail.setAttribute('d', '');
        if (browserControl) {
          browserControl = false;
          style = nativeStyle;
          shape();
        }
        place([event.x, event.y]);
        break;
      case 'browser.cursor.style':
        nativeStyle = event.style;
        style = browserControl ? style : nativeStyle;
        shape();
        place(point);
        break;
      case 'browser.pointer.pressed':
        click(event);
        break;
      case 'browser.scroll.started':
        startScroll(event);
        break;
      case 'browser.scrolled':
        ui.later('scroll-end', endScroll, 180);
        break;
      case 'browser.tab.pressed': {
        browserControl = true;
        style = 'pointer';
        shape();
        const target = ui.node('navigation').getBoundingClientRect();
        move({...event, to_position: [target.left + 25, target.top + 20]});
        break;
      }
      case 'browser.bar.typed':
        address(event);
        break;
      case 'browser.activity.started':
        activities.set(event.interval_id, event.kind);
        label();
        break;
      case 'browser.activity.finished':
        activities.delete(event.interval_id);
        label();
        break;
      default:
        break;
    }
  };
  shape();
  return {show, point: () => point};
}
