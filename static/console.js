const el = id => document.getElementById(id);
const media = el('media'), raw = el('raw'), ctx = raw.getContext('2d');
let generation = 0, stream, fileUrl, latest = '', stamp = 0, lastEvent = '', candidate = '', count = 0;
let resume = false, chatting = false, mic, awakeUntil = 0, history = [];
let replyAudio;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function checked(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.text()).slice(0, 200));
  return response;
}
function log(id, text) {
  const li = document.createElement('li'), time = document.createElement('time');
  time.textContent = new Date().toLocaleTimeString();
  li.append(time, document.createTextNode(text));
  const list = el(id); list.append(li);
  while (list.children.length > 50) list.firstChild.remove();
  list.scrollTop = list.scrollHeight;
}
function say(text, urgent = false) {
  if (urgent) replyAudio?.pause();
  if (!el('speak').checked || !window.speechSynthesis) return;
  if (urgent) speechSynthesis.cancel();
  const voices = speechSynthesis.getVoices().filter(v => v.localService && v.lang.startsWith('zh'));
  if (!voices.length) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voices[0]; speechSynthesis.speak(utterance);
}
function resetEvents() { lastEvent = candidate = ''; count = 0; }
function stop(message = '已停止') {
  generation++; resume = false; latest = ''; stamp = 0; resetEvents();
  media.pause(); stream?.getTracks().forEach(t => t.stop()); stream = null;
  media.srcObject = null; media.removeAttribute('src'); media.load();
  if (fileUrl) URL.revokeObjectURL(fileUrl); fileUrl = null;
  ctx.clearRect(0, 0, raw.width, raw.height); el('overlay').hidden = true; el('stats').textContent = message;
}
function capture(element, w, h) {
  const scale = Math.min(1, 960 / Math.max(w, h));
  raw.width = Math.max(1, Math.round(w * scale)); raw.height = Math.max(1, Math.round(h * scale));
  ctx.drawImage(element, 0, 0, raw.width, raw.height);
  latest = raw.toDataURL('image/jpeg', 0.82); stamp = Date.now();
}
function eventUpdate(event) {
  if (candidate === event) count++; else { candidate = event; count = 1; }
  if (count < (event === '前方路面看不清' ? 5 : 3) || event === lastEvent) return;
  lastEvent = event;
  if (event) { log('alerts', event); say(event, true); }
}
async function start() {
  stop('正在连接输入…');
  const run = generation, source = el('source').value;
  try {
    if (source === 'file') {
      if (!el('file').files.length) throw new Error('请先选择本地视频');
      fileUrl = URL.createObjectURL(el('file').files[0]); media.src = fileUrl;
    } else if (source === 'camera') {
      const incoming = await navigator.mediaDevices.getUserMedia({video:true});
      if (run !== generation) { incoming.getTracks().forEach(t => t.stop()); return; }
      stream = incoming; media.srcObject = stream;
    }
    if (source !== 'board') await media.play();
    if (run !== generation) return;
    resume = true;
    let previousTime = -1, disconnected = false;
    while (run === generation) {
      const mode = el('mode').value;
      if (source === 'board') {
        const response = await fetch('/api/glasses.jpg', {cache:'no-store'});
        if (run !== generation) break;
        if (!response.ok) {
          if (!disconnected) { log('alerts','眼镜视频未连接，视觉提醒暂停'); disconnected = true; }
          latest = ''; resetEvents(); el('overlay').hidden = true; ctx.clearRect(0, 0, raw.width, raw.height);
          el('stats').textContent = '等待眼镜视频'; await pause(750); continue;
        }
        const bitmap = await createImageBitmap(await response.blob());
        if (run !== generation) { bitmap.close(); break; }
        capture(bitmap, bitmap.width, bitmap.height); bitmap.close(); disconnected = false;
      } else {
        if (media.ended) { stop('视频已结束'); break; }
        if (!media.videoWidth || previousTime === media.currentTime) { await pause(50); continue; }
        previousTime = media.currentTime; capture(media, media.videoWidth, media.videoHeight);
      }
      const body = await new Promise(resolve => raw.toBlob(resolve, 'image/jpeg', 0.82));
      const result = await fetch('/api/vision?mode=' + mode, {method:'POST',body});
      if (result.status === 429) { await pause(120); continue; }
      if (!result.ok) throw new Error(await result.text());
      const data = await result.json();
      if (run !== generation || mode !== el('mode').value) continue;
      el('overlay').src = 'data:image/jpeg;base64,' + data.image; el('overlay').hidden = false;
      el('stats').textContent = el('source').selectedOptions[0].text + ' · ' + data.device + ' · 推理 ' + data.ms + ' ms';
      eventUpdate(data.event); await pause(80);
    }
  } catch (e) { if (run === generation) stop(e.message); }
}
el('source').onchange = () => { stop('等待输入'); el('file').hidden = el('source').value !== 'file'; };
el('file').onchange = () => stop('已选择视频，点击开始分析');
el('mode').onchange = () => { resetEvents(); el('overlay').hidden = true; };
el('start').onclick = start; el('stop').onclick = () => stop();
async function status() {
  try {
    const s = await (await checked('/api/status')).json();
    el('board').textContent = s.online ? '眼镜视频在线' : s.configured ? '眼镜视频离线' : '眼镜未配置';
    el('cloud').textContent = s.qwen ? '北京百炼 · 已配置密钥' : '北京百炼 · 尚未配置密钥';
  } catch { el('board').textContent = '电脑服务离线'; }
}
status(); setInterval(status, 3000);
async function command(text, look = false) {
  if (chatting || !text.trim()) return;
  log('dialog','你：' + text);
  if (/^(切换(到)?|打开|进入)(室内|室外)(模式|走廊|通道)?[。！]?$/.test(text)) {
    el('mode').value = text.includes('室内') ? 'indoor' : 'outdoor';
    el('mode').onchange(); const msg = '已切换到' + el('mode').selectedOptions[0].text;
    log('dialog', msg); say(msg); return;
  }
  if (/^(结束对话|退出对话)[。！]?$/.test(text)) {
    awakeUntil = 0; history = []; el('wake').textContent = '等待唤醒：你好，小镜'; return;
  }
  const asksToLook = /^(?:请|帮我|请帮我|麻烦你|小镜[，, ]*)?(?:看看|看一下|看一看|看当前画面|描述(?:一下)?(?:当前|眼前的)?画面)/;
  look ||= asksToLook.test(text);
  if (look && (!resume || !latest || Date.now()-stamp > 4000)) {
    log('dialog','当前没有新鲜画面，请先开始分析。'); return;
  }
  chatting = true;
  try {
    const response = await checked('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text,look,history,frame:look ? latest : undefined})});
    const {text:answer, audio} = await response.json();
    log('dialog','小镜：' + (answer || '语音回复'));
    if (audio && el('speak').checked) {
      replyAudio?.pause(); replyAudio = new Audio('data:audio/wav;base64,' + audio);
      replyAudio.play().catch(() => log('dialog','浏览器未允许自动播放语音'));
    } else if (!audio) say(answer);
    history.push({role:'user',content:text},{role:'assistant',content:answer}); history = history.slice(-8);
    if (awakeUntil) awakeUntil = Date.now()+20000;
  } catch (e) { log('dialog', e.message); } finally { chatting = false; }
}
el('chat').onsubmit = e => { e.preventDefault(); command(el('question').value.trim()); el('question').value = ''; };
el('look').onclick = () => command(el('question').value.trim() || '请看看当前画面。', true);
async function recognize(pcm, session) {
  if (session.busy || chatting) return;
  session.busy = true;
  try {
    const data = await (await checked('/api/listen',{method:'POST',body:pcm})).json();
    if (mic !== session) return;
    let text = data.text;
    const hit = text.match(/你好[小晓筱][镜境静靖径]/);
    if (hit) { awakeUntil = Date.now()+20000; text = text.slice(hit.index+hit[0].length); log('dialog','已唤醒'); }
    if (awakeUntil > Date.now()) {
      el('wake').textContent = '已唤醒'; if (text) { awakeUntil = Date.now()+20000; await command(text); }
    }
  } catch (e) { if (session === mic) { log('dialog', e.message); stopMic(); } }
  finally { session.busy = false; }
}
function stopMic() {
  mic?.stream.getTracks().forEach(t => t.stop()); mic?.context.close();
  mic = null; awakeUntil = 0; el('mic').textContent = '开启电脑麦克风'; el('wake').textContent = '唤醒词：你好，小镜';
}
el('mic').onclick = async () => {
  if (mic) { stopMic(); return; }
  el('mic').disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true}});
    const context = new AudioContext({sampleRate:16000});
    mic = {stream,context,busy:false}; const session = mic;
    await context.audioWorklet.addModule('/static/pcm.js');
    const input = context.createMediaStreamSource(stream), node = new AudioWorkletNode(context,'utterance');
    node.port.onmessage = e => {
      if (mic === session && !window.speechSynthesis?.speaking && (!replyAudio || replyAudio.paused)) recognize(e.data,session);
    };
    input.connect(node); node.connect(context.destination); await context.resume();
    el('mic').textContent = '关闭电脑麦克风'; el('wake').textContent = '等待唤醒：你好，小镜';
  } catch (e) { stopMic(); log('dialog',e.message); } finally { el('mic').disabled = false; }
};
setInterval(() => {
  if (mic && awakeUntil && awakeUntil < Date.now() && !chatting) {
    awakeUntil = 0; history = []; el('wake').textContent = '等待唤醒：你好，小镜';
  }
}, 1000);
