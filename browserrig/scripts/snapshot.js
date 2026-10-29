function browserrigSnapshot({token, maxElements, maxText, clip}) {
  const nodes = [];
  const elements = [];
  const text = [];
  let textLength = 0;
  let truncated = false;
  const hints = globalThis.__browserrig?.dom;
  const closedRoots = new Map((hints?.roots || []).map((root) => [root.host, root]));
  const clean = (s, n = 300) =>
    String(s || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, n);
  const parentFor = (el) => el.assignedSlot || el.parentElement || el.getRootNode().host;
  const roles = new Set([
    'button',
    'link',
    'textbox',
    'searchbox',
    'combobox',
    'checkbox',
    'radio',
    'switch',
    'tab',
    'menuitem',
    'menuitemcheckbox',
    'menuitemradio',
    'option',
    'listbox',
    'slider',
    'spinbutton',
    'treeitem',
  ]);

  function intersect(a, b) {
    const x = Math.max(a.x, b.x);
    const y = Math.max(a.y, b.y);
    return {
      x,
      y,
      width: Math.max(0, Math.min(a.x + a.width, b.x + b.width) - x),
      height: Math.max(0, Math.min(a.y + a.height, b.y + b.height) - y),
    };
  }

  function visibleBounds(el, rect, viewport) {
    let bounds = intersect(rect, viewport);
    for (let current = el; current; current = parentFor(current)) {
      const style = getComputedStyle(current);
      if (
        style.display === 'none' ||
        style.visibility !== 'visible' ||
        Number(style.opacity) === 0 ||
        current.inert
      ) {
        return null;
      }
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

  function pointFor(el, area = null) {
    const viewport = intersect(
      {x: 0, y: 0, width: innerWidth, height: innerHeight},
      area || {x: 0, y: 0, width: innerWidth, height: innerHeight},
    );
    for (const rect of el.getClientRects()) {
      const bounds = visibleBounds(el, rect, viewport);
      if (!bounds) {
        continue;
      }
      const point = hitPoint(el, bounds);
      if (point) {
        return {...point, bounds};
      }
    }
    return null;
  }

  function renderedBounds(el) {
    const original = el.getBoundingClientRect();
    let bounds = original;
    for (let current = el; current; current = parentFor(current)) {
      const style = getComputedStyle(current);
      if (
        style.display === 'none' ||
        style.visibility !== 'visible' ||
        Number(style.opacity) === 0 ||
        current.inert
      ) {
        return null;
      }
      if (current === el) {
        continue;
      }
      const box = current.getBoundingClientRect();
      const scrollX =
        /auto|scroll/.test(style.overflowX) && current.scrollWidth > current.clientWidth;
      const scrollY =
        /auto|scroll/.test(style.overflowY) && current.scrollHeight > current.clientHeight;
      // A scrollable ancestor can reveal its descendants inside an outer clipping region.
      bounds = {
        x: scrollX ? box.x : bounds.x,
        y: scrollY ? box.y : bounds.y,
        width: scrollX ? box.width : bounds.width,
        height: scrollY ? box.height : bounds.height,
      };
      const x = /hidden|clip/.test(style.overflowX);
      const y = /hidden|clip/.test(style.overflowY);
      bounds = intersect(bounds, {
        x: x ? box.x : bounds.x,
        y: y ? box.y : bounds.y,
        width: x ? box.width : bounds.width,
        height: y ? box.height : bounds.height,
      });
    }
    return bounds.width > 0 && bounds.height > 0 && original.width > 0 && original.height > 0
      ? {x: original.x, y: original.y, width: original.width, height: original.height}
      : null;
  }

  function geometricallyVisible(el) {
    const viewport = clip || {x: 0, y: 0, width: innerWidth, height: innerHeight};
    return Array.from(el.getClientRects()).some((rect) => visibleBounds(el, rect, viewport));
  }

  function hitPoint(el, bounds) {
    for (const [fx, fy] of [
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

  function roleFor(el, type) {
    const explicit = el.getAttribute('role')?.trim().split(/\s+/)[0];
    if (explicit && explicit !== 'none' && explicit !== 'presentation') {
      return explicit;
    }
    if (el.localName === 'input') {
      return (
        {
          checkbox: 'checkbox',
          radio: 'radio',
          submit: 'button',
          button: 'button',
          reset: 'button',
          range: 'slider',
          number: 'spinbutton',
          search: 'searchbox',
        }[type] || 'textbox'
      );
    }
    return (
      {a: 'link', button: 'button', textarea: 'textbox', select: 'combobox', summary: 'button'}[
        el.localName
      ] || (el.isContentEditable ? 'textbox' : el.localName)
    );
  }

  function interactive(el, role) {
    if (el.matches('html,body,iframe,frame,input[type="hidden"]')) {
      return false;
    }
    if (
      roles.has(role) ||
      el.matches('a[href],button,input,textarea,select,summary,[draggable="true"]')
    ) {
      return true;
    }
    const editable = el.getAttribute('contenteditable');
    if (
      (editable !== null && editable !== 'false') ||
      el.tabIndex >= 0 ||
      el.hasAttribute('onclick') ||
      hints?.clickable.has(el)
    ) {
      return true;
    }
    const parent = parentFor(el);
    return (
      getComputedStyle(el).cursor === 'pointer' &&
      (!parent || getComputedStyle(parent).cursor !== 'pointer')
    );
  }

  function nameFor(el, type) {
    const labelled = (el.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .map((id) => clean(el.getRootNode().getElementById?.(id)?.textContent))
      .join(' ')
      .trim();
    const labels = Array.from(el.labels || [])
      .map((label) => label.textContent)
      .join(' ');
    let fallback = el.innerText || composedText(el) || el.title;
    if (el.localName === 'input' && ['submit', 'reset', 'button'].includes(type)) {
      fallback = el.value || {submit: 'Submit', reset: 'Reset'}[type];
    }
    return clean(
      labelled ||
        el.getAttribute('aria-label') ||
        labels ||
        el.getAttribute('alt') ||
        el.getAttribute('placeholder') ||
        fallback,
    );
  }

  function collect(el) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = roleFor(el, type);
    if (!interactive(el, role)) {
      return;
    }
    const bounds = renderedBounds(el);
    if (!bounds) {
      return;
    }
    const point = pointFor(el, clip);
    if (!point && geometricallyVisible(el)) {
      return;
    }
    const index = nodes.push(el) - 1;
    elements.push({
      index,
      in_viewport: point !== null,
      role,
      name: nameFor(el, type),
      tag: el.localName,
      input_type: type,
      value: type !== 'password' && 'value' in el ? clean(el.value, 500) : null,
      disabled: el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true',
      checked: checkedFor(el),
      draggable: Boolean(el.draggable),
      options: el.localName === 'select' ? Array.from(el.options).map((o) => clean(o.text)) : [],
      bounds: point ? point.bounds : bounds,
      x: point ? point.x : bounds.x + bounds.width / 2,
      y: point ? point.y : bounds.y + bounds.height / 2,
    });
  }

  function checkedFor(el) {
    if (el.matches('input[type="checkbox"],input[type="radio"]')) {
      return el.checked;
    }
    const value = el.getAttribute('aria-checked');
    return value === null ? null : value === 'true';
  }

  function collectText(node) {
    if (maxText === 0) {
      return;
    }
    const value = clean(node.textContent, maxText + 1);
    if (!value || node.parentElement?.closest('script,style,noscript,template')) {
      return;
    }
    const range = document.createRange();
    range.selectNodeContents(node);
    const parent = node.parentElement || node.getRootNode().host;
    const viewport = clip || {x: 0, y: 0, width: innerWidth, height: innerHeight};
    const visible = Array.from(range.getClientRects()).some((r) =>
      visibleBounds(parent, r, viewport),
    );
    if (!visible) {
      return;
    }
    const remaining = maxText - textLength - (text.length ? 1 : 0);
    if (value.length > remaining) {
      truncated = true;
    }
    if (remaining <= 0) {
      return;
    }
    const part = value.slice(0, remaining);
    text.push(part);
    textLength += part.length + (text.length > 1 ? 1 : 0);
  }

  function childrenFor(node) {
    const shadow = node.shadowRoot || closedRoots.get(node);
    if (shadow) {
      return shadow.childNodes;
    }
    if (node.localName === 'slot') {
      const assigned = node.assignedNodes({flatten: true});
      return assigned.length ? assigned : node.childNodes;
    }
    return node.childNodes;
  }

  function composedText(el) {
    const pending = [el];
    const parts = [];
    let visited = 0;
    while (pending.length && visited++ < 2000) {
      const node = pending.pop();
      if (node.nodeType === Node.TEXT_NODE) {
        parts.push(node.textContent);
      }
      const children = childrenFor(node);
      for (let i = children.length - 1; i >= 0; i--) {
        pending.push(children[i]);
      }
    }
    return parts.join(' ');
  }

  function deduplicate() {
    const collected = new Set(nodes);
    const redundant = new Set();
    for (const element of elements) {
      const node = nodes[element.index];
      const semantic =
        roles.has(element.role) || node.matches('a[href],button,input,textarea,select,summary');
      if (semantic) {
        removeContainers(node, redundant);
      }
      if (node.localName === 'label' && collected.has(node.control)) {
        redundant.add(node);
      }
    }
    return elements.filter((element) => !redundant.has(nodes[element.index]));
  }

  function removeContainers(node, redundant) {
    for (let parent = parentFor(node); parent; parent = parentFor(parent)) {
      if (
        parent.matches('div,span,section,article,li,ul,ol,nav,header,footer,main,aside') &&
        !parent.hasAttribute('role') &&
        !parent.isContentEditable &&
        !parent.draggable
      ) {
        redundant.add(parent);
      }
    }
  }

  const pending = [document.documentElement];
  const seen = new Set();
  while (pending.length && seen.size < 50000) {
    const node = pending.pop();
    if (!node || seen.has(node)) {
      continue;
    }
    seen.add(node);
    if (node.nodeType === Node.ELEMENT_NODE) {
      collect(node);
    }
    if (node.nodeType === Node.TEXT_NODE) {
      collectText(node);
    }
    const children = childrenFor(node);
    for (let i = children.length - 1; i >= 0; i--) {
      pending.push(children[i]);
    }
  }
  const unique = deduplicate();
  (globalThis.__browserrig ||= {}).elements = {token, nodes, pointFor};
  return {
    url: location.href,
    title: document.title,
    width: innerWidth,
    height: innerHeight,
    scroll_y: scrollY,
    text: text.join(' '),
    elements: maxElements === null ? unique : unique.slice(0, maxElements),
    truncated:
      truncated || pending.length > 0 || (maxElements !== null && unique.length > maxElements),
  };
}
