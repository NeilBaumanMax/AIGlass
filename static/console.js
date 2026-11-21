const el = id => document.getElementById(id);
let lastSequence = -1;
function showEvents(id, events) {
  el(id).replaceChildren(...events.map(event => {
    const li = document.createElement('li');
    const time = document.createElement('time');
    time.textContent = new Date(event.time * 1000).toLocaleTimeString();
    li.append(time, document.createTextNode(event.text));
    return li;
  }));
}
function clearImages() {
  el('raw').hidden = el('overlay').hidden = true;
  lastSequence = -1;
}
async function refresh() {
  try {
    const response = await fetch('/api/status', {signal: AbortSignal.timeout(4000)});
    if (!response.ok) throw new Error('状态请求失败');
    const state = await response.json();
    el('connection').textContent = '电脑后端在线';
    const source = state.source.startsWith('rtsp://') ? '眼镜摄像头' : state.source === '未配置' ? '等待眼镜配置' : '后端测试录像';
    el('status').textContent = source + ' · ' + (state.video_online ? '视频在线' : '视频离线') +
      ' · ' + (state.mode === 'indoor' ? '室内走廊' : '室外通道');
    el('stats').textContent = state.error || (state.device ? state.device + ' · 推理 ' + state.ms + ' ms' : '等待视觉处理');
    if (state.frame) {
      if (state.frame.sequence !== lastSequence) {
        el('raw').src = 'data:image/jpeg;base64,' + state.frame.raw;
        el('overlay').src = 'data:image/jpeg;base64,' + state.frame.overlay;
        el('raw').hidden = el('overlay').hidden = false;
        lastSequence = state.frame.sequence;
      }
    } else clearImages();
    const audio = state.audio;
    el('voice').textContent = (audio?.online ? '眼镜音频在线' : '眼镜音频离线') + ' · ' +
      (audio?.microphone ? '麦克风 ' + audio.mic_dbfs + ' dBFS' : '未收到麦克风数据') + ' · ' +
      (audio?.awake ? '已唤醒' : '等待唤醒：你好，小镜') + ' · ' +
      (audio?.playing ? '正在播放' : audio?.busy ? '千问正在回答' : '等待指令') +
      (state.qwen ? '' : ' · 百炼密钥未配置');
    showEvents('alerts', state.events.filter(event => event.kind !== 'dialog'));
    showEvents('dialog', state.events.filter(event => event.kind === 'dialog'));
  } catch {
    el('connection').textContent = '后端连接中断';
    el('status').textContent = '无法取得设备状态';
    el('voice').textContent = '音频状态未知';
    clearImages();
  } finally {
    setTimeout(refresh, 500);
  }
}
refresh();
