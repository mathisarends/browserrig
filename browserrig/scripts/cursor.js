function browserrigCursor({x, y}) {
  const textInput =
    'textarea, input:not([type=button], [type=submit], [type=reset], [type=checkbox], ' +
    '[type=radio], [type=range], [type=color], [type=file], [type=image], [type=hidden])';
  let root = document;
  let left = x;
  let top = y;
  let hit = root.elementFromPoint(left, top);
  while (hit) {
    const inner = hit.shadowRoot?.elementFromPoint(left, top);
    if (inner && inner !== hit) {
      hit = inner;
      continue;
    }
    let nested;
    try {
      nested = hit.contentDocument ?? null;
    } catch {
      nested = null;
    }
    if (!nested) {
      break;
    }
    const rect = hit.getBoundingClientRect();
    left -= rect.left + hit.clientLeft;
    top -= rect.top + hit.clientTop;
    root = nested;
    hit = root.elementFromPoint(left, top);
  }
  if (!hit) {
    return 'default';
  }
  const view = hit.ownerDocument.defaultView ?? window;
  for (let element = hit; element;) {
    const cursor = view.getComputedStyle(element).cursor;
    if (cursor && cursor !== 'auto') {
      return cursor;
    }
    element = element.parentElement ?? element.getRootNode().host ?? null;
  }
  if (hit.isContentEditable || hit.matches(textInput)) {
    return 'text';
  }
  const inside = (rect) =>
    left >= rect.left && left <= rect.right && top >= rect.top && top <= rect.bottom;
  const range = hit.ownerDocument.createRange();
  for (const node of hit.childNodes) {
    if (node.nodeType !== Node.TEXT_NODE || !node.nodeValue.trim()) {
      continue;
    }
    range.selectNodeContents(node);
    if (Array.from(range.getClientRects()).some(inside)) {
      return 'text';
    }
  }
  return 'default';
}
