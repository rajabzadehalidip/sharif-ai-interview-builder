const $ = (selector) => document.querySelector(selector);
const state = { pre: {}, preForm: [], protocolVersion: null, step: 0, session: null, pendingTurn: null, waiting: false };
function visiblePreQuestions() {
  return state.preForm.filter(question => !question.visible_if_id || (question.visible_if_answers || []).includes(state.pre[question.visible_if_id]));
}
async function loadPreInterviewForm() {
  const data = await api('/public/pre-interview-form');
  state.preForm = Array.isArray(data.questions) ? data.questions : [];
  state.protocolVersion = Number.isInteger(data.version) ? data.version : null;
}
async function loadProject() {
  const project = await api('/public/project');
  if (Number.isInteger(project.version)) state.protocolVersion = project.version;
  const title = project.project_title || 'مصاحبه پژوهشی';
  document.title = title;
  ['#header-project-title','#project-title','#chat-project-title'].forEach(selector => { const element=$(selector); if (element) element.textContent=title; });
  $('#project-welcome').textContent = project.welcome_text || '';
  $('#project-consent').textContent = project.consent_text || '';
}
function renderPreQuestion(question) {
  const value = state.pre[question.id] || '';
  const required = question.required ? '<span aria-hidden="true"> *</span>' : '';
  if (question.kind === 'multiple') {
    const selected = value ? value.split('؛ ').filter(Boolean) : [];
    return `<fieldset class="pre-multiple" data-multiple="${escapeHtml(question.id)}"><legend>${escapeHtml(question.text)}${required}</legend><p class="muted small">می‌توانید یک یا چند گزینه را انتخاب کنید.${question.required ? '' : ' پاسخ به این سؤال اختیاری است.'}</p>${question.options.map((option, index) => `<label class="pre-option" for="field-${escapeHtml(question.id)}-${index}"><input type="checkbox" id="field-${escapeHtml(question.id)}-${index}" value="${escapeHtml(option)}" ${selected.includes(option) ? 'checked' : ''}><span dir="auto">${escapeHtml(option)}</span></label>`).join('')}${question.allows_other ? `<label class="field"><span>گزینه دیگر…</span><input data-other="${escapeHtml(question.id)}" value="${escapeHtml(selected.filter(item => !question.options.includes(item)).join('؛ '))}" placeholder="در صورت تمایل بنویسید"></label>` : ''}</fieldset>`;
  }
  if (question.kind === 'single') return `<div class="field"><label for="field-${escapeHtml(question.id)}">${escapeHtml(question.text)}${required}</label><select id="field-${escapeHtml(question.id)}" data-pre-field="${escapeHtml(question.id)}"><option value="">انتخاب کنید…</option>${question.options.map(option => `<option value="${escapeHtml(option)}" ${value === option ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select></div>`;
  return `<div class="field"><label for="field-${escapeHtml(question.id)}">${escapeHtml(question.text)}${required}</label><input id="field-${escapeHtml(question.id)}" data-pre-field="${escapeHtml(question.id)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(question.placeholder || 'پاسخ شما…')}" autocomplete="off"></div>`;
}

async function api(path, options={}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  let response;
  try { response = await fetch(path, {headers:{"Content-Type":"application/json", ...(options.headers || {})}, ...options, signal:controller.signal}); }
  finally { clearTimeout(timer); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : 'لطفاً فیلدهای فرم را بررسی کنید'); error.status=response.status; throw error; }
  return data;
}
function reveal(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }
function escapeHtml(value="") { return String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c])); }
function showParticipant() { hide("#dashboard"); reveal("#participant"); }
function typingMarkup() {
  return `<div id="typing-indicator" class="typing-indicator" role="status"><span class="typing-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>مصاحبه‌گر در حال نوشتن است…</span></div>`;
}
function setWaiting(waiting) {
  state.waiting = waiting;
  const chat = $("#chat");
  if (chat) chat.setAttribute("aria-busy", String(waiting));
  const input = $("#message-input"), send = $("#send"), end = $("#end-interview");
  if (input) input.disabled = waiting || !!state.pendingTurn;
  if (send) send.disabled = waiting || !!state.pendingTurn;
  if (end) end.disabled = waiting;
  document.querySelectorAll("#choice-form button, #choice-form input, #chat-controls button").forEach(button => button.disabled = waiting || !!state.pendingTurn);
}

function renderStep() {
  const questions = visiblePreQuestions();
  state.step = Math.min(state.step, Math.max(0, questions.length - 1));
  const question = questions[state.step];
  $("#pre-step-label").textContent = `پرسش ${state.step + 1} از ${questions.length}`;
  $("#pre-progress").textContent = `${Math.round(((state.step + 1) / questions.length) * 100)}٪`;
  $("#pre-title").textContent = question.section;
  $("#pre-help").textContent = question.kind === 'multiple' ? 'لطفاً همه گزینه‌های مرتبط را انتخاب کنید.' : (question.required ? 'لطفاً پاسخ خود را انتخاب یا وارد کنید.' : 'پاسخ به این سؤال اختیاری است.');
  $("#pre-fields").innerHTML = renderPreQuestion(question);
  $("#pre-error").textContent = '';
  $("#pre-back").classList.toggle("hidden", state.step === 0);
  $("#pre-next").textContent = state.step === questions.length - 1 ? "ورود به گفت‌وگو" : "ادامه";
}
function collectStep() {
  const question = visiblePreQuestions()[state.step];
  if (!question) return true;
  let value = '';
  if (question.kind === 'multiple') {
    const group = document.querySelector('#pre-fields [data-multiple]');
    const selected = [...group.querySelectorAll('input:checked')].map(input => input.value);
    const other = group.querySelector('[data-other]')?.value.trim();
    if (other) selected.push(other);
    value = selected.join('؛ ');
  } else value = document.querySelector('#pre-fields [data-pre-field]')?.value.trim() || '';
  if (question.required && !value) {
    $('#pre-error').textContent = 'برای ادامه، پاسخ این پرسش را وارد یا انتخاب کنید.';
    document.querySelector('#pre-fields [data-pre-field], #pre-fields input')?.focus();
    return false;
  }
  if (value) state.pre[question.id] = value; else delete state.pre[question.id];
  return true;
}
async function startInterview() {
  $("#pre-next").disabled = true;
  try {
    const preInterview = Object.fromEntries(visiblePreQuestions().filter(question => state.pre[question.id]).map(question => [question.text, state.pre[question.id]]));
    state.session = await api("/sessions", {method:"POST",body:JSON.stringify({pre_interview:preInterview, expected_settings_version:state.protocolVersion})}); localStorage.setItem("interview-builder-id", state.session.id); hide("#pre-form"); reveal("#chat"); renderChat();
  }
  catch (error) {
    if (error.status === 409) {
      alert(`${error.message}\n\nصفحه اکنون با نسخهٔ منتشرشدهٔ جدید بارگذاری می‌شود.`);
      location.reload();
      return;
    }
    alert(error.message);
  } finally { $("#pre-next").disabled = false; }
}
function renderChat() {
  if (!state.session) return;
  const container = $("#messages");
  const messages = [...state.session.messages];
  if (state.pendingTurn && !messages.some(message => message.turn_id === state.pendingTurn.requestId)) {
    messages.push({ role: "user", content: state.pendingTurn.text });
  }
  container.innerHTML = messages.map(message => `<div class="message ${message.role === "user" ? "user" : "assistant"}">${escapeHtml(message.content)}</div>`).join("") + (state.waiting ? typingMarkup() : "");
  container.scrollTop = container.scrollHeight;
  const choices = state.session.current_choices || [];
  const choiceMode = state.session.status === "active" && choices.length > 0;
  $("#choice-form").classList.toggle("hidden", !choiceMode); $("#message-form").classList.toggle("hidden", choiceMode || state.session.status !== "active");
  if (choiceMode) $("#choice-form").innerHTML = state.session.current_response_kind === 'multiple' ? `<div class="muted">یک یا چند گزینه انتخاب کنید</div>${choices.map((choice,index)=>`<label class="pre-option"><input type="checkbox" value="${index}"><span>${escapeHtml(choice)}</span></label>`).join('')}<button type="submit" class="primary">ارسال گزینه‌ها</button>` : `<div class="muted">یک گزینه را انتخاب کنید</div>${choices.map((choice,index) => `<button class="choice" type="button" data-choice="${index}">${escapeHtml(choice)}</button>`).join("")}`;
  setWaiting(state.waiting);
  if (state.session.status !== 'active') {
    hide('#chat'); reveal('#complete');
    const interrupted = state.session.status === 'interrupted';
    $('#complete h1').textContent = interrupted ? 'گفت‌وگو موقتاً متوقف شده است' : 'سپاس از مشارکت شما';
    $('#complete p').textContent = interrupted ? 'پاسخ‌ها محفوظ‌اند. می‌توانید همان نوبت را بازیابی کنید.' : state.session.status === 'completed' ? 'مصاحبه کامل شد و پاسخ‌های شما ثبت شدند.' : 'گفت‌وگو پایان یافت و پاسخ‌های ثبت‌شده محفوظ‌اند.';
    $('#resume-interrupted').classList.toggle('hidden', !interrupted);
    if (!interrupted) localStorage.removeItem('interview-builder-id');
  }
}
function storageKey(kind) { return `interview-builder-${kind}-${state.session.id}`; }
function clearPending() { localStorage.removeItem(storageKey('pending')); state.pendingTurn=null; }
async function submitAnswer(text, control='answer') {
  if (!text || !state.session || state.waiting || state.pendingTurn) return;
  const pending = { text, control, requestId: crypto.randomUUID() };
  try { localStorage.setItem(storageKey('pending'), JSON.stringify(pending)); }
  catch (_) { alert('ذخیره محلی در مرورگر در دسترس نیست. پاسخ را نگه دارید و دسترسی ذخیره‌سازی را فعال کنید.'); return; }
  state.pendingTurn = pending;
  $('#message-input').value=''; localStorage.removeItem(storageKey('draft'));
  await submitRetry();
}
async function retryPendingTurn() { if (state.pendingTurn) await submitRetry(); }
async function submitRetry() {
  if (!state.pendingTurn || !state.session || state.waiting) return;
  $("#network-note").classList.add("hidden"); setWaiting(true); renderChat();
  try {
    state.session = await api(`/sessions/${state.session.id}/turn`, {method:"POST",body:JSON.stringify({text:state.pendingTurn.text,request_id:state.pendingTurn.requestId, control:state.pendingTurn.control || 'answer'})});
    clearPending();
  } catch (_) { $("#network-note").classList.remove("hidden"); }
  finally { setWaiting(false); renderChat(); }
}
async function resume() {
  const id = localStorage.getItem("interview-builder-id"); if (!id) return;
  try {
    state.session = await api(`/sessions/${id}`);
    try { state.pendingTurn = JSON.parse(localStorage.getItem(storageKey('pending')) || 'null'); } catch (_) { state.pendingTurn=null; }
    if (state.pendingTurn && state.session.processed_turn_ids.includes(state.pendingTurn.requestId)) clearPending();
    if (!state.pendingTurn && state.session.pending_turn) { const p=state.session.pending_turn; state.pendingTurn={text:p.text,requestId:p.id,control:p.control || 'answer'}; }
    hide('#consent'); hide('#pre-form'); hide('#complete'); reveal('#chat'); renderChat();
    $('#message-input').value=localStorage.getItem(storageKey('draft')) || '';
    if (state.pendingTurn && state.session.status==='active') reveal('#network-note');
  } catch (error) {
    if (error.status === 404) {
      // A retired/deleted session must never strand a participant on a blank
      // page. Forget only the obsolete resume pointer and restart safely at
      // informed consent; no server-side interview data is modified.
      localStorage.removeItem('interview-builder-id');
      state.session = null;
      state.pendingTurn = null;
      hide('#resume-error');
      hide('#pre-form');
      hide('#chat');
      hide('#complete');
      reveal('#consent');
    } else {
      hide('#consent');
      reveal('#resume-error');
    }
  }
}

async function showDashboard() {
  hide("#participant"); reveal("#dashboard");
  try { const staff = await api("/auth/me"); await dashboardHome(staff); } catch (_) { reveal("#staff-login"); }
}
async function dashboardHome(staff) {
  hide("#staff-login"); reveal("#staff-home"); $("#staff-name").textContent = `${staff.username} · ${staff.role === "admin" ? "مدیر پژوهش" : "عضو تیم"}`;
  document.body.dataset.staffRole = staff.role;
  window.currentStaff = staff;
  window.dispatchEvent(new CustomEvent('interview-builder-staff-ready', {detail: staff}));
  $("#export-data").classList.toggle("hidden", staff.role !== "admin");
  $("#export-csv").classList.toggle("hidden", staff.role !== "admin");
  $("#export-architecture").classList.toggle("hidden", staff.role !== "admin");
  const sessions = await api("/admin/sessions");
  const completed = sessions.filter(s => s.status === "completed").length;
  const labels={active:'در جریان',completed:'کامل',withdrawn:'پایان به درخواست فرد',interrupted:'اختلال فنی',ended_unknown:'پایان قدیمی — نامشخص'};
  $("#metrics").innerHTML = Object.entries(labels).map(([key,label])=>`<div class="metric"><strong>${sessions.filter(s=>s.status===key).length}</strong><span>${label}</span></div>`).join('');
  $("#session-list").innerHTML = sessions.length ? `<p class="muted small export-hint">برای خروجیِ منتخب، موارد دلخواه را تیک بزنید؛ با «لغو انتخاب‌ها» همیشه همهٔ مصاحبه‌ها دانلود می‌شوند.</p><div class="export-controls"><button id="select-all-sessions" class="secondary" type="button">انتخاب همه</button><button id="clear-session-selection" class="quiet" type="button">لغو انتخاب‌ها / خروجی همه</button><span id="export-selection-status" class="export-selection-status">خروجی: همهٔ ${sessions.length} مصاحبه</span></div>${sessions.map(s => `<div class="session-row"><label class="session-check"><input type="checkbox" value="${s.id}" aria-label="انتخاب این مصاحبه برای خروجی"></label><button class="session" data-id="${s.id}"><strong>${escapeHtml(s.occupation || "مشارکت‌کننده")}</strong><small>${labels[s.status] || escapeHtml(s.status)} · ${s.message_count} پیام</small><small>${new Date(s.updated_at).toLocaleString("fa-IR")}</small></button></div>`).join("")}` : `<p class="muted">هنوز مصاحبه‌ای ثبت نشده است.</p>`;
  updateExportSelectionStatus();
}
async function loadTranscript(id, button) {
  const data = await api(`/admin/sessions/${id}`); document.querySelectorAll(".session").forEach(el => el.classList.remove("active")); button.classList.add("active"); hide("#transcript-empty"); reveal("#transcript");
  const pre = Object.entries(data.pre_interview || {}).map(([key,value])=>`<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value || 'ثبت نشده')}</dd>`).join('');
  $("#transcript").innerHTML = `<p class="muted small">شناسه: ${escapeHtml(data.id)} · ${escapeHtml(data.status)}</p>${pre ? `<details class="pre-results"><summary>پاسخ‌های فرم پیش از مصاحبه</summary><dl>${pre}</dl></details>` : ''}${data.messages.map(message => `<div data-turn="${escapeHtml(message.turn_id || '')}" class="message ${message.role === "user" ? "user" : "assistant"}">${escapeHtml(message.content)}</div>`).join("")}`;
  window.dispatchEvent(new CustomEvent('transcript-loaded',{detail:data}));
}

$("#consent-check").addEventListener("change", e => $("#consent-next").disabled = !e.target.checked);
$("#consent-next").addEventListener("click", async () => {
  const button = $("#consent-next"); button.disabled = true;
  try { await loadPreInterviewForm(); hide("#consent"); if (visiblePreQuestions().length) { reveal("#pre-form"); renderStep(); } else { startInterview(); } }
  catch (error) { alert(error.message); }
  finally { button.disabled = !$("#consent-check").checked; }
});
$("#pre-next").addEventListener("click", () => { if (!collectStep()) return; const questions = visiblePreQuestions(); if (state.step < questions.length - 1) { state.step += 1; renderStep(); } else startInterview(); });
$("#pre-back").addEventListener("click", () => { collectStep(); state.step = Math.max(0, state.step - 1); renderStep(); });
$("#message-form").addEventListener("submit", event => { event.preventDefault(); submitAnswer($('#message-input').value.trim()); });
$("#message-input").addEventListener('input',()=>{ if(state.session) { try { localStorage.setItem(storageKey('draft'),$('#message-input').value); } catch(_) {} } });
$("#message-input").addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submitAnswer($('#message-input').value.trim());
  }
});
$("#choice-form").addEventListener("click", event => { const button = event.target.closest("[data-choice]"); if (button) submitAnswer((state.session.current_choices || [])[Number(button.dataset.choice)]); });
$('#choice-form').addEventListener('submit',event=>{event.preventDefault(); const choices=state.session.current_choices; submitAnswer([...document.querySelectorAll('#choice-form input:checked')].map(input=>choices[Number(input.value)]).join('\n'));});
$('#clarify-question').addEventListener('click',()=>submitAnswer('لطفاً این سؤال را ساده‌تر بپرسید.','clarify'));
$('#skip-question').addEventListener('click',()=>submitAnswer('بریم سؤال بعد','skip'));
$('#resume-interrupted').addEventListener('click',async()=>{try { state.session=await api(`/sessions/${state.session.id}/resume`,{method:'POST'}); await resume(); } catch(error) { alert(error.message); }});
$('#resume-again').addEventListener('click',()=>{hide('#resume-error'); resume();});
$("#retry-send").addEventListener("click", retryPendingTurn);
$("#end-interview").addEventListener("click", async () => { if (state.session && confirm("آیا از پایان گفت‌وگو مطمئن هستید؟")) { state.session = await api(`/sessions/${state.session.id}/finish`, {method:"POST"}); renderChat(); } });
$("#login-form").addEventListener("submit", async event => { event.preventDefault(); $("#login-error").textContent=""; try { const staff=await api("/auth/login",{method:"POST",body:JSON.stringify({username:$("#username").value,password:$("#password").value})}); await dashboardHome(staff); } catch(error) { $("#login-error").textContent=error.message; } });
$("#session-list").addEventListener("click", event => {
  if (event.target.closest("#select-all-sessions")) { document.querySelectorAll('.session-check input').forEach(input => input.checked = true); updateExportSelectionStatus(); return; }
  if (event.target.closest("#clear-session-selection")) { document.querySelectorAll('.session-check input').forEach(input => input.checked = false); updateExportSelectionStatus(); return; }
  const button=event.target.closest("[data-id]"); if(button) loadTranscript(button.dataset.id,button);
});
$("#session-list").addEventListener("change", event => { if (event.target.matches('.session-check input')) updateExportSelectionStatus(); });
$("#logout").addEventListener("click", async () => { await api("/auth/logout",{method:"POST"}); location.href="/"; });
function selectedSessionIds() { return [...document.querySelectorAll('.session-check input:checked')].map(input => input.value); }
function updateExportSelectionStatus() { const status = $('#export-selection-status'); if (!status) return; const total = document.querySelectorAll('.session-check input').length, selected = selectedSessionIds().length; status.textContent = selected ? `خروجی: ${selected} مصاحبهٔ منتخب` : `خروجی: همهٔ ${total} مصاحبه`; }
function setExportFeedback(message='', state='') { const feedback=$('#export-feedback'); feedback.textContent=message; feedback.dataset.state=state; feedback.classList.toggle('hidden', !message); }
function downloadBlob(blob, filename) { const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=filename; a.style.display='none'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url), 30000); }
function exportButtons(disabled) { ['#export-data','#export-csv','#export-architecture'].forEach(id => { const button=$(id); if (button) button.disabled=disabled; }); }
async function exportJson() { exportButtons(true); setExportFeedback('در حال آماده‌سازی فایل JSON…'); try { const data=await api('/admin/export.json',{method:'POST',body:JSON.stringify({session_ids:selectedSessionIds()})}); downloadBlob(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),`interviews-${new Date().toISOString().slice(0,10)}.json`); setExportFeedback(`${data.length} مصاحبه در فایل JSON آمادهٔ دانلود شد.`, 'success'); } catch(error) { setExportFeedback(`دانلود JSON انجام نشد: ${error.message}`, 'error'); } finally { exportButtons(false); } }
async function exportCsv() { exportButtons(true); setExportFeedback('در حال آماده‌سازی فایل CSV…'); try { const response=await fetch('/admin/export.csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_ids:selectedSessionIds()})}); if(!response.ok) { const data=await response.json().catch(()=>({})); throw new Error(data.detail || 'خروجی CSV آماده نشد'); } downloadBlob(await response.blob(),`interviews-${new Date().toISOString().slice(0,10)}.csv`); setExportFeedback('فایل CSV آمادهٔ دانلود شد.', 'success'); } catch(error) { setExportFeedback(`دانلود CSV انجام نشد: ${error.message}`, 'error'); } finally { exportButtons(false); } }
async function exportArchitectureCsv() { exportButtons(true); setExportFeedback('در حال آماده‌سازی گزارش مسیر اجرا…'); try { const response=await fetch('/admin/export.architecture.csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_ids:selectedSessionIds()})}); if(!response.ok) { const data=await response.json().catch(()=>({})); throw new Error(data.detail || 'گزارش مسیر اجرا آماده نشد'); } downloadBlob(await response.blob(),`architecture-events-${new Date().toISOString().slice(0,10)}.csv`); setExportFeedback('گزارش مسیر اجرا آمادهٔ دانلود شد.', 'success'); } catch(error) { setExportFeedback(`دانلود گزارش انجام نشد: ${error.message}`, 'error'); } finally { exportButtons(false); } }
$("#export-data").addEventListener("click", exportJson);
$("#export-csv").addEventListener("click", exportCsv);
$("#export-architecture").addEventListener("click", exportArchitectureCsv);

if (new URLSearchParams(location.search).get("view") === "team") showDashboard(); else { showParticipant(); loadProject().catch(() => {}); resume(); }
