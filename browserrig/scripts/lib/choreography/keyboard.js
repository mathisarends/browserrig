function createChoreographyKeyboard(ui) {
  const board = ui.node('keyboard');
  const keys = new Map();
  let layout = '';
  let typing = false;
  const key = (label, code, units = 1) => ({label, code, units});
  const letters = (row) => [...row].map((label) => key(label, label.toLowerCase()));
  const rows = (german) => [
    [...letters(german ? '^1234567890ß´' : '`1234567890-='), key('⌫', 'Backspace', 2)],
    [
      key('Tab', 'Tab', 1.5),
      ...letters(german ? 'QWERTZUIOPÜ+' : 'QWERTYUIOP[]'),
      key('↵', 'Enter', 1.5),
    ],
    [
      key('Caps', 'CapsLock', 1.75),
      ...letters(german ? 'ASDFGHJKLÖÄ#' : "ASDFGHJKL;'"),
      key('', 'home-gap', german ? 1.25 : 2.25),
    ],
    [
      key('Shift', 'Shift', german ? 1.25 : 2.25),
      ...letters(german ? '<YXCVBNM,.-' : 'ZXCVBNM,./'),
      key('Shift', 'ShiftRight', 2.75),
    ],
    [
      key('Ctrl', 'Control', 1.25),
      key('⌘', 'Meta', 1.25),
      key('Alt', 'Alt', 1.25),
      key('', ' ', 6.25),
      key('Alt', 'AltRight', 1.25),
      key('⌘', 'MetaRight', 1.25),
      key('☰', 'ContextMenu', 1.25),
      key('Ctrl', 'ControlRight', 1.25),
    ],
  ];
  const drawRow = (row) => {
    const element = document.createElement('div');
    element.className = 'keyboard-row';
    let offset = 0;
    const colors = [
      'rose',
      'amber',
      'cyan',
      'violet',
      'violet',
      'cyan',
      'amber',
      'rose',
    ];
    for (const item of row) {
      const button = document.createElement('span');
      button.className = 'keyboard-key';
      button.dataset.key = item.code;
      button.dataset.modifier = String(item.label.length > 1);
      button.textContent = item.label;
      button.style.setProperty('--units', item.units);
      const zone = Math.min(
        colors.length - 1,
        Math.floor(((offset + item.units / 2) / 15) * colors.length),
      );
      button.style.setProperty('--key-color', `var(--${colors[zone]})`);
      keys.set(item.code, button);
      element.append(button);
      offset += item.units;
    }
    return element;
  };
  const ensure = () => {
    const next = ui.options().keyboard_layout;
    if (next === layout) {
      return;
    }
    layout = next;
    keys.clear();
    ui.node('keyboard-keys').replaceChildren(...rows(layout === 'de').map(drawRow));
  };
  const clear = () => {
    for (const button of keys.values()) {
      button.dataset.pressed = 'false';
    }
  };
  const shifted = '~!@#$%^&*()_+{}|:"<>?';
  const base = "`1234567890-=[]\\;',./";
  const press = (event) => {
    ensure();
    clear();
    const protectedInput = event.key === '•';
    board.dataset.protected = String(protectedInput);
    ui.node('keyboard-caption').textContent = protectedInput ? '• Protected input' : '';
    const modifiers = [...(event.modifiers || [])];
    let code = event.key;
    if (code.length === 1 && !protectedInput) {
      const index = shifted.indexOf(code);
      if (index >= 0) {
        code = base[index];
        modifiers.push('Shift');
      } else if (code !== code.toLowerCase()) {
        modifiers.push('Shift');
      }
      code = code.toLowerCase();
    }
    const active = protectedInput ? [] : [...modifiers, code];
    for (const value of active) {
      const button = keys.get(value);
      if (button) {
        button.dataset.pressed = 'true';
      }
    }
    ui.panel('keyboard', true);
    ui.later('keys', clear, Math.max(110, (event.duration || 0) * 1000));
    if (!typing) {
      ui.hide('keyboard', Math.max(800, (event.duration || 0) * 1000 + 180));
    }
  };
  const show = (event) => {
    const kinds = ui.options().events;
    switch (event.type) {
      case kinds.KEYBOARD_VISIBILITY:
        typing = event.visible;
        ensure();
        if (typing) {
          ui.panel('keyboard', true);
        } else {
          ui.hide('keyboard');
        }
        break;
      case kinds.KEY_PRESSED:
      case kinds.BAR_TYPED:
        press(event);
        break;
      default:
        break;
    }
  };
  return {show};
}
