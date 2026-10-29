function browserrigStability(_args) {
  globalThis.__browserrig ||= {};
  if (!globalThis.__browserrig.stability) {
    const state = {last: performance.now()};
    state.observer = new MutationObserver(() => {
      state.last = performance.now();
    });
    state.observer.observe(document, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    globalThis.__browserrig.stability = state;
  }
  return {
    loaded: document.readyState !== 'loading',
    body: Boolean(document.body),
    quiet_ms: performance.now() - globalThis.__browserrig.stability.last,
    width: innerWidth,
    height: innerHeight,
  };
}
