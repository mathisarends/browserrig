function resolveElement(el) {
  if (!(el instanceof Element) || !el.isConnected) {
    throw new Error('STALE_ELEMENT');
  }
  if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') {
    throw new Error('ELEMENT_DISABLED');
  }
  return el;
}
