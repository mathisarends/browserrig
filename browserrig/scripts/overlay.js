function browserrigOverlay({operation, id, visible}) {
  const state = (globalThis.__browserrig ||= {});
  const overlays = (state.overlays ||= new Map());
  state.overlayNodes ||= new WeakSet();
  if (operation === 'visibility') {
    for (const entry of overlays.values()) {
      entry.node.style.setProperty(
        'visibility',
        visible ? 'visible' : 'hidden',
        'important',
      );
    }
    // Restoration must be painted before a recording subscriber starts again.
    return new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  }
  const existing = overlays.get(id);
  if (operation === 'close') {
    existing?.node.remove();
    overlays.delete(id);
    return Promise.resolve();
  }
  const mount = () => {
    if (existing?.node.isConnected) {
      return existing.ready.then(() => false);
    }
    const node = document.createElement('iframe');
    node.setAttribute('sandbox', 'allow-scripts allow-same-origin');
    node.name = 'browserrig-overlay-' + id;
    node.setAttribute('aria-hidden', 'true');
    node.setAttribute('tabindex', '-1');
    node.inert = true;
    node.style.cssText =
      'all:initial!important;position:fixed!important;inset:0!important;' +
      'width:100%!important;height:100%!important;border:0!important;' +
      'background:transparent!important;pointer-events:none!important;' +
      'z-index:2147483647!important;color-scheme:normal!important;';
    state.overlayNodes.add(node);
    const ready = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Overlay did not load')), 2000);
      node.addEventListener(
        'load',
        () => {
          clearTimeout(timeout);
          resolve(true);
        },
        {once: true},
      );
    });
    overlays.set(id, {node, ready});
    document.documentElement.append(node);
    return ready;
  };
  return mount();
}
