// WebSocket client with automatic reconnect.
export function connectLive(onMessage, onStatus) {
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`;
  let delay = 500;
  let ws;

  const open = () => {
    ws = new WebSocket(url);
    ws.onopen = () => { delay = 500; onStatus(true); };
    ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
    ws.onclose = () => {
      onStatus(false);
      setTimeout(open, delay);
      delay = Math.min(delay * 2, 5000);
    };
    ws.onerror = () => ws.close();
  };
  open();
}
