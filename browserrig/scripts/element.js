/* global resolveElement, pointFor, intersect, visibleBounds */
function browserrigElement({operation, value, clip = null, aim = null}) {
  const el = resolveElement(this);
  function selectOption() {
    if (el.localName !== 'select') {
      throw new Error('NOT_A_SELECT');
    }
    const found = Array.from(el.options).find(
      (o) => o.value === value || o.text === value,
    );
    if (!found || found.disabled) {
      throw new Error('OPTION_NOT_FOUND');
    }
    el.value = found.value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return {value: el.value};
  }
  function setValue() {
    if (!el.matches('input,textarea')) {
      throw new Error('NOT_EDITABLE');
    }
    const prototype =
      el.localName === 'textarea'
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    if (el.value !== value) {
      throw new Error('INVALID_VALUE');
    }
    return {value: el.type === 'password' ? null : el.value};
  }
  function focus() {
    if (!(
      el.matches('input:not([readonly]),textarea:not([readonly])') ||
      el.isContentEditable
    )) {
      throw new Error('NOT_EDITABLE');
    }
    el.focus({preventScroll: true});
    if (!value) {
      return true;
    }
    if (typeof el.select === 'function') {
      el.select();
      return true;
    }
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  }

  if (operation === 'diagnose') {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const facts =
      'display=' +
      style.display +
      ', visibility=' +
      style.visibility +
      ', pointer-events=' +
      style.pointerEvents;
    const bounds =
      'frame-local bounds=(' +
      [box.x, box.y, box.width, box.height]
        .map((value) => Math.round(value))
        .join(', ') +
      ')';
    const viewport = intersect(
      {x: 0, y: 0, width: innerWidth, height: innerHeight},
      clip,
    );
    const visible = visibleBounds(el, box, viewport);
    if (!visible) {
      return (
        'No visible target area after viewport/ancestor clipping. ' +
        bounds +
        '; ' +
        facts +
        '.'
      );
    }
    const x = visible.x + visible.width / 2;
    const y = visible.y + visible.height / 2;
    const hit = el.getRootNode().elementFromPoint(x, y);
    const hitName = hit ? '<' + hit.localName + '>' : 'no element';
    return (
      'Frame-local visible-center hit test at (' +
      Math.round(x) +
      ', ' +
      Math.round(y) +
      ') reaches ' +
      hitName +
      '; target is <' +
      el.localName +
      '>. ' +
      bounds +
      '; ' +
      facts +
      '.'
    );
  }
  if (operation === 'bounds') {
    const box = el.getBoundingClientRect();
    return {x: box.x, y: box.y, width: box.width, height: box.height};
  }
  if (operation === 'select') {
    return selectOption();
  }
  if (operation === 'set_value') {
    return setValue();
  }
  if (operation === 'focus') {
    return focus();
  }
  if (operation === 'focused') {
    const active = el.getRootNode().activeElement;
    return active === el || (el.isContentEditable && el.contains(active));
  }
  if (operation === 'text_state') {
    // Passwords, editors and non-text controls need their own value semantics.
    if (
      el.localName !== 'textarea' &&
      !(
        el.localName === 'input' &&
        ['text', 'search', 'url', 'email', 'tel'].includes(el.type)
      )
    ) {
      return null;
    }
    return {value: el.value, start: el.selectionStart, end: el.selectionEnd};
  }
  const point = pointFor(el, clip, getComputedStyle, aim);
  if (!point) {
    throw new Error('ELEMENT_BLOCKED');
  }
  const bounds = el.getBoundingClientRect();
  return {
    x: point.x,
    y: point.y,
    scrolled: false,
    bounds: {x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height},
  };
}
