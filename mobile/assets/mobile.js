const title = document.querySelector('title');
new MutationObserver(() => {
  if (title.textContent !== 'Lake Dashboard') title.textContent = 'Lake Dashboard';
}).observe(title, {childList: true, characterData: true, subtree: true});

const cameraButton = document.getElementById('camera-fullscreen');
const cameraPanel = cameraButton.closest('.camera-panel');

if (document.fullscreenEnabled) {
  cameraButton.hidden = false;
  document.addEventListener('fullscreenchange', () => {
    cameraButton.textContent = document.fullscreenElement === cameraPanel ? 'Exit full screen' : 'Full screen';
  });

  cameraButton.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement === cameraPanel) {
        await document.exitFullscreen();
        return;
      }
      await cameraPanel.requestFullscreen();
      if (matchMedia('(pointer: coarse)').matches && screen.orientation?.lock) {
        // Chrome releases this lock when the camera exits fullscreen.
        await screen.orientation.lock('landscape').catch(() => {});
      }
    } catch (error) {
      console.warn('Lake Dashboard could not change camera fullscreen:', error);
    }
  });
}

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(error => {
    console.warn('Lake Dashboard service worker registration failed:', error);
  });
}
