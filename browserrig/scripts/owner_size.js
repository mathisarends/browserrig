function browserrigOwnerSize(_args) {
  for (let el = this; el; el = el.parentElement || el.getRootNode().host) {
    const style = getComputedStyle(el);
    if (
      style.display === 'none' ||
      style.visibility !== 'visible' ||
      Number(style.opacity) === 0 ||
      el.inert
    ) {
      return null;
    }
  }
  const style = getComputedStyle(this);
  return [
    this.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
    this.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
  ];
}
