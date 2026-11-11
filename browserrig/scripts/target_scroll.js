/* global resolveElement */
function browserrigTargetScroll({deltaX = 0, deltaY = 0, page = false}) {
  const node = page ? document.scrollingElement : resolveElement(this);
  if (!node) {
    return {before: {x: 0, y: 0}, after: {x: 0, y: 0}, blocked: true};
  }
  const before = {x: node.scrollLeft, y: node.scrollTop};
  const style = getComputedStyle(node);
  const body = getComputedStyle(document.body || node);
  const overflowX =
    page && style.overflowX === 'visible' ? body.overflowX : style.overflowX;
  const overflowY =
    page && style.overflowY === 'visible' ? body.overflowY : style.overflowY;
  const allowX = page
    ? !/hidden|clip/.test(overflowX)
    : /auto|scroll|overlay/.test(overflowX);
  const allowY = page
    ? !/hidden|clip/.test(overflowY)
    : /auto|scroll|overlay/.test(overflowY);
  const scrollable =
    page ||
    (node !== document.scrollingElement &&
      node.clientWidth > 0 &&
      node.clientHeight > 0 &&
      ((allowX && node.scrollWidth > node.clientWidth + 1) ||
        (allowY && node.scrollHeight > node.clientHeight + 1)));
  if (!scrollable) {
    return {before, after: before, scrollable: false};
  }
  node.scrollBy({
    left: allowX ? deltaX : 0,
    top: allowY ? deltaY : 0,
    behavior: 'instant',
  });
  return {
    before,
    after: {x: node.scrollLeft, y: node.scrollTop},
    blocked: (deltaX !== 0 && !allowX) || (deltaY !== 0 && !allowY),
  };
}
