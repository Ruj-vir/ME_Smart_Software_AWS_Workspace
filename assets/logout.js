(() => {
  'use strict';
  const loginUrl = new URL('../Login.html', document.currentScript.src).href;
  if (window.self !== window.top) return;

  const style = document.createElement('style');
  style.textContent = `
    .logout-header { padding-top: calc(var(--logout-original-padding) + 44px) !important; }
    .logout-actions { position: absolute; top: 8px; right: 20px; display: flex; justify-content: flex-end; z-index: 11; }
    .logout-toolbar { display: flex; justify-content: flex-end; padding: 8px 20px; }
    .topbar > .logout-toolbar { margin-left: auto; padding: 0; flex-shrink: 0; }
    .me-logout-button { display: inline-flex; align-items: center; justify-content: center; padding: 7px 16px; border: 1px solid #b42318; border-radius: 6px; background: #fff; color: #b42318; font: 600 14px/1.2 'Segoe UI', sans-serif; cursor: pointer; white-space: nowrap; }
    .me-logout-button:hover { background: #fff1f0; }
    .me-logout-button:focus-visible { outline: 3px solid #0078d7; outline-offset: 2px; }
    .me-logout-button:disabled { opacity: .6; cursor: wait; }
    @media print { .logout-actions, .logout-toolbar { display: none !important; } .logout-header { padding-top: var(--logout-original-padding) !important; } }
  `;
  document.head.append(style);

  const actions = document.createElement('div');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'me-logout-button';
  button.textContent = 'Log out';
  actions.append(button);

  const header = document.querySelector('.header, header');
  if (header) {
    const layout = getComputedStyle(header);
    header.style.setProperty('--logout-original-padding', layout.paddingTop);
    if (layout.position === 'static') header.style.position = 'relative';
    header.classList.add('logout-header');
    actions.className = 'logout-actions';
    header.append(actions);
  } else {
    actions.className = 'logout-toolbar';
    const topbar = document.querySelector('.topbar');
    if (topbar) topbar.append(actions);
    else document.body.prepend(actions);
  }

  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Logging out...';
    try {
      const response = await fetch('/api/logout', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('Logout failed');
      document.documentElement.classList.remove('general-form-admin');
      window.location.replace(loginUrl);
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Log out';
      window.alert('Unable to log out. Please check your connection and try again.');
    }
  });

  // Recheck the server session when Back restores a cached page after logout.
  window.addEventListener('pageshow', async (event) => {
    if (!event.persisted) return;
    try {
      const response = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' });
      if (response.status === 401) window.location.replace(loginUrl);
    } catch (error) {
      console.warn('Unable to check session', error);
    }
  });
})();
