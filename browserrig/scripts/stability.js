function browserrigStability(_args) {
  globalThis.__browserrig ||= {};
  const state = (globalThis.__browserrig.stability ||= {
    last: performance.now(),
    roots: new Map(),
  });
  let loaded = true;
  let busy = false;
  let limited = false;
  let unobservedFrames = 0;
  const animations = new Set();
  const notify = () => {
    state.last = performance.now();
  };
  const visible = (node) => {
    if (!node?.getBoundingClientRect) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    const view = node.ownerDocument.defaultView;
    return (
      rect.width > 0 &&
      rect.height > 0 &&
      rect.bottom > 0 &&
      rect.right > 0 &&
      rect.top < view.innerHeight &&
      rect.left < view.innerWidth &&
      node.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
    );
  };
  const connected = (root) => {
    if (root === document) {
      return true;
    }
    if (root.host) {
      return root.host.isConnected && connected(root.ownerDocument);
    }
    try {
      const frame = root.defaultView?.frameElement;
      return Boolean(
        frame?.isConnected &&
        frame.contentDocument === root &&
        connected(frame.ownerDocument),
      );
    } catch {
      // A formerly accessible child may now navigate to another origin.
      return false;
    }
  };
  const observe = (root) => {
    if (!root || state.roots.has(root)) {
      return;
    }
    if (state.roots.size >= 64) {
      limited = true;
      return;
    }
    const observer = new MutationObserver(notify);
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    root.addEventListener('scroll', notify, true);
    state.roots.set(root, {observer, notify});
    notify();
  };
  const inspect = (node) => {
    observe(node.shadowRoot);
    if (node.localName !== 'iframe' || !visible(node)) {
      return;
    }
    const child = node.contentDocument;
    if (child) {
      observe(child);
    } else {
      unobservedFrames++;
    }
  };
  const discover = (root) => {
    const owner = root.ownerDocument || root;
    const walker = owner.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let count = 0;
    let node;
    while ((node = walker.nextNode())) {
      inspect(node);
      if (++count >= 20000) {
        limited = true;
        break;
      }
    }
  };
  const active = (animation) =>
    animation.playState === 'running' &&
    animation.effect?.getComputedTiming().iterations !== Infinity &&
    visible(animation.effect?.target);
  const inspectRoot = (root) => {
    const owner = root.ownerDocument || root;
    loaded &&= owner.readyState !== 'loading';
    busy ||= Array.from(root.querySelectorAll('[aria-busy="true"]')).some(visible);
    for (const animation of root.getAnimations?.() || []) {
      if (active(animation)) {
        animations.add(animation);
      }
    }
    // Discover roots attached without adding a host to the light DOM, too.
    discover(root);
  };

  for (const [root, entry] of state.roots) {
    if (!connected(root)) {
      entry.observer.disconnect();
      root.removeEventListener('scroll', entry.notify, true);
      state.roots.delete(root);
      notify();
    }
  }
  observe(document);
  for (const root of globalThis.__browserrig.dom?.roots || []) {
    observe(root);
  }
  for (const root of state.roots.keys()) {
    inspectRoot(root);
  }
  if (animations.size || busy) {
    notify();
  }
  return {
    loaded,
    body: Boolean(document.body),
    quiet_ms: performance.now() - state.last,
    width: innerWidth,
    height: innerHeight,
    unobserved_frames: unobservedFrames,
    animations: animations.size,
    busy,
    limited,
  };
}
