/* global focusStep, isTextField, maskSecretField */
function browserrigSecretFocus(args) {
  const origins = [location.origin];
  let target = document.activeElement;
  let crossOrigin = false;
  for (;;) {
    const step = focusStep(target);
    if (step.origin) {
      origins.push(step.origin);
    }
    crossOrigin ||= Boolean(step.crossOrigin);
    if (!step.next || step.next === target) {
      break;
    }
    target = step.next;
  }
  const editable = !crossOrigin && isTextField(target);
  const state = (globalThis.__browserrig ||= {});
  if (args.start) {
    state.secretTarget = editable ? target : null;
    if (editable) {
      maskSecretField(target);
    }
  }
  return {
    origins,
    cross_origin: crossOrigin,
    editable,
    same: editable && state.secretTarget === target,
  };
}
