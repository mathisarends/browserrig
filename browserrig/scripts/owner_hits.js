/* global hits */
function browserrigOwnerHits({points}) {
  return points.map(([x, y]) => hits(this, x, y));
}
