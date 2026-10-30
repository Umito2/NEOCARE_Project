(function () {
  'use strict';
  if (window !== window.top || location.origin !== 'https://umito.pythonanywhere.com'
      || window.__neocareNativeReports || !window.NEOCAREAndroid) return;
  window.__neocareNativeReports = true;
  const bridge = window.NEOCAREAndroid;
  const pdfs = new Map();
  const createObjectURL = URL.createObjectURL.bind(URL);
  const revokeObjectURL = URL.revokeObjectURL.bind(URL);
  const originalClick = HTMLAnchorElement.prototype.click;
  const maximumSize = 8 * 1024 * 1024;
  let reading = false;

  URL.createObjectURL = function (blob) {
    const url = createObjectURL(blob);
    if (blob instanceof Blob && blob.type === 'application/pdf') pdfs.set(url, blob);
    return url;
  };
  URL.revokeObjectURL = function (url) {
    pdfs.delete(String(url));
    return revokeObjectURL(url);
  };

  function exportPdf(link) {
    const blob = pdfs.get(link.href);
    if (!blob || !link.download) return false;
    if (reading || blob.size > maximumSize) {
      bridge.postMessage(JSON.stringify({ op: 'downloadError' }));
      return true;
    }
    reading = true;
    const reader = new FileReader();
    reader.onload = function () {
      reading = false;
      const encoded = String(reader.result || '');
      const comma = encoded.indexOf(',');
      if (comma < 0) {
        bridge.postMessage(JSON.stringify({ op: 'downloadError' }));
        return;
      }
      bridge.postMessage(JSON.stringify({
        op: 'savePdf', data: encoded.slice(comma + 1),
        mimeType: 'application/pdf', filename: link.download
      }));
    };
    reader.onerror = function () {
      reading = false;
      bridge.postMessage(JSON.stringify({ op: 'downloadError' }));
    };
    // Hold the Blob itself: the website revokes its object URL after one second.
    reader.readAsDataURL(blob);
    return true;
  }

  HTMLAnchorElement.prototype.click = function () {
    if (!exportPdf(this)) return originalClick.call(this);
  };
  document.addEventListener('click', function (event) {
    const link = event.target instanceof Element ? event.target.closest('a[download]') : null;
    if (link && exportPdf(link)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  window.print = function () {
    bridge.postMessage(JSON.stringify({ op: 'print' }));
  };
})();
