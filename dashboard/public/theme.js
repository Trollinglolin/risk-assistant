// Apply the saved or requested colour theme before first paint (external file: the site's
// Content-Security-Policy allows no inline scripts).
try {
  var t = new URLSearchParams(location.search).get('theme') || localStorage.getItem('hkrisk-theme')
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t
} catch (e) {}
