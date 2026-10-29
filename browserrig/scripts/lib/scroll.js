function planScroll(el, {clip = null, targetBounds = null}) {
  const root = document.scrollingElement;
  const parentFor = (node) => node.assignedSlot || node.parentElement || node.getRootNode().host;
  const closedRoots = new Map(
    (globalThis.__browserrig?.dom?.roots || []).map((shadow) => [shadow.host, shadow]),
  );
  const viewport = intersect({x: 0, y: 0, width: innerWidth, height: innerHeight}, clip);
  const containers = [];
  let pinned = false;

  function intersect(box, other) {
    if (!other) {
      return box;
    }
    const x = Math.max(box.x, other.x);
    const y = Math.max(box.y, other.y);
    return {
      x,
      y,
      width: Math.max(0, Math.min(box.x + box.width, other.x + other.width) - x),
      height: Math.max(0, Math.min(box.y + box.height, other.y + other.height) - y),
    };
  }

  function scrollable(node) {
    if (node === root) {
      return true;
    }
    const style = getComputedStyle(node);
    return (
      (/auto|scroll/.test(style.overflowY) && node.scrollHeight > node.clientHeight) ||
      (/auto|scroll/.test(style.overflowX) && node.scrollWidth > node.clientWidth)
    );
  }

  function axes(node) {
    const style = getComputedStyle(node);
    if (node !== root) {
      return {x: /auto|scroll/.test(style.overflowX), y: /auto|scroll/.test(style.overflowY)};
    }
    const body = getComputedStyle(document.body || root);
    const x = style.overflowX === 'visible' ? body.overflowX : style.overflowX;
    const y = style.overflowY === 'visible' ? body.overflowY : style.overflowY;
    return {x: !/hidden|clip/.test(x), y: !/hidden|clip/.test(y)};
  }

  function isPinned(node) {
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return (
      style.position === 'fixed' ||
      (style.position === 'sticky' &&
        ((style.top !== 'auto' && box.top <= parseFloat(style.top) + 1) ||
          (style.bottom !== 'auto' && box.bottom >= innerHeight - parseFloat(style.bottom) - 1)))
    );
  }

  function areaFor(node) {
    if (node === root) {
      return {area: viewport, scaleX: 1, scaleY: 1};
    }
    const box = node.getBoundingClientRect();
    const scaleX = box.width / (node.offsetWidth || box.width || 1);
    const scaleY = box.height / (node.offsetHeight || box.height || 1);
    return {
      area: {
        x: box.x + node.clientLeft * scaleX,
        y: box.y + node.clientTop * scaleY,
        width: node.clientWidth * scaleX,
        height: node.clientHeight * scaleY,
      },
      scaleX,
      scaleY,
    };
  }

  function comfortable(start, size, origin, span) {
    if (size >= span * 0.76) {
      return start <= origin + span / 2 && start + size >= origin + span / 2;
    }
    return start >= origin + span * 0.12 && start + size <= origin + span * 0.88;
  }

  function verticalAnchor(target, box, area) {
    const label = target.labels?.[0]?.getBoundingClientRect();
    const nearbyLabel = label && Math.abs(box.y - label.y) <= area.height * 0.25;
    const top = nearbyLabel ? Math.min(box.y, label.y) : box.y;
    const group = target.closest('fieldset,form,[role="group"]')?.getBoundingClientRect();
    if (
      group &&
      group.height <= area.height * 0.8 &&
      group.y <= box.y &&
      group.bottom >= box.bottom
    ) {
      const padding = Math.min(area.height * 0.15, (area.height - group.height) / 2);
      return Math.min(group.y - area.y - padding, top - area.y - area.height * 0.12);
    }
    return top - area.y - area.height * 0.33;
  }

  function deltas(container, target, area, scaleX, scaleY) {
    const box =
      target === el && targetBounds ? clampTarget(targetBounds) : target.getBoundingClientRect();
    const allowed = axes(container);
    let dx = 0;
    let dy = 0;
    if (allowed.x && !comfortable(box.x, box.width, area.x, area.width)) {
      dx = (box.x + box.width / 2 - area.x - area.width / 2) / scaleX;
    }
    if (allowed.y && !comfortable(box.y, box.height, area.y, area.height)) {
      dy = verticalAnchor(target, box, area) / scaleY;
    }
    dx = Math.max(
      -container.scrollLeft,
      Math.min(container.scrollWidth - container.clientWidth - container.scrollLeft, dx),
    );
    dy = Math.max(
      -container.scrollTop,
      Math.min(container.scrollHeight - container.clientHeight - container.scrollTop, dy),
    );
    const outsideX = box.x + box.width <= area.x || box.x >= area.x + area.width;
    const outsideY = box.y + box.height <= area.y || box.y >= area.y + area.height;
    return {
      dx: Math.abs(dx) < 40 && !outsideX ? 0 : dx,
      dy: Math.abs(dy) < 40 && !outsideY ? 0 : dy,
    };
  }

  function clampTarget(box) {
    const owner = el.getBoundingClientRect();
    const x = Math.max(owner.x, Math.min(owner.right - 1, box.x));
    const y = Math.max(owner.y, Math.min(owner.bottom - 1, box.y));
    return {
      x,
      y,
      width: Math.max(1, Math.min(box.width, owner.right - x)),
      height: Math.max(1, Math.min(box.height, owner.bottom - y)),
      bottom: y + Math.max(1, Math.min(box.height, owner.bottom - y)),
    };
  }

  function canMove(node, dx, dy) {
    const allowed = axes(node);
    return (
      (allowed.x && dx < 0 && node.scrollLeft > 0) ||
      (allowed.x && dx > 0 && node.scrollLeft < node.scrollWidth - node.clientWidth - 1) ||
      (allowed.y && dy < 0 && node.scrollTop > 0) ||
      (allowed.y && dy > 0 && node.scrollTop < node.scrollHeight - node.clientHeight - 1)
    );
  }

  function receiver(x, y, dx, dy) {
    let hit = document.elementFromPoint(x, y);
    let shadow = hit?.shadowRoot || closedRoots.get(hit);
    while (shadow) {
      hit = shadow.elementFromPoint(x, y);
      shadow = hit?.shadowRoot || closedRoots.get(hit);
    }
    for (let node = hit; node; node = parentFor(node)) {
      if (node.matches('iframe,frame') && node !== el) {
        return null;
      }
      if (scrollable(node) && canMove(node, dx, dy)) {
        return node;
      }
    }
    return null;
  }

  function wheelPoint(container, area, dx, dy) {
    for (const [fx, fy] of [
      [0.5, 0.5],
      [0.04, 0.04],
      [0.96, 0.04],
      [0.04, 0.96],
      [0.96, 0.96],
    ]) {
      const x = area.x + area.width * fx;
      const y = area.y + area.height * fy;
      if (receiver(x, y, dx, dy) === container) {
        return {x, y};
      }
    }
    throw new Error('ELEMENT_BLOCKED');
  }

  for (let node = parentFor(el); node; node = parentFor(node)) {
    pinned ||= isPinned(node);
    if (scrollable(node)) {
      containers.push(node);
    }
  }
  pinned ||= isPinned(el);
  if (!containers.includes(root)) {
    containers.push(root);
  }
  containers.reverse();
  let visible = viewport;
  for (let i = 0; i < containers.length; i++) {
    const container = containers[i];
    const {area, scaleX, scaleY} = areaFor(container);
    visible = intersect(visible, area);
    if ((container === root && pinned) || visible.width <= 0 || visible.height <= 0) {
      continue;
    }
    const target = containers[i + 1] || el;
    const {dx, dy} = deltas(container, target, visible, scaleX, scaleY);
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) {
      continue;
    }
    const point = wheelPoint(container, visible, dx, dy);
    return {
      ...point,
      delta_x: Math.max(-10000, Math.min(10000, dx)),
      delta_y: Math.max(-10000, Math.min(10000, dy)),
      scroll_x: container.scrollLeft,
      scroll_y: container.scrollTop,
    };
  }
  return null;
}
