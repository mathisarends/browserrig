function (token, index, operation, value) {
  const state = globalThis.__browserrigElements;
  const el = state?.token === token ? state.nodes[index] : null;
  if (!el || !el.isConnected) throw new Error('STALE_ELEMENT');
  if (el.disabled || el.getAttribute('aria-disabled') === 'true') throw new Error('ELEMENT_DISABLED');
  if (operation === 'node') return el;
  if (operation === 'select') {
    if (el.localName !== 'select') throw new Error('NOT_A_SELECT');
    const found = Array.from(el.options).find(o => o.value === value || o.text === value);
    if (!found || found.disabled) throw new Error('OPTION_NOT_FOUND');
    el.value = found.value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return {value: el.value};
  }
  if (operation === 'set_value') {
    if (!el.matches('input,textarea')) throw new Error('NOT_EDITABLE');
    const prototype = el.localName === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    if (el.value !== value) throw new Error('INVALID_VALUE');
    return {value: el.type === 'password' ? null : el.value};
  }
  if (operation === 'focus') {
    if (!el.matches('input:not([readonly]),textarea:not([readonly]),[contenteditable="true"]')) throw new Error('NOT_EDITABLE');
    el.focus();
    if (value) {
      if (typeof el.select === 'function') el.select();
      else {
        const range = document.createRange();
        range.selectNodeContents(el);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
    return true;
  }
  const before = scrollY;
  el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  const r = el.getBoundingClientRect();
  const x = Math.max(0, r.left) + (Math.min(innerWidth, r.right) - Math.max(0, r.left)) / 2;
  const y = Math.max(0, r.top) + (Math.min(innerHeight, r.bottom) - Math.max(0, r.top)) / 2;
  const root = el.getRootNode();
  const hit = root.elementFromPoint?.(x, y) || document.elementFromPoint(x, y);
  if (!hit || !(hit === el || el.contains(hit))) throw new Error('ELEMENT_BLOCKED');
  return {x, y, scrolled: scrollY !== before};
}
