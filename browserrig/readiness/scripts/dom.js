(() => {
  if (!globalThis.__browserrigStability) {
    const state = {last: performance.now()};
    state.observer = new MutationObserver(() => { state.last = performance.now(); });
    state.observer.observe(document, {childList: true, subtree: true, attributes: true, characterData: true});
    globalThis.__browserrigStability = state;
  }
  return {loaded: document.readyState !== 'loading', body: Boolean(document.body),
    quiet_ms: performance.now() - globalThis.__browserrigStability.last,
    width: innerWidth, height: innerHeight};
})()
