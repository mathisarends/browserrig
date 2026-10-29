/* global isRendered */
function browserrigCanvas({selector, loadingSelector}) {
  const visible = (el) => {
    if (!isRendered(el)) {
      return false;
    }
    const r = el.getBoundingClientRect();
    return (
      r.width > 0 &&
      r.height > 0 &&
      r.right > 0 &&
      r.bottom > 0 &&
      r.left < innerWidth &&
      r.top < innerHeight
    );
  };
  const loading = Array.from(document.querySelectorAll(loadingSelector)).some(visible);
  const canvases = Array.from(document.querySelectorAll(selector)).filter(visible);
  if (!canvases.length) {
    return {ready: false, reason: 'no visible canvas'};
  }
  const el = canvases.sort(
    (a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight,
  )[0];
  const r = el.getBoundingClientRect();
  const x = Math.max(0, r.left),
    y = Math.max(0, r.top);
  const width = Math.min(innerWidth, r.right) - x;
  const height = Math.min(innerHeight, r.bottom) - y;
  return {
    ready: !loading,
    reason: loading ? 'visible loading indicator' : '',
    geometry: {x, y, width, height, scale: 1},
  };
}
