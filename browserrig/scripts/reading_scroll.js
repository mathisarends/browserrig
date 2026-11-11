function browserrigReadingScroll({operation, down = 1.6, hold = 0.25, back = 0.7}) {
  const state = (globalThis.__browserrig ||= {});
  if (operation === 'cancel') {
    state.readingSweep?.cancel();
    return false;
  }
  const node = document.scrollingElement;
  const style = node && getComputedStyle(node);
  const body = node && getComputedStyle(document.body || node);
  const overflow = style?.overflowY === 'visible' ? body?.overflowY : style?.overflowY;
  const movable =
    node &&
    !document.hidden &&
    !matchMedia('(prefers-reduced-motion: reduce)').matches &&
    !/hidden|clip/.test(overflow) &&
    node.scrollHeight > node.clientHeight + 1;
  if (operation === 'measure' || !movable) {
    return Boolean(movable);
  }
  state.readingSweep?.cancel();
  const origin = {left: node.scrollLeft, top: node.scrollTop};
  // Freeze the endpoint: lazy loading must not turn this into an endless scroll.
  const bottom = node.scrollHeight - node.clientHeight;
  const downMs = Math.max(1, down * 1000);
  const holdMs = Math.max(0, hold * 1000);
  const backMs = Math.max(1, back * 1000);
  const total = downMs + holdMs + backMs;
  return new Promise((resolve) => {
    let frame = 0;
    let deadline = 0;
    let finished = false;
    const finish = (complete = false) => {
      if (finished) {
        return;
      }
      finished = true;
      cancelAnimationFrame(frame);
      clearTimeout(deadline);
      removeEventListener('pagehide', cancel);
      document.removeEventListener('visibilitychange', hidden);
      if (node.isConnected) {
        node.scrollTo({...origin, behavior: 'instant'});
      }
      if (state.readingSweep?.cancel === cancel) {
        delete state.readingSweep;
      }
      resolve(complete);
    };
    const cancel = () => finish();
    const hidden = () => {
      if (document.hidden) {
        cancel();
      }
    };
    state.readingSweep = {cancel};
    addEventListener('pagehide', cancel, {once: true});
    document.addEventListener('visibilitychange', hidden);
    const started = performance.now();
    const ease = (value) => value * value * (3 - 2 * value);
    const tick = (now) => {
      if (finished) {
        return;
      }
      const elapsed = now - started;
      if (elapsed >= total || !node.isConnected) {
        finish(elapsed >= total);
        return;
      }
      let progress = 1;
      if (elapsed < downMs) {
        progress = ease(elapsed / downMs);
      } else if (elapsed > downMs + holdMs) {
        progress = 1 - ease((elapsed - downMs - holdMs) / backMs);
      }
      node.scrollTo({
        left: origin.left,
        top: origin.top + (bottom - origin.top) * progress,
        behavior: 'instant',
      });
      frame = requestAnimationFrame(tick);
    };
    deadline = setTimeout(cancel, total + 500);
    frame = requestAnimationFrame(tick);
  });
}
