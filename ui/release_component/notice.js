(() => {
  const notice = document.getElementById('notice');
  const close = document.getElementById('close');
  let currentKey = null;
  let timer = null;
  let deadline = null;
  let closedKey = null;
  function send(type, values = {}) {
    window.parent.postMessage({isStreamlitMessage: true, type, ...values}, '*');
  }
  function storageGet(key) { try { return sessionStorage.getItem(key); } catch (_) { return null; } }
  function storageSet(key, value) { try { sessionStorage.setItem(key, value); } catch (_) {} }
  function height() { send('streamlit:setFrameHeight', {height: notice.hidden ? 0 : Math.ceil(notice.getBoundingClientRect().height)}); }
  function hide(reason, notify = true) {
    if (timer !== null) clearTimeout(timer);
    notice.hidden = true;
    closedKey = currentKey;
    if (currentKey) storageSet('lessonai-notice-closed:' + currentKey, '1');
    height();
    if (notify) send('streamlit:setComponentValue', {value: {notice_key: currentKey, reason}, dataType: 'json'});
  }
  function render(args) {
    if (timer !== null) clearTimeout(timer);
    currentKey = args.notice_key;
    if (closedKey === currentKey || storageGet('lessonai-notice-closed:' + currentKey) === '1') {
      hide('closed', false); return;
    }
    const storageKey = 'lessonai-notice-deadline:' + currentKey;
    const saved = Number(storageGet(storageKey));
    const requested = Date.now() + Math.max(0, Number(args.remaining_seconds)) * 1000;
    deadline = saved > 0 ? Math.min(saved, requested) : requested;
    storageSet(storageKey, String(deadline));
    if (deadline <= Date.now()) { hide('timeout'); return; }
    document.documentElement.lang = args.language === 'kk' ? 'kk' : 'ru';
    document.getElementById('title').textContent = args.title;
    document.getElementById('message').textContent = args.message;
    close.setAttribute('aria-label', args.language === 'kk' ? 'Жабу' : 'Закрыть');
    notice.hidden = false;
    height();
    timer = setTimeout(() => hide('timeout'), deadline - Date.now());
  }
  close.addEventListener('click', () => hide('manual'));
  window.addEventListener('message', event => {
    if (event.source === window.parent && event.data?.type === 'streamlit:render') render(event.data.args);
  });
  window.addEventListener('resize', height);
  document.addEventListener('visibilitychange', () => {
    if (!notice.hidden && deadline <= Date.now()) hide('timeout');
  });
  send('streamlit:componentReady', {apiVersion: 1});
})();
