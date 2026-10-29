function browserrigSeed({clickable}, ...nodes) {
  globalThis.__browserrig ||= {};
  globalThis.__browserrig.dom = {
    roots: Array.from(
      new Set(nodes.map((node) => node.getRootNode()).filter((root) => root.mode === 'closed')),
    ),
    clickable: new WeakSet(nodes.filter((node, index) => clickable[index])),
  };
}
