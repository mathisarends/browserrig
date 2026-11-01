/* global resolveElement, pointFor */
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
