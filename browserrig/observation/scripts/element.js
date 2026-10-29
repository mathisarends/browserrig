function browserrigElement(token, index, operation, value, clip = null) {
  const state = globalThis.__browserrigElements;
  const el = state?.token === token ? state.nodes[index] : null;
  if (!el || !el.isConnected) {
    throw new Error('STALE_ELEMENT');
  }
  if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') {
    throw new Error('ELEMENT_DISABLED');
  }
  function selectOption() {
    if (el.localName !== 'select') {
      throw new Error('NOT_A_SELECT');
    }
    const found = Array.from(el.options).find((o) => o.value === value || o.text === value);
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
      el.localName === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    if (el.value !== value) {
      throw new Error('INVALID_VALUE');
    }
    return {value: el.type === 'password' ? null : el.value};
  }
  function focus() {
    if (!(el.matches('input:not([readonly]),textarea:not([readonly])') || el.isContentEditable)) {
      throw new Error('NOT_EDITABLE');
    }
    el.focus();
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

  if (operation === 'node') {
    return el;
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
  const before = scrollY;
  if (value !== false) {
    el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  }
  const point = state.pointFor(el, clip);
  if (!point) {
    throw new Error('ELEMENT_BLOCKED');
  }
  const bounds = el.getBoundingClientRect();
  return {
    x: point.x,
    y: point.y,
    scrolled: scrollY !== before,
    bounds: {x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height},
  };
}
