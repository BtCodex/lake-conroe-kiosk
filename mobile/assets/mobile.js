const title = document.querySelector('title');
new MutationObserver(() => {
  if (title.textContent !== 'Lake Dashboard') title.textContent = 'Lake Dashboard';
}).observe(title, {childList: true, characterData: true, subtree: true});

const installPanel = document.getElementById('install-app');
const installButton = document.getElementById('install-button');
const installHelp = document.getElementById('install-help');
let installPrompt;

if (/Android/i.test(navigator.userAgent) && !matchMedia('(display-mode: standalone)').matches) {
  installPanel.hidden = false;
}

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  installPrompt = event;
  installPanel.hidden = false;
});

window.addEventListener('appinstalled', () => {
  installPrompt = null;
  installPanel.hidden = true;
});

function showInstallHelp(show) {
  installHelp.hidden = !show;
  installButton.setAttribute('aria-expanded', String(show));
}

installButton.addEventListener('click', async () => {
  if (!installPrompt) {
    showInstallHelp(installHelp.hidden);
    return;
  }

  const prompt = installPrompt;
  installPrompt = null;
  showInstallHelp(false);
  try {
    await prompt.prompt();
    if ((await prompt.userChoice).outcome === 'accepted') installPanel.hidden = true;
  } catch {
    showInstallHelp(true);
  }
});

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
