/* global planScroll */
function browserrigScroll({token, index, clip = null}) {
  const state = globalThis.__browserrig?.elements;
  const el = state?.token === token ? state.nodes[index] : null;
  if (!el?.isConnected) {
    throw new Error('STALE_ELEMENT');
  }
  if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') {
    throw new Error('ELEMENT_DISABLED');
  }
  return planScroll(el, {clip});
}
