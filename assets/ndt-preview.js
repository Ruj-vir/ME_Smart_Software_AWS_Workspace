// Preview uploads and bank forms are alternative modes within each NDT category.
function isNdtPreviewFile(file) {
  return /^\d+-[a-f0-9-]{36}_/i.test(file.name) && /\.(pdf|png|jpe?g|gif|webp)$/i.test(file.name);
}

function ndtPreviewPrefix(subtabId) {
  const config = REPORT_CONFIG[subtabId];
  if (!config?.report) throw new Error('Invalid NDT category');
  return config.dest;
}

async function readNdtFiles(subtabId) {
  const prefix = ndtPreviewPrefix(subtabId);
  const response = await fetch('/api/browse?prefix=' + encodeURIComponent(prefix));
  if (!response.ok) throw new Error('Cannot load NDT files');
  const { files, folders = [] } = await response.json();
  // Move attachments created by the old UI into the category itself.
  if (folders.some(folder => folder.name === 'Preview Uploads')) {
    const old = await fetch('/api/browse?prefix=' + encodeURIComponent(prefix + 'Preview Uploads/'));
    if (!old.ok) throw new Error('Cannot load previous uploads');
    for (const file of (await old.json()).files) {
      if (!isNdtPreviewFile(file)) continue;
      let name = file.name;
      if (files.some(existing => existing.name === name)) name = Date.now() + '-' + crypto.randomUUID() + '_' + name;
      const object_name = prefix + name;
      const moved = await fetch('/api/rename-file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_object: file.object_name, new_object: object_name }),
      });
      if (!moved.ok) throw new Error('Cannot move previous upload');
      files.push({ ...file, name, object_name });
    }
  }
  return files;
}

function applyNdtMode(subtabId, files) {
  const previews = files.some(isNdtPreviewFile);
  const bankForms = files.some(file => !isNdtPreviewFile(file));
  document.getElementById('ndtBankButton-' + subtabId).hidden = previews;
  document.getElementById('ndtUploadButton-' + subtabId).hidden = bankForms;
  if (previews) {
    selectedObjectNames[subtabId] = null;
    document.getElementById('selectedBankForm-' + subtabId).textContent = '';
    document.getElementById('recordBtn-' + subtabId).style.display = 'none';
  }
}

async function canUseNdtMode(subtabId, mode) {
  try {
    const files = await readNdtFiles(subtabId);
    applyNdtMode(subtabId, files);
    const blocked = files.some(file => mode === 'bank' ? isNdtPreviewFile(file) : !isNdtPreviewFile(file));
    if (blocked) alert('Delete the existing files before switching between Bank form and Upload.');
    return !blocked;
  } catch (error) {
    alert('Unable to check NDT files. Please try again.');
    return false;
  }
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
    if (!await canUseNdtMode(subtabId, 'preview')) {
      status.textContent = 'Upload cancelled.';
      return;
    }
    const data = new FormData();
    // Unique names prevent a later upload from overwriting an earlier attachment.
    const name = Date.now() + '-' + crypto.randomUUID() + '_' + file.name.replace(/[\\/]/g, '_');
    data.append('file', file, name);
    const response = await fetch('/api/browse/upload?prefix=' + encodeURIComponent(ndtPreviewPrefix(subtabId)), {
      method: 'POST', body: data,
    });
    if (!response.ok) throw new Error('Upload failed');
    status.textContent = 'Uploaded';
    await loadRecordedFiles(subtabId);
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
    const files = await readNdtFiles(subtabId);
    if (list.dataset.request !== request) return;
    applyNdtMode(subtabId, files);
    list.replaceChildren();
    for (const file of files) {
      if (!isNdtPreviewFile(file)) continue;
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
      const deleteButton = document.createElement('button');
      deleteButton.textContent = 'Delete';
      deleteButton.style.marginLeft = '12px';
      deleteButton.onclick = async () => {
        if (!confirm('Delete this uploaded file?')) return;
        deleteButton.disabled = true;
        try {
          const result = await fetch('/api/browse/file?object_name=' + encodeURIComponent(file.object_name), { method: 'DELETE' });
          if (!result.ok) throw new Error('Delete failed');
          await loadRecordedFiles(subtabId);
        } catch (error) {
          alert('Delete failed. Please try again.');
          deleteButton.disabled = false;
        }
      };
      title.appendChild(deleteButton);
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
