function browserrigOwnerHits({points}) {
  return points.map(([x, y]) => {
    let root = this.getRootNode();
    let target = this;
    while (root) {
      const hit = root.elementFromPoint(x, y);
      if (hit !== target) {
        return false;
      }
      target = root.host;
      root = target?.getRootNode();
    }
    return true;
  });
}
