/* global createChoreographySurface, createChoreographyCursor, createChoreographyKeyboard, createChoreographyPanels, createChoreographyTransfers, createChoreographyCaption, createChoreographyWork */
function browserrigChoreography(_args) {
  const ui = createChoreographySurface();
  const cursor = createChoreographyCursor(ui);
  const keyboard = createChoreographyKeyboard(ui);
  const caption = createChoreographyCaption(ui);
  const panels = createChoreographyPanels(ui, caption);
  const transfers = createChoreographyTransfers(ui, cursor);
  const work = createChoreographyWork(ui, cursor, caption, panels);
  const show = (data) => {
    panels.show(data);
    cursor.show(data);
    keyboard.show(data);
    transfers.show(data);
    work.show(data);
  };
  window.addEventListener('message', (event) => {
    if (
      event.source !== parent ||
      !event.data ||
      (typeof event.data.type !== 'string' && !Array.isArray(event.data.restore))
    ) {
      return;
    }
    ui.configure(event.data.presentation);
    if (Array.isArray(event.data.restore)) {
      work.reset();
      cursor.reset();
      transfers.reset();
      for (const receipt of event.data.restore) {
        show({...receipt, restoring: true});
      }
    }
    show(event.data);
  });
}
