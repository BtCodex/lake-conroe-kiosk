const title = document.querySelector('title');
new MutationObserver(() => {
  if (title.textContent !== 'Lake Dashboard') title.textContent = 'Lake Dashboard';
}).observe(title, {childList: true, characterData: true, subtree: true});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(error => {
    console.warn('Lake Dashboard service worker registration failed:', error);
  });
}
