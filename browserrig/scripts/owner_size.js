/* global isRendered */
function browserrigOwnerSize(_args) {
  if (!isRendered(this)) {
    return null;
  }
  const style = getComputedStyle(this);
  return [
    this.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
    this.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
  ];
}
