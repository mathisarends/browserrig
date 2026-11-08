function createChoreographyTransfers(ui, cursor) {
  const file = ui.svg(
    '<path d="M5 2h9l7 7v21H5Z M14 2v8h7 M9 17h8 M9 22h8" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  );
  const downloads = new Map();
  let downloadSequence = 0;
  let flight = 0;
  for (const id of ['download', 'opening', 'upload', 'flying-file']) {
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
  const downloadCard = (downloadId, name = 'Download') => {
    let item = downloads.get(downloadId);
    if (!item) {
      const node =
        downloads.size === 0
          ? ui.node('download')
          : ui.node('download').cloneNode(true);
      node.id = downloads.size === 0 ? 'download' : `download-${++downloadSequence}`;
      node.dataset.downloadId = downloadId;
      ui.node('downloads').append(node);
      item = {id: node.id, node, name};
      downloads.set(downloadId, item);
    }
    if (name !== 'Download') {
      item.name = name;
    }
    return item;
  };
  const finish = (event, status, state) => {
    const item = downloadCard(event.download_id, event.filename);
    item.state = state;
    ui.cancel(`download:${event.download_id}`);
    card(item.id, item.name, status, state);
    ui.later(
      `download:${event.download_id}`,
      () => {
        downloads.delete(event.download_id);
        if (item.id === 'download') {
          ui.panel(item.id, false);
        } else {
          item.node.remove();
        }
      },
      2200,
    );
  };
  const show = (event) => {
    const kinds = ui.options().events;
    switch (event.type) {
      case kinds.FILE_TRANSFER: {
        const uploading = event.direction === 'upload';
        const id = uploading ? 'upload' : 'opening';
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
      case kinds.FILES_UPLOADED:
        card('upload', event.paths.map(filename).join(', '), 'Uploaded', 'completed');
        ui.hide('upload', 2200);
        break;
      case kinds.DOWNLOAD_STARTED: {
        const item = downloadCard(event.download_id, event.filename);
        item.state = 'active';
        ui.cancel(`download:${event.download_id}`);
        card(item.id, item.name, 'Downloading …');
        if (!event.restoring) {
          fly(item.id, cursor.point(), false);
        }
        break;
      }
      case kinds.DOWNLOAD_PROGRESS: {
        const item = downloadCard(event.download_id);
        if (item.state && item.state !== 'active') {
          break;
        }
        const progress =
          event.total_bytes > 0
            ? ` / ${(event.total_bytes / 1024).toFixed(1)} KB`
            : ' KB received';
        card(
          item.id,
          item.name,
          `${(event.received_bytes / 1024).toFixed(1)}${progress}`,
        );
        break;
      }
      case kinds.DOWNLOAD_COMPLETED:
        finish(event, 'Downloaded', 'completed');
        break;
      case kinds.DOWNLOAD_FAILED:
        finish(event, 'Download failed', 'failed');
        break;
      case kinds.DOWNLOAD_CANCELED:
        finish(event, 'Download canceled', 'failed');
        break;
      default:
        break;
    }
  };
  const reset = () => {
    for (const [downloadId, item] of downloads) {
      ui.cancel(`download:${downloadId}`);
      if (item.id !== 'download') {
        item.node.remove();
      }
    }
    downloads.clear();
    ui.panel('download', false);
    ui.panel('opening', false);
    ui.panel('upload', false);
  };
  return {show, reset};
}
