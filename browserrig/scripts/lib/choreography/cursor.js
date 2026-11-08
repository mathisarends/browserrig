function createChoreographyCursor(ui) {
  const cursor = ui.node('cursor');
  const icon = ui.node('cursor-icon');
  const badge = ui.node('cursor-name');
  const trail = ui.node('trail').querySelector('path');
  const activities = new Map();
  // Running JavaScript by work id, with the time it started.
  const scripts = new Map();
  let point = [0, 0];
  let style = 'default';
  let nativeStyle = 'default';
  let browserControl = false;
  let route = 0;
  let scroll = 0;
  let scrolling = false;
  const paths = {
    default: 'M0 0 L1 22 L6.5 16.5 L11 26 L14.5 24 L10 14.5 L18 13 Z',
    // Hotspot at the index fingertip; rounded caps mark the folded fingers.
    pointer:
      'M-2.6 0A2.6 2.6 0 0 1 2.6 0V8.5A2.3 2.3 0 0 1 7.2 8.5V10A2.2 2.2 0 0 1 11.6 10V12A1.9 1.9 0 0 1 15.4 12V18C15.4 21.8 12.8 24 9 24H4.5C1.8 24 .2 22.8-1.2 21L-6.4 14.6A2 2 0 0 1-3.3 12.2L-2.6 13Z',
    text: 'M-5 -11 H-1 V11 H-5 V12.5 H5 V11 H1 V-11 H5 V-12.5 H-5 Z',
    crosshair: 'M0 -10 V10 M-10 0 H10',
  };
  const wheel = () =>
    ui.svg(
      '<circle cx="8" cy="10" r="10" fill="var(--surface)" stroke="currentColor" stroke-width="1.5"/><g id="wheel-spokes" stroke="currentColor" stroke-width="1.5"><path d="M12 10h3M6 13l-1.5 2.5M6 7 4.5 4.5"/></g><circle cx="8" cy="10" r="2" fill="var(--foreground)"/>',
    );
  // Curly braces around the hotspot, outlined like the arrow.
  const braces = () => {
    const sides = {
      left: 'M-5 -11C-9 -11-9 -8.5-9 -5V-2.5C-9 -.8-10.2 0-12.5 0C-10.2 0-9 .8-9 2.5V5C-9 8.5-9 11-5 11',
      right:
        'M5 -11C9 -11 9 -8.5 9 -5V-2.5C9 -.8 10.2 0 12.5 0C10.2 0 9 .8 9 2.5V5C9 8.5 9 11 5 11',
    };
    return ui.svg(
      Object.entries(sides)
        .map(
          ([side, d]) =>
            `<g class="brace" data-side="${side}" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${d}" stroke="#fff" stroke-width="4.5"/><path d="${d}" stroke="currentColor" stroke-width="2.4"/></g>`,
        )
        .join(''),
    );
  };
  const shape = () => {
    cursor.dataset.style = style;
    cursor.dataset.code = String(scripts.size > 0 && !scrolling);
    if (scrolling) {
      icon.innerHTML = wheel();
      return;
    }
    if (scripts.size) {
      icon.innerHTML = braces();
      return;
    }
    const path = paths[style] || paths.default;
    icon.innerHTML = ui.svg(
      `<path d="${path}" fill="currentColor" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>`,
    );
  };
  const label = () => {
    const values = [...activities.values()];
    const activity = ui.options().activities || {};
    let value = ui.options().name;
    if (scripts.size) {
      value = 'Executing JavaScript';
    } else if (values.includes(activity.LLM)) {
      value = 'Thinking';
    } else if (values.includes(activity.COMPACTION)) {
      value += ' is organizing context';
    } else if (values.includes(activity.PAUSED)) {
      value += ' is paused';
    } else if (values.includes(activity.HANDOFF)) {
      value += ' is waiting for you';
    }
    badge.textContent = value;
    cursor.dataset.thinking = String(values.includes(activity.LLM));
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
    const kinds = ui.options().events;
    label();
    switch (event.type) {
      case kinds.CURSOR_MOVED:
      case kinds.CURSOR_ENTERED:
        move(event);
        break;
      case kinds.CURSOR_STATE:
        route++;
        trail.setAttribute('d', '');
        if (browserControl) {
          browserControl = false;
          style = nativeStyle;
          shape();
        }
        place([event.x, event.y]);
        break;
      case kinds.CURSOR_STYLE:
        nativeStyle = event.style;
        style = browserControl ? style : nativeStyle;
        shape();
        place(point);
        break;
      case kinds.POINTER_PRESSED:
        click(event);
        break;
      case kinds.SCROLL_STARTED:
        startScroll(event);
        break;
      case kinds.SCROLLED:
        ui.later('scroll-end', endScroll, 180);
        break;
      case kinds.TAB_PRESSED: {
        browserControl = true;
        style = 'pointer';
        shape();
        const target = ui.node('navigation').getBoundingClientRect();
        move({...event, to_position: [target.left + 25, target.top + 20]});
        break;
      }
      case kinds.BAR_TYPED:
        address(event);
        break;
      case kinds.ACTIVITY_STARTED:
        activities.set(event.interval_id, event.kind);
        label();
        break;
      case kinds.ACTIVITY_FINISHED:
        activities.delete(event.interval_id);
        label();
        break;
      default:
        break;
    }
  };
  shape();
  // JavaScript finishes in milliseconds; the braces stay long enough to be seen.
  const work = (id, active) => {
    if (active) {
      ui.cancel(`script:${id}`);
      if (!scripts.has(id)) {
        scripts.set(id, performance.now());
        shape();
        label();
      }
      return;
    }
    const started = scripts.get(id);
    if (started === undefined) {
      return;
    }
    ui.later(
      `script:${id}`,
      () => {
        scripts.delete(id);
        shape();
        label();
      },
      Math.max(0, 1400 - (performance.now() - started)),
    );
  };
  const reset = () => {
    activities.clear();
    for (const id of scripts.keys()) {
      ui.cancel(`script:${id}`);
    }
    scripts.clear();
    shape();
    label();
  };
  const visible = () => cursor.style.display === 'block';
  const shake = () => {
    if (!visible() || ui.reduced()) {
      return;
    }
    icon.animate(
      [
        {translate: '0 0'},
        {translate: '-3px 0'},
        {translate: '3px 0'},
        {translate: '-2px 0'},
        {translate: '0 0'},
      ],
      {duration: 320, easing: 'ease-in-out'},
    );
  };
  return {show, reset, shake, work, visible, point: () => point};
}
