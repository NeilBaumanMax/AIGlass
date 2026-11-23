const el = id => document.getElementById(id);
document.querySelectorAll('[data-icon]').forEach(node => node.style.setProperty('--icon', `url('/static/icons/${node.dataset.icon}.svg')`));
document.querySelectorAll('nav a').forEach(link => link.addEventListener('click', () => {
  document.querySelectorAll('nav a').forEach(item => item.classList.toggle('selected', item === link));
  if (link.hash === '#connection-details') el('connection-details').open = true;
}));
let lastSequence = -1, lastDialog = '', lastEvents = '', state = null, viewGeneration = 0;
const timeText = t => new Date(t * 1000).toLocaleTimeString('zh-CN', {hour12:false});
function label(id, text, tone='') { el(id).textContent = text; el(id).dataset.tone = tone; }
function clearImages() {
  el('raw').hidden = el('overlay').hidden = true;
  el('raw-empty').hidden = el('overlay-empty').hidden = false;
  lastSequence = -1;
  label('frame-size', '第一视角 · 尚无画面');
  label('analysis-message', '尚无画面，等待分析');
  label('direction', '等待方向判断');
  ['floor-ratio', 'obstacle-ratio', 'stairs-ratio'].forEach(id => label(id, '—'));
}
function renderDialog(events) {
  const signature = events.map(e => e.id || e.time + e.text).join('|');
  if (signature === lastDialog) return;
  lastDialog = signature;
  const container = el('chat-scroll');
  const follow = container.scrollHeight - container.scrollTop - container.clientHeight < 70;
  el('dialog').replaceChildren(...events.map(event => {
    const li = document.createElement('li');
    const user = event.text.startsWith('你 · '), assistant = event.text.startsWith('Edith · ');
    li.className = 'message ' + (user ? 'user' : assistant ? 'assistant' : 'system');
    const time = document.createElement('time'); time.textContent = timeText(event.time);
    time.dateTime = new Date(event.time * 1000).toISOString();
    if (user || assistant) {
      const meta = document.createElement('div'); meta.className = 'message-label';
      meta.append(document.createTextNode(user ? '你' : 'Edith'), time);
      const bubble = document.createElement('p'); bubble.className = 'bubble';
      bubble.textContent = event.text.slice(event.text.indexOf(' · ') + 3);
      li.append(meta, bubble);
    } else li.append(time, document.createTextNode(event.text));
    return li;
  }));
  el('chat-empty').hidden = events.length > 0;
  if (follow) container.scrollTop = container.scrollHeight;
}
function renderEvents(events) {
  const recent = events.slice(-18).reverse();
  const signature = recent.map(e=>e.id || e.time+e.text).join('|');
  if (signature === lastEvents) return;
  lastEvents = signature;
  el('alerts').replaceChildren(...recent.map(event=>{
    const li=document.createElement('li'), time=document.createElement('time');
    time.textContent=timeText(event.time);li.append(time,document.createTextNode(event.text));return li;
  }));
  el('events-empty').hidden = recent.length > 0;
  const alerts = events.filter(event => event.kind === 'alert').slice(-3).reverse();
  el('recent-alerts').replaceChildren(...alerts.map(event => {
    const li = document.createElement('li'), icon = document.createElement('span'), time = document.createElement('time');
    icon.className = 'icon';icon.style.setProperty('--icon', "url('/static/icons/focus-2.svg')");
    time.textContent = timeText(event.time);li.append(icon, document.createTextNode(event.text), time);return li;
  }));
  el('recent-empty').hidden = alerts.length > 0;
}
function display(next) {
  state = next;
  const audio = next.audio || {}, info = audio.device || {}, online = audio.online;
  label('connection', '电脑后端在线', 'good');
  label('board-state', online ? '已连接' : '未连接', online ? 'good' : 'warning');
  label('device-health', online ? '设备在线' : '设备离线', online ? 'good' : 'warning');
  label('board-detail', online ? (info.ssid || 'Wi-Fi') + ' · Pico Zero' : '等待设备心跳');
  label('wake-state', !online ? '设备离线' : audio.awake ? '已唤醒' : '等待唤醒', audio.awake ? 'good' : '');
  label('wake-detail', audio.wake_error || (audio.awake && audio.idle_remaining != null ? audio.idle_remaining + ' 秒后退出' : '嗨，Edith'));
  const phase = !online ? 'offline' : audio.playing ? 'speaking' : audio.busy ? 'thinking' : audio.awake ? 'listening' : 'idle';
  const names = {offline:'设备离线', speaking:'正在播报', thinking:'正在思考', listening:'正在聆听', idle:'等待唤醒'};
  label('ai-state', !next.qwen ? '未配置千问' : names[phase], phase === 'listening' ? 'good' : '');
  label('ai-detail', phase === 'thinking' ? '正在生成语音回答' : phase === 'speaking' ? (audio.duplex ? '可以直接插话' : '请听完后再说') : '千问 · 北京地域');
  const agent = audio.agent || {};
  if (agent.provider === 'nanomuse') {
    const states = {thinking:'正在思考', executing:'正在执行任务', awaiting_approval:'等待语音确认', cancelling:'正在取消任务', uncertain:'任务状态待核实', idle:'nanoMuse 已就绪'};
    const phones = (agent.devices || []).filter(d=>d.kind==='phone' && d.online).length;
    label('ai-state', agent.online ? (states[agent.phase] || 'nanoMuse 已连接') : 'nanoMuse 未连接', agent.online ? '' : 'warning');
    label('ai-detail', agent.online ? `nanoMuse · ${agent.hub_connected ? phones + ' 台手机在线' : '设备互联未连接'}` : '请启动已启用眼镜接口的 nanoMuse');
  }
  label('voice-title', names[phase]); el('presence').dataset.phase = phase;
  label('voice', phase === 'idle' ? '对眼镜说「嗨，Edith」' : phase === 'thinking' ? '正在理解你的问题…' : phase === 'speaking' ? (audio.duplex ? '想补充内容？直接开口就好' : '正在通过眼镜喇叭回答') : phase === 'listening' ? '我在，请说' : '眼镜重新连接后自动恢复');
  label('mic-label', audio.microphone ? '麦克风在线 · ' + audio.mic_dbfs + ' dBFS' : '未收到麦克风数据');
  label('duplex-label', audio.aec_error ? '回声处理异常' : audio.duplex ? '双向音频 · 回声消除' : '轮流说话');
  label('vision-state', next.engine_state === 'ready' ? (next.video_online ? '正在分析' : '引擎就绪') : next.engine_state === 'error' ? '模型异常' : '加载模型中');
  label('vision-detail', next.device ? next.device.toUpperCase() + ' · SegFormer-B2' : 'WalkGuide · 电脑端运行');
  label('vision-version', next.vision_revision ? 'WalkGuide · ' + next.vision_revision.slice(0, 7) : 'WalkGuide · 电脑本地推理');
  label('mode', next.mode === 'outdoor' ? '室外模式' : '室内模式');
  const isTest = next.source !== '未配置' && !next.source.startsWith('rtsp://');
  label('video-badge', next.video_online ? (isTest ? '测试录像' : 'LIVE') : '等待摄像头', next.video_online ? 'good' : 'warning');
  label('video-note', next.error || (next.video_online ? (isTest ? '当前是后端测试素材，不是眼镜实拍。' : '原始画面与分割结果对应同一帧；颜色表示视觉候选区域。') : '正在等待 CSI 摄像头的视频流。离线时不显示旧画面或通行判断。'));
  label('stats', next.frame ? '推理 ' + next.ms + ' ms · 帧 ' + next.frame.sequence : '等待第一帧');
  if (next.frame) {
    label('frame-size', (isTest ? '测试画面' : '第一视角') + (next.frame.width ? ` · ${next.frame.width} × ${next.frame.height}` : ''));
    const analysis = next.frame.analysis;
    label('analysis-message', analysis ? analysis.message : '正在分析当前画面');
    label('direction', analysis?.direction_message || '等待方向判断', analysis?.direction === 'stop' ? 'warning' : '');
    for (const kind of ['floor', 'obstacle', 'stairs']) label(kind + '-ratio', analysis && analysis[kind] != null ? analysis[kind] + '%' : '—');
    const frameKey = next.frame.sequence + ':' + (next.frame.mode || next.mode);
    if (frameKey !== lastSequence) {
      el('raw').src='data:image/jpeg;base64,'+next.frame.raw;el('overlay').src='data:image/jpeg;base64,'+next.frame.overlay;
      el('raw').hidden=el('overlay').hidden=false;el('raw-empty').hidden=el('overlay-empty').hidden=true;
      lastSequence=frameKey;
    }
  } else clearImages();
  label('os-info', info.os || '等待 Linux 设备信息'); label('ssid', info.ssid || '—');label('board-ip', info.ip || '—');
  label('heartbeat', online ? (audio.heartbeat_age || 0) + ' 秒前' : '已离线');
  label('source-address', next.source || '等待设备');label('events-live', '实时同步');
  renderDialog(next.events.filter(e=>e.kind==='dialog'));renderEvents(next.events.filter(e=>e.kind!=='dialog'));
}
async function refresh() {
  const generation = viewGeneration;
  try { const response=await fetch('/api/status',{signal:AbortSignal.timeout(4000)});if(!response.ok)throw Error();const next=await response.json();if(generation===viewGeneration)display(next); }
  catch {
    label('connection','电脑后端离线','bad');label('board-state','状态未知','warning');label('board-detail','无法取得设备心跳');
    label('wake-state','状态未知');label('ai-state','连接中断');label('voice-title','连接中断');label('voice','正在等待电脑后端恢复');
    label('mic-label','麦克风状态未知');label('duplex-label','链路状态未知');label('heartbeat','状态未知');label('vision-state','状态未知');
    label('video-badge','连接中断','bad');label('stats','无实时数据');el('presence').dataset.phase='offline';clearImages();
    label('device-health','状态未知','warning');label('wake-detail','等待后端恢复');label('ai-detail','等待后端恢复');
    label('vision-detail','等待后端恢复');label('video-note','电脑后端连接中断，正在重连。');label('events-live','历史记录');
  } finally { setTimeout(refresh,500); }
}
el('clear-dialog').addEventListener('click',async()=>{
  const button=el('clear-dialog');button.disabled=true;
  viewGeneration++;
  try {
    const response=await fetch('/api/dialog/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if(!response.ok)throw Error();lastDialog='reset';renderDialog([]);label('clear-feedback','对话展示记录已清空');label('clear-label','已清空');
  } catch { label('clear-label','清空失败，重试');label('clear-feedback','无法清空，请检查后端连接'); }
  finally {button.disabled=false;setTimeout(()=>label('clear-label','清空记录'),2000);}
});
setInterval(()=>label('clock',new Date().toLocaleTimeString('zh-CN',{hour12:false})),1000);
refresh();
