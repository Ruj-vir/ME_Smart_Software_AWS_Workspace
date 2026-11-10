// Access is confirmed by the server; browser storage is not an authority.
(() => {
  const loginUrl = new URL('../Login.html', document.currentScript.src).href;
  async function refreshAccess() {
    document.documentElement.classList.remove('general-form-admin');
    const menu = document.getElementById('myBox');
    const label = document.getElementById('hnLabel');
    if (menu) menu.style.display = 'none';
    if (label) label.classList.remove('open');
    try {
      const response = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' });
      if (response.status === 401) {
        location.replace(loginUrl);
        return;
      }
      if (!response.ok) return;
      const user = await response.json();
      if (user.role === 'admin') document.documentElement.classList.add('general-form-admin');
    } catch (error) {
      console.warn('Unable to check General Form access', error);
    }
  }
  window.addEventListener('pageshow', refreshAccess);
})();
