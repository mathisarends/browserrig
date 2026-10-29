/* global parentFor */
function isRendered(el, allowContents = false) {
  if (!el) {
    return false;
  }
  const visible = el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
  const style = allowContents ? getComputedStyle(el) : null;
  const contents =
    allowContents &&
    style.display === 'contents' &&
    style.visibility === 'visible' &&
    canTraverse(el);
  if (!visible && !contents) {
    return false;
  }
  for (let current = el; current; current = parentFor(current)) {
    if (current.inert) {
      return false;
    }
  }
  return true;
}

function canTraverse(el) {
  for (let current = el; current; current = parentFor(current)) {
    const style = getComputedStyle(current);
    if (style.display === 'none' || Number(style.opacity) === 0 || current.inert) {
      return false;
    }
  }
  return true;
}

function createStyleReader() {
  const styles = new Map();
  return (el) => {
    if (!styles.has(el)) {
      styles.set(el, getComputedStyle(el));
    }
    return styles.get(el);
  };
}
