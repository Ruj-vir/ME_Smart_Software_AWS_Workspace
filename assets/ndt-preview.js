// Uploaded attachments are kept apart from editable bank-form records.
function ndtPreviewPrefix(subtabId) {
  const config = REPORT_CONFIG[subtabId];
  if (!config?.report) throw new Error('Invalid NDT category');
  return config.dest + 'Preview Uploads/';
}

async function uploadNdtPreview(subtabId, input) {
  const file = input.files[0];
  if (!file) return;
  const status = document.getElementById('ndtUploadStatus-' + subtabId);
  if (!/\.(pdf|png|jpe?g|gif|webp)$/i.test(file.name)) {
    status.textContent = 'Please choose a PDF or image (PNG, JPG, GIF, WebP).';
    input.value = '';
    return;
  }
  const button = document.getElementById('ndtUploadButton-' + subtabId);
  button.disabled = true;
  status.textContent = 'Uploading...';
  try {
    const data = new FormData();
    // Unique names prevent a later upload from overwriting an earlier attachment.
    const name = Date.now() + '-' + crypto.randomUUID() + '_' + file.name.replace(/[\\/]/g, '_');
    data.append('file', file, name);
    const response = await fetch('/api/browse/upload?prefix=' + encodeURIComponent(ndtPreviewPrefix(subtabId)), {
      method: 'POST', body: data,
    });
    if (!response.ok) throw new Error('Upload failed');
    status.textContent = 'Uploaded';
    await loadNdtPreviews(subtabId);
  } catch (error) {
    status.textContent = 'Upload failed. Please try again.';
  } finally {
    input.value = '';
    button.disabled = false;
  }
}

async function loadNdtPreviews(subtabId) {
  const list = document.getElementById('ndtPreviews-' + subtabId);
  const request = String(Number(list.dataset.request || 0) + 1);
  list.dataset.request = request;
  try {
    const response = await fetch('/api/browse?prefix=' + encodeURIComponent(ndtPreviewPrefix(subtabId)));
    if (!response.ok) throw new Error('Cannot load previews');
    const { files } = await response.json();
    if (list.dataset.request !== request) return;
    list.replaceChildren();
    for (const file of files) {
      if (!/\.(pdf|png|jpe?g|gif|webp)$/i.test(file.name)) continue;
      const card = document.createElement('div');
      card.className = 'recorded-files-card';
      const title = document.createElement('div');
      title.style.padding = '10px';
      title.textContent = file.name.replace(/^\d+-[a-f0-9-]{36}_/i, '');
      const button = document.createElement('button');
      button.textContent = 'Preview';
      button.style.marginLeft = '12px';
      const viewer = document.createElement('div');
      title.appendChild(button);
      card.append(title, viewer);
      list.appendChild(card);
      button.onclick = async () => {
        if (viewer.childElementCount) {
          viewer.hidden = !viewer.hidden;
          button.textContent = viewer.hidden ? 'Show preview' : 'Hide preview';
          return;
        }
        button.disabled = true;
        button.textContent = 'Loading preview...';
        try {
          const result = await fetch('/api/browse/file-url?object_name=' + encodeURIComponent(file.object_name));
          if (!result.ok) throw new Error('Preview unavailable');
          const { url } = await result.json();
          const pdf = /\.pdf$/i.test(file.name);
          const frame = document.createElement(pdf ? 'iframe' : 'img');
          frame.src = pdf ? url + '#toolbar=0' : url;
          frame.title = title.firstChild.textContent;
          if (!pdf) frame.alt = frame.title;
          frame.style.cssText = pdf ? 'width:100%;height:80vh;border:0' : 'display:block;max-width:100%;max-height:80vh;margin:auto;object-fit:contain';
          viewer.replaceChildren(frame);
          viewer.hidden = false;
          button.textContent = 'Hide preview';
        } catch (error) {
          button.textContent = 'Preview failed - Retry';
        } finally {
          button.disabled = false;
        }
      };
      // Open each attachment immediately, including after upload or revisiting a tab.
      button.onclick();
    }
  } catch (error) {
    if (list.dataset.request === request) list.textContent = 'Unable to load uploaded previews. Reopen this tab to retry.';
  }
}
