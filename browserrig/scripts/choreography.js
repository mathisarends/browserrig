/* global createChoreographySurface, createChoreographyCursor, createChoreographyKeyboard, createChoreographyPanels, createChoreographyTransfers */
function browserrigChoreography(_args) {
  const ui = createChoreographySurface();
  const cursor = createChoreographyCursor(ui);
  const keyboard = createChoreographyKeyboard(ui);
  const panels = createChoreographyPanels(ui);
  const transfers = createChoreographyTransfers(ui, cursor);
  window.addEventListener('message', (event) => {
    if (event.source !== parent || !event.data || typeof event.data.type !== 'string') {
      return;
    }
    ui.configure(event.data.presentation);
    panels.show(event.data);
    cursor.show(event.data);
    keyboard.show(event.data);
    transfers.show(event.data);
  });
}
