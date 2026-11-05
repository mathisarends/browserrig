function createChoreographyTransfers(ui, cursor) {
  const file = ui.svg(
    '<path d="M5 2h9l7 7v21H5Z M14 2v8h7 M9 17h8 M9 22h8" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  );
  let download = '';
  let flight = 0;
  for (const id of ['download', 'upload', 'flying-file']) {
    const element =
      id === 'flying-file' ? ui.node(id) : ui.node(id).querySelector('.file-icon');
    element.innerHTML = file;
  }
  const card = (id, filename, status, state = 'active') => {
    const element = ui.node(id);
    element.querySelector('b').textContent = filename;
    element.querySelector('.file-copy span').textContent = status;
    let symbol = id === 'upload' ? '↑' : '↓';
    if (state !== 'active') {
      symbol = {completed: '✓', failed: '×'}[state];
    }
    element.querySelector('.transfer-state').textContent = symbol;
    element.dataset.state = state;
    ui.panel(id, true);
  };
  const fly = (id, point, uploading, seconds = 0.45) => {
    if (ui.reduced()) {
      return;
    }
    const generation = ++flight;
    const target = ui.node(id).getBoundingClientRect();
    const cardPoint = [target.left + 34, target.top + 36];
    const from = uploading ? cardPoint : point;
    const to = uploading ? point : cardPoint;
    const control = [
      from[0] + (to[0] - from[0]) * 0.75,
      Math.max(8, Math.min(from[1], to[1]) - 48),
    ];
    const element = ui.node('flying-file');
    const started = performance.now();
    element.style.display = 'grid';
    const animate = (now) => {
      if (generation !== flight) {
        return;
      }
      const fraction = Math.min(1, (now - started) / Math.max(1, seconds * 1000));
      const t = fraction * fraction * (3 - 2 * fraction);
      const p = from.map(
        (value, axis) =>
          (1 - t) ** 2 * value + 2 * (1 - t) * t * control[axis] + t ** 2 * to[axis],
      );
      element.style.transform = `translate(${p[0] - 20}px, ${p[1] - 20}px) rotate(${Math.sin(t * Math.PI) * 0.25}rad)`;
      element.style.opacity = Math.min(1, fraction * 10, (1 - fraction) * 10);
      if (fraction < 1) {
        requestAnimationFrame(animate);
      } else {
        element.style.display = 'none';
      }
    };
    requestAnimationFrame(animate);
  };
  const filename = (path) => path.split(/[\\/]/).pop();
  const finish = (event, status, state) => {
    if (download && event.download_id !== download) {
      return;
    }
    const name = event.filename || ui.node('download').querySelector('b').textContent;
    card('download', name, status, state);
    ui.hide('download', 2200);
  };
  const show = (event) => {
    switch (event.type) {
      case 'browser.files.transfer': {
        const uploading = event.direction === 'upload';
        const id = uploading ? 'upload' : 'download';
        card(
          id,
          event.paths.map(filename).join(', '),
          uploading ? 'Uploading …' : 'Opening …',
        );
        const point = event.x === null ? cursor.point() : [event.x, event.y];
        fly(id, point, uploading, event.duration);
        if (!uploading) {
          ui.hide(id, 1800);
        }
        break;
      }
      case 'browser.files.uploaded':
        card('upload', event.paths.map(filename).join(', '), 'Uploaded', 'completed');
        ui.hide('upload', 2200);
        break;
      case 'browser.download.started':
        download = event.download_id;
        card('download', event.filename, 'Downloading …');
        fly('download', cursor.point(), false);
        break;
      case 'browser.download.progress':
        if (event.download_id === download) {
          ui.node('download').querySelector('.file-copy span').textContent =
            `${(event.received_bytes / 1024).toFixed(1)} KB received`;
        }
        break;
      case 'browser.download.completed':
        finish(event, 'Downloaded', 'completed');
        break;
      case 'browser.download.failed':
        finish(event, 'Download failed', 'failed');
        break;
      case 'browser.download.canceled':
        finish(event, 'Download canceled', 'failed');
        break;
      default:
        break;
    }
  };
  return {show};
}
