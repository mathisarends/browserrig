/* global intersect, parentFor, isRendered */
function visibleBounds(el, rect, viewport, styleFor = getComputedStyle) {
  if (!isRendered(el)) {
    return null;
  }
  let bounds = intersect(rect, viewport);
  for (let current = el; current; current = parentFor(current)) {
    const style = styleFor(current);
    if (current === el) {
      continue;
    }
    const box = current.getBoundingClientRect();
    const x = /hidden|clip|scroll|auto/.test(style.overflowX);
    const y = /hidden|clip|scroll|auto/.test(style.overflowY);
    const area = {
      x: x ? box.x : bounds.x,
      y: y ? box.y : bounds.y,
      width: x ? box.width : bounds.width,
      height: y ? box.height : bounds.height,
    };
    bounds = intersect(bounds, area);
  }
  return bounds.width > 0 && bounds.height > 0 ? bounds : null;
}

function hits(el, x, y) {
  let root = el.getRootNode();
  let target = el;
  while (root) {
    const hit = root.elementFromPoint?.(x, y);
    if (!hit || !containsComposed(target, hit)) {
      return false;
    }
    target = root.host;
    root = target?.getRootNode();
  }
  return true;
}

function containsComposed(target, hit) {
  for (let current = hit; current; current = parentFor(current)) {
    if (current === target) {
      return true;
    }
  }
  return false;
}

function pointFor(el, area = null, styleFor = getComputedStyle, aim = null) {
  const viewport = intersect(
    {x: 0, y: 0, width: innerWidth, height: innerHeight},
    area || {x: 0, y: 0, width: innerWidth, height: innerHeight},
  );
  for (const rect of el.getClientRects()) {
    const bounds = visibleBounds(el, rect, viewport, styleFor);
    if (!bounds) {
      continue;
    }
    const point = hitPoint(el, bounds, aim);
    if (point) {
      return {...point, bounds};
    }
  }
  return null;
}

// `aim` is a preferred spot as fractions of the box; covered spots fall back.
function hitPoint(el, bounds, aim = null) {
  for (const [fx, fy] of [
    ...(aim ? [aim] : []),
    [0.5, 0.5],
    [0.15, 0.15],
    [0.85, 0.15],
    [0.15, 0.85],
    [0.85, 0.85],
  ]) {
    const x = bounds.x + bounds.width * fx;
    const y = bounds.y + bounds.height * fy;
    if (hits(el, x, y)) {
      return {x, y};
    }
  }
  return null;
}
