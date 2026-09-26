const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('alfred', {
  onRecord: (fn) => ipcRenderer.on('record', (_e, v) => fn(v)),
  onState: (fn) => ipcRenderer.on('state', (_e, v) => fn(v)),
  take: (audio, mimeType, ms) => ipcRenderer.invoke('take', { audio, mimeType, ms }),
  answer: (approved) => ipcRenderer.invoke('answer', approved),
  interactive: (on) => ipcRenderer.send('interactive', on),
  stopped: () => ipcRenderer.send('stopped'),
});
