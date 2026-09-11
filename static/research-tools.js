let questionnaireDraft = [];
let preInterviewDraft = [];

function preQuestionOptionLines(question) { return (question.options || []).join('\n'); }
function renderPreInterviewForm() {
  const editor = $('#pre-interview-editor');
  if (!editor) return;
  editor.innerHTML = preInterviewDraft.map((question, index) => `<details class="question-edit pre-question-edit" data-pre-index="${index}"><summary>${index + 1}. ${escapeHtml(question.text)}</summary>
    <div class="field"><label>شناسهٔ ثابت<input data-pre="id" value="${escapeHtml(question.id)}" required maxlength="40" pattern="[A-Za-z][A-Za-z0-9_-]{0,39}"></label></div>
    <div class="field"><label>بخش فرم<input data-pre="section" value="${escapeHtml(question.section)}" required maxlength="200"></label></div>
    <div class="field"><label>متن کامل پرسش<textarea data-pre="text" rows="2" required>${escapeHtml(question.text)}</textarea></label></div>
    <div class="field"><label>نوع پاسخ<select data-pre="kind">${[['single','تک‌گزینه‌ای'],['multiple','چندگزینه‌ای'],['text','متن آزاد']].map(([value, label]) => `<option value="${value}" ${question.kind === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label></div>
    ${question.kind !== 'text' ? `<div class="field"><label>گزینه‌ها — هر گزینه در یک خط<textarea data-pre="options" rows="5" required>${escapeHtml(preQuestionOptionLines(question))}</textarea></label></div>` : `<div class="field"><label>راهنمای پاسخ<input data-pre="placeholder" value="${escapeHtml(question.placeholder || '')}" placeholder="مثلاً: پزشک، معلم، دانشجو"></label></div>`}
    <div class="field"><label>نمایش در صورت پاسخ به پرسش پیشین<select data-pre="visible_if_id"><option value="">همیشه نمایش بده</option>${preInterviewDraft.slice(0, index).map(previous => `<option value="${escapeHtml(previous.id)}" ${question.visible_if_id === previous.id ? 'selected' : ''}>${escapeHtml(previous.id)} — ${escapeHtml(previous.text)}</option>`).join('')}</select></label></div>
    ${question.visible_if_id ? `<div class="field"><label>پاسخ یا پاسخ‌های مجاز برای نمایش — هر مورد در یک خط<textarea data-pre="visible_if_answers" rows="2" required>${escapeHtml((question.visible_if_answers || []).join('\n'))}</textarea></label></div>` : ''}
    <div class="actions"><label class="check"><input data-pre="required" type="checkbox" ${question.required ? 'checked' : ''}><span>پاسخ الزامی است</span></label>${question.kind === 'multiple' ? `<label class="check"><input data-pre="allows_other" type="checkbox" ${question.allows_other ? 'checked' : ''}><span>گزینهٔ «دیگر» داشته باشد</span></label>` : ''}</div>
    <div class="actions"><button class="secondary" type="button" data-pre-move="-1" ${index === 0 ? 'disabled' : ''}>بالاتر</button><button class="secondary" type="button" data-pre-move="1" ${index === preInterviewDraft.length - 1 ? 'disabled' : ''}>پایین‌تر</button><button class="quiet" type="button" data-pre-delete ${preInterviewDraft.length === 1 ? 'disabled' : ''}>حذف از پیش‌نویس</button></div>
  </details>`).join('');
}
function collectPreInterviewForm() {
  document.querySelectorAll('.pre-question-edit').forEach(box => {
    const question = preInterviewDraft[Number(box.dataset.preIndex)];
    box.querySelectorAll('[data-pre]').forEach(input => {
      const key = input.dataset.pre;
      if (key === 'required' || key === 'allows_other') question[key] = input.checked;
      else if (key === 'options' || key === 'visible_if_answers') question[key] = input.value.split('\n').map(value => value.trim()).filter(Boolean);
      else question[key] = input.value.trim();
    });
    if (question.kind === 'text') { question.options = []; question.allows_other = false; }
    if (question.kind !== 'multiple') question.allows_other = false;
    if (!question.visible_if_id) question.visible_if_answers = [];
  });
}
$('#pre-interview-editor').addEventListener('change', event => {
  if (!event.target.dataset.pre || !['kind', 'visible_if_id'].includes(event.target.dataset.pre)) return;
  const box = event.target.closest('[data-pre-index]');
  collectPreInterviewForm(); renderPreInterviewForm();
  document.querySelector(`.pre-question-edit[data-pre-index="${box.dataset.preIndex}"]`).open = true;
});
$('#pre-interview-editor').addEventListener('click', event => {
  const button = event.target.closest('[data-pre-move], [data-pre-delete]');
  if (!button) return;
  collectPreInterviewForm();
  const index = Number(button.closest('[data-pre-index]').dataset.preIndex);
  if (button.hasAttribute('data-pre-delete')) preInterviewDraft.splice(index, 1);
  else { const target = index + Number(button.dataset.preMove); [preInterviewDraft[index], preInterviewDraft[target]] = [preInterviewDraft[target], preInterviewDraft[index]]; }
  renderPreInterviewForm();
});
$('#add-pre-question').addEventListener('click', () => {
  collectPreInterviewForm();
  preInterviewDraft.push({id: `P_${crypto.randomUUID().slice(0, 8)}`, section: 'بخش جدید', text: 'متن پرسش جدید', kind: 'single', options: ['گزینه اول', 'گزینه دوم'], required: true, allows_other: false, placeholder: '', visible_if_id: null, visible_if_answers: []});
  renderPreInterviewForm();
});
$('#restore-pre-defaults').addEventListener('click', async () => {
  if (!confirm('همهٔ پرسش‌های فرم پیش از مصاحبه از پیش‌نویس حذف شوند؟')) return;
  preInterviewDraft = []; renderPreInterviewForm(); settingsNote('فرم در پیش‌نویس خالی شد. برای اعمال عمومی، سپس «انتشار» را بزنید.');
});
function renderQuestionnaire() {
  $('#questionnaire-editor').innerHTML = questionnaireDraft.map((q,index)=>`<details class="question-edit" data-index="${index}"><summary>${index+1}. ${escapeHtml(q.text)}</summary>
    <p class="muted small">شناسه ثابت: ${escapeHtml(q.id)}</p>
    <div class="field"><label>متن پرسش<textarea data-q="text" rows="2" required>${escapeHtml(q.text)}</textarea></label></div>
    <div class="field"><label>هدف و کفایت پاسخ<textarea data-q="goal" rows="2" required>${escapeHtml(q.goal)}</textarea></label></div>
    <div class="field"><label>نوع پاسخ<select data-q="kind">${[['open','باز'],['single','تک‌گزینه‌ای'],['multiple','چندگزینه‌ای']].map(([v,t])=>`<option value="${v}" ${q.kind===v?'selected':''}>${t}</option>`).join('')}</select></label></div>
    <div class="field"><label>سقف پیگیری<input data-q="probe_limit" type="number" min="0" max="5" value="${q.probe_limit}" required></label></div>
    ${q.kind!=='open'?`<div class="field"><label>گزینه‌ها — هر گزینه در یک خط<textarea data-q="options" rows="4">${escapeHtml(q.options.join('\n'))}</textarea></label></div>`:''}
    ${q.kind==='single'?q.options.map((option,oi)=>`<div class="field"><label>پس از «${escapeHtml(option)}»<select data-branch="${oi}"><option value="">پرسش بعدی</option>${questionnaireDraft.slice(index+1).map(target=>`<option value="${escapeHtml(target.id)}" ${q.branches?.[option]===target.id?'selected':''}>${escapeHtml(target.text)}</option>`).join('')}</select></label></div>`).join(''):''}
    <div class="actions"><button class="secondary" type="button" data-move="-1" ${index===0 || index===questionnaireDraft.length-1?'disabled':''}>بالاتر</button><button class="secondary" type="button" data-move="1" ${index>=questionnaireDraft.length-2?'disabled':''}>پایین‌تر</button><button class="quiet" type="button" data-delete ${index===questionnaireDraft.length-1?'disabled':''}>حذف از پیش‌نویس</button></div></details>`).join('');
}
function collectQuestionnaire() {
  document.querySelectorAll('.question-edit').forEach(box=>{
    const q=questionnaireDraft[Number(box.dataset.index)];
    box.querySelectorAll('[data-q]').forEach(input=>{const k=input.dataset.q; q[k]= k==='probe_limit'?Number(input.value):k==='options'?input.value.split('\n').map(x=>x.trim()).filter(Boolean):input.value;});
    q.branches={}; if(q.kind==='single') box.querySelectorAll('[data-branch]').forEach(select=>{if(select.value && q.options[Number(select.dataset.branch)]) q.branches[q.options[Number(select.dataset.branch)]]=select.value;});
    if(q.kind==='open') q.options=[];
  });
}
$('#questionnaire-editor').addEventListener('change',event=>{
  if(['kind','options'].includes(event.target.dataset.q)) {const idx=event.target.closest('[data-index]').dataset.index;collectQuestionnaire();renderQuestionnaire();document.querySelector(`.question-edit[data-index="${idx}"]`).open=true;}
});
$('#questionnaire-editor').addEventListener('click',event=>{
  const button=event.target.closest('[data-move],[data-delete]'); if(!button)return;
  collectQuestionnaire();const index=Number(button.closest('[data-index]').dataset.index);
  if(button.hasAttribute('data-delete')) questionnaireDraft.splice(index,1);
  else {const dest=index+Number(button.dataset.move);[questionnaireDraft[index],questionnaireDraft[dest]]=[questionnaireDraft[dest],questionnaireDraft[index]];}
  renderQuestionnaire();
});
$('#add-question').addEventListener('click',()=>{collectQuestionnaire();questionnaireDraft.splice(Math.max(0,questionnaireDraft.length-1),0,{id:'Q_'+crypto.randomUUID().slice(0,8),text:'پرسش جدید',goal:'هدف این پرسش را توضیح دهید',kind:'open',options:[],probe_limit:1,branches:{}});renderQuestionnaire();});

const backupButton=document.createElement('button');backupButton.className='secondary hidden';backupButton.textContent='پشتیبان‌گیری';$('#export-data').before(backupButton);
const backupPanel=document.createElement('section');backupPanel.className='card hidden';backupPanel.innerHTML='<h2>پشتیبان‌گیری و بازیابی</h2><p class="muted">هر روز یک نسخه کامل با بررسی سلامت پایگاه داده ذخیره می‌شود. برای محافظت در برابر از دست رفتن دیسک، نسخه را دانلود و خارج از لیارا نگهداری کنید.</p><button class="primary" id="backup-now">ساخت نسخه و بررسی سلامت</button><p id="backup-note" role="status"></p><div id="backup-list"></div>';$('#metrics').before(backupPanel);
new MutationObserver(()=>backupButton.classList.toggle('hidden',$('#export-data').classList.contains('hidden'))).observe($('#export-data'),{attributes:true,attributeFilter:['class']});
async function refreshBackups(){const data=await api('/admin/backups');$('#backup-list').innerHTML=data.map(b=>`<div class="question-edit"><span>${escapeHtml(b.created_at)} · ${Math.round(b.bytes/1024)} KB</span><div class="actions"><a class="secondary" href="/admin/backups/${encodeURIComponent(b.name)}/download">دانلود</a><button class="secondary" data-restore="${escapeHtml(b.name)}">بررسی بازیابی مصاحبه‌های مفقود</button></div></div>`).join('')||'<p>هنوز نسخه‌ای وجود ندارد.</p>';}
backupButton.addEventListener('click',async()=>{backupPanel.classList.toggle('hidden');try{await refreshBackups();}catch(e){$('#backup-note').textContent=e.message;}});
$('#backup-now').addEventListener('click',async()=>{const b=$('#backup-now');b.disabled=true;try{const r=await api('/admin/backups',{method:'POST'});$('#backup-note').textContent=`نسخه سالم ساخته شد. SHA-256: ${r.sha256}`;await refreshBackups();}catch(e){$('#backup-note').textContent=e.message;}finally{b.disabled=false;}});
$('#backup-list').addEventListener('click',async event=>{const b=event.target.closest('[data-restore]');if(!b)return;b.disabled=true;try{const path='/admin/backups/'+encodeURIComponent(b.dataset.restore);const p=await api(path+'/restore-preview');if(!p.missing_interviews){$('#backup-note').textContent='مصاحبه مفقودی برای بازیابی وجود ندارد.';return;}if(confirm(`${p.missing_interviews} مصاحبه مفقود بازیابی شود؟ ${p.existing_preserved} مصاحبه موجود بدون تغییر باقی می‌مانند.`)){const r=await api(path+'/restore-missing',{method:'POST'});$('#backup-note').textContent=`${r.missing_interviews} مصاحبه بازیابی شد. پیش از بازیابی نیز پشتیبان ساخته شد.`;await refreshBackups();}}catch(e){$('#backup-note').textContent=e.message;}finally{b.disabled=false;}});

let reviewedTranscript=null;
const reviews=document.createElement('section');reviews.className='hidden';$('#transcript').after(reviews);
async function renderReviews(){const data=await api(`/admin/reviews/${reviewedTranscript.id}`);const turns=[...new Map(reviewedTranscript.messages.filter(m=>m.turn_id).map(m=>[m.turn_id,m.content])).entries()];reviews.innerHTML=`<h3>بازبینی پژوهشگر</h3><p class="muted small">پرچم‌ها پیشنهاد بررسی هستند و به معنی شکست قطعی مصاحبه نیستند.</p><button class="secondary ${$('#export-data').classList.contains('hidden')?'hidden':''}" id="review-ai">بازبینی با مدل (مصرف اعتبار API)</button><p id="review-note" role="status"></p>${data.suggestions.map(f=>`<p>${escapeHtml(f.note)} <button class="quiet" data-jump="${escapeHtml(f.turn_id||'')}">نمایش نوبت</button></p>`).join('')}${data.notes.map(n=>`<div class="question-edit"><strong>${escapeHtml(n.category)} · ${escapeHtml(n.status)}</strong><p>${escapeHtml(n.note)}</p><small>${escapeHtml(n.author)} · ${escapeHtml(n.source)}</small><div class="actions"><button class="quiet" data-jump="${escapeHtml(n.turn_id||'')}">نمایش نوبت</button><button class="secondary" data-review="${n.id}" data-status="confirmed">تأیید</button><button class="secondary" data-review="${n.id}" data-status="dismissed">رد پرچم</button></div></div>`).join('')}<form id="review-form"><div class="field"><label>نوبت<select name="turn_id"><option value="">کل مصاحبه</option>${turns.map(([id,text])=>`<option value="${escapeHtml(id)}">${escapeHtml(text.slice(0,65))}</option>`).join('')}</select></label></div><div class="field"><label>نوع نکته<select name="category"><option value="repeated_question">تکرار پرسش</option><option value="unnecessary_probe">پیگیری غیرضروری</option><option value="contradiction">تناقض</option><option value="early_ending">پایان زودهنگام</option><option value="other">سایر</option></select></label></div><div class="field"><label>یادداشت<textarea name="note" required minlength="2" maxlength="3000"></textarea></label></div><button class="primary">ثبت یادداشت</button></form>`;reviews.classList.remove('hidden');}
window.addEventListener('transcript-loaded',async event=>{reviewedTranscript=event.detail;try{await renderReviews();}catch(e){reviews.textContent=e.message;}});
reviews.addEventListener('submit',async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));data.turn_id=data.turn_id||null;try{await api(`/admin/reviews/${reviewedTranscript.id}`,{method:'POST',body:JSON.stringify(data)});await renderReviews();}catch(e){$('#review-note').textContent=e.message;}});
reviews.addEventListener('click',async event=>{const b=event.target.closest('button');if(!b)return;try{if(b.dataset.jump){const target=[...document.querySelectorAll('#transcript [data-turn]')].find(x=>x.dataset.turn===b.dataset.jump);if(target){target.scrollIntoView({block:'center'});target.style.outline='2px solid var(--lime)';}}else if(b.dataset.review){await api(`/admin/review-notes/${b.dataset.review}`,{method:'PUT',body:JSON.stringify({status:b.dataset.status})});await renderReviews();}else if(b.id==='review-ai'){b.disabled=true;$('#review-note').textContent='بازبینی در حال انجام است…';await api(`/admin/reviews/${reviewedTranscript.id}/analyze`,{method:'POST'});await renderReviews();}}catch(e){$('#review-note').textContent=e.message;b.disabled=false;}});
