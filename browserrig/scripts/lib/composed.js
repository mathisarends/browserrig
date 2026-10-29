function parentFor(node) {
  return node.assignedSlot || node.parentElement || node.getRootNode().host;
}

function closedRootsForDocument() {
  return new Map((globalThis.__browserrig?.dom?.roots || []).map((root) => [root.host, root]));
}

function childrenFor(node, closedRoots) {
  const shadow = node.shadowRoot || closedRoots.get(node);
  if (shadow) {
    return shadow.childNodes;
  }
  if (node.localName === 'slot') {
    const assigned = node.assignedNodes({flatten: true});
    return assigned.length ? assigned : node.childNodes;
  }
  return node.childNodes;
}
