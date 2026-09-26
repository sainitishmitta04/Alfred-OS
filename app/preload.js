const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('alfred', {
  // overlay
  onRecord: (fn) => ipcRenderer.on('record', (_e, v) => fn(v)),
  onState: (fn) => ipcRenderer.on('state', (_e, v) => fn(v)),
  take: (audio, mimeType, ms) => ipcRenderer.invoke('take', { audio, mimeType, ms }),
  interactive: (on) => ipcRenderer.send('interactive', on),
  stopped: () => ipcRenderer.send('stopped'),
  openTasks: () => ipcRenderer.send('tasks:open'),
  // both windows
  answer: (sessionId, approved) => ipcRenderer.invoke('answer', sessionId, approved),
  // Tasks window
  tasks: () => ipcRenderer.invoke('tasks:all'),
  taskDetail: (sessionId) => ipcRenderer.invoke('tasks:detail', sessionId),
  onTask: (fn) => ipcRenderer.on('tasks:update', (_e, t) => fn(t)),
});
