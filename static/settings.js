// Privileged data is fetched only after server-side administrator authorization.
let settingsBaseVersion = 0;
let previewSession = null;
let previewBusy = false;
const settingsButton = document.createElement('button');
settingsButton.className = 'secondary hidden';
settingsButton.textContent = 'تنظیمات مصاحبه';
document.querySelector('#export-data').before(settingsButton);
const preInterviewFormButton = document.createElement('button');
preInterviewFormButton.className = 'secondary hidden';
preInterviewFormButton.textContent = 'فرم پیش از مصاحبه';
preInterviewFormButton.title = 'ویرایش مستقیم فرم پیش از مصاحبه';
settingsButton.after(preInterviewFormButton);
const settingsPanel = document.createElement('section');
settingsPanel.className = 'card hidden';
settingsPanel.style.marginBottom = '24px';
settingsPanel.innerHTML = `
  <h2>ساخت و انتشار پروتکل</h2>
  <p class="muted">این پروژه از محتوای آماده شروع نمی‌کند. ابتدا عنوان، متن رضایت، دستورالعمل‌ها و پرسش‌های خودتان را تکمیل کنید؛ سپس یک نسخه منتشر کنید. انتشار فقط بر مصاحبه‌های جدید اثر دارد.</p>
  <p id="settings-version" class="muted"></p>
  <nav class="settings-jump-nav" aria-label="بخش‌های تنظیمات">
    <button type="button" class="quiet" data-settings-jump="settings-core">پروژه، مدل و دستورالعمل‌ها</button>
    <button type="button" class="quiet" data-settings-jump="settings-questionnaire">پرسش‌های مصاحبه</button>
    <button type="button" class="primary" data-settings-jump="settings-pre-form">فرم پیش از مصاحبه</button>
  </nav>
  <form id="settings-form">
    <section id="settings-core"><div class="field"><label for="config-project-title">عنوان پروژه</label><input id="config-project-title" name="project_title" required maxlength="200"></div>
    <div class="field"><label for="config-participant-language">زبان مصاحبه</label><input id="config-participant-language" name="participant_language" required maxlength="80" placeholder="مثلاً: فارسی رسمی ایران"></div>
    <div class="field"><label for="config-welcome-text">متن خوش‌آمدگویی</label><textarea id="config-welcome-text" name="welcome_text" rows="4" required minlength="10"></textarea></div>
    <div class="field"><label for="config-consent-text">متن رضایت و حریم خصوصی</label><textarea id="config-consent-text" name="consent_text" rows="4" required minlength="10"></textarea></div>
    <div class="field"><label for="config-model">شناسه مدل در سرویس فعلی</label><input id="config-model" name="model" required maxlength="200" dir="ltr"></div>
    <div class="field"><label for="config-architecture">معماری اصلی</label><select id="config-architecture" name="architecture"><option value="simple_adaptive">Simple Adaptive — یک عامل، پاسخ‌گو و سریع</option><option value="multi_agent_lite">Multi-agent Lite — مدیر و مصاحبه‌گر جدا</option><option value="conversational_lead">Conversational Lead — خودمختاری بیشتر در پیگیری</option></select></div>
    <div class="field"><label for="config-lite">مهلت هر فراخوانی Lite (ثانیه)</label><input id="config-lite" name="lite_timeout" type="number" min="6" max="30" required></div>
    <div class="field"><label for="config-fast">مهلت Fast Guided (ثانیه)</label><input id="config-fast" name="fast_timeout" type="number" min="6" max="30" required></div>
    ${[['base_prompt','دستورالعمل عمومی و اصول حرفه‌ای'],['planner_prompt','Lite — مدیر گفت‌وگو و منطق پیگیری'],['interviewer_prompt','مصاحبه‌گر — لحن و متن روبه‌مشارکت‌کننده'],['fast_prompt','Simple Adaptive — تصمیم و متن سریع'],['lead_prompt','Conversational Lead — دستورالعمل پیگیری خودمختار']].map(([name,label]) => `<div class="field"><label for="config-${name}">${label}</label><textarea id="config-${name}" name="${name}" rows="8" required minlength="20"></textarea></div>`).join('')}</section>
    <section id="settings-questionnaire"><h3>پرسشنامه و منطق مصاحبه</h3><p class="muted small">آخرین پرسش، دعوت پایانی باز با پیگیری صفر است. انشعاب تک‌گزینه‌ای فقط به پرسش‌های بعدی مجاز است.</p><div id="questionnaire-editor"></div><button type="button" id="add-question" class="secondary">افزودن پرسش پیش از دعوت پایانی</button></section>
    <details id="settings-pre-form" class="pre-form-settings" open><summary><strong>فرم پیش از مصاحبه (اختیاری)</strong></summary><p class="muted small">در پروژهٔ تازه، فرم خالی است. در صورت نیاز، پرسش‌های اطلاعات اولیه را خودتان اضافه کنید و منطق نمایش مشروط را تنظیم کنید.</p><div id="pre-interview-editor"></div><div class="actions"><button type="button" id="add-pre-question" class="secondary">افزودن پرسش فرم</button><button type="button" id="restore-pre-defaults" class="quiet">پاک‌کردن فرم</button></div></details>
    <p class="muted small">ساختار JSON و نام اقدامات مدیر گفت‌وگو و مسیر سریع را حفظ کنید.</p>
    <div class="actions"><button class="secondary" type="submit">ذخیره پیش‌نویس</button><button class="secondary" id="settings-test" type="button">آزمون پیش‌نویس</button><button class="primary" id="settings-publish" type="button">انتشار برای مصاحبه‌های جدید</button></div>
  </form>
  <p id="settings-note" role="status"></p>
  <details><summary>تاریخچه نسخه‌ها و بازگردانی</summary><div id="settings-history"></div></details>
  <section id="settings-preview" class="hidden"><h3>گفت‌وگوی آزمایشی</h3><p class="muted">این آزمون از اعتبار API استفاده می‌کند و در آرشیو پژوهش وارد نمی‌شود. تغییر فرم به آزمون جاری منتقل نمی‌شود؛ برای آزمون تغییرات، آزمون تازه بسازید.</p><div id="preview-messages" class="messages"></div><form id="preview-form" class="composer"><textarea aria-label="پاسخ آزمایشی" id="preview-input" required></textarea><button class="primary">ارسال</button></form></section>`;
document.querySelector('#metrics').before(settingsPanel);
settingsPanel.querySelector('.actions').style.flexWrap = 'wrap';
document.querySelector('#staff-home .dashboard-head .actions').style.flexWrap = 'wrap';
document.querySelector('#config-model').style.direction = 'ltr';
document.querySelector('#config-model').style.textAlign = 'left';

function settingsNote(text) { document.querySelector('#settings-note').textContent = text; }
function fillSettings(config) {
  questionnaireDraft = structuredClone(config.questionnaire || []);
  preInterviewDraft = structuredClone(config.pre_interview_form || []);
  renderQuestionnaire();
  renderPreInterviewForm();
  for (const [key,value] of Object.entries(config)) {
    const field = document.querySelector('#settings-form').elements.namedItem(key);
    if (field) field.value = value;
  }
}
function editedSettings() {
  const form = document.querySelector('#settings-form');
  if (!form.reportValidity()) throw new Error('لطفاً فیلدهای مشخص‌شده را کامل کنید');
  const result = Object.fromEntries(new FormData(form));
  result.lite_timeout = Number(result.lite_timeout);
  result.fast_timeout = Number(result.fast_timeout);
  result.based_on = settingsBaseVersion;
  collectQuestionnaire(); result.questionnaire = questionnaireDraft;
  collectPreInterviewForm(); result.pre_interview_form = preInterviewDraft;
  return result;
}
function jumpToSettingsSection(sectionId) {
  const section = document.querySelector(`#${sectionId}`);
  if (!section) return;
  if (section.tagName === 'DETAILS') section.open = true;
  section.classList.remove('settings-target');
  // Restart the brief highlight when the same destination is selected twice.
  void section.offsetWidth;
  section.classList.add('settings-target');
  section.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function openSettings(sectionId = null) {
  try {
    const data = await api('/admin/settings');
    settingsBaseVersion = data.version;
    fillSettings(data.draft || data.settings);
    // Preserve stale draft ancestry so publishing cannot overwrite another admin.
    if (data.draft) settingsBaseVersion = data.draft.based_on;
    document.querySelector('#settings-version').textContent = `نسخه منتشرشده: ${data.version} · ${data.draft ? 'پیش‌نویس شما بازیابی شد' : 'ویرایش نسخه جاری'}`;
    document.querySelector('#settings-history').innerHTML = data.history.map(item => `<p>نسخه ${item.version} · ${escapeHtml(item.author)} · ${escapeHtml(item.created_at)} <button type="button" class="secondary" data-version="${item.version}">بارگذاری در ویرایشگر</button></p>`).join('') || '<p>هنوز نسخه‌ای منتشر نشده است.</p>';
    settingsPanel.classList.remove('hidden');
    if (sectionId) requestAnimationFrame(() => jumpToSettingsSection(sectionId));
  } catch(error) { alert(error.message); }
}
settingsButton.addEventListener('click', () => settingsPanel.classList.contains('hidden') ? openSettings() : settingsPanel.classList.add('hidden'));
preInterviewFormButton.addEventListener('click', () => openSettings('settings-pre-form'));
settingsPanel.querySelector('.settings-jump-nav').addEventListener('click', event => {
  const button = event.target.closest('[data-settings-jump]');
  if (button) jumpToSettingsSection(button.dataset.settingsJump);
});
new MutationObserver(() => {
  const hidden = document.querySelector('#export-data').classList.contains('hidden');
  settingsButton.classList.toggle('hidden', hidden);
  preInterviewFormButton.classList.toggle('hidden', hidden);
}).observe(document.querySelector('#export-data'), {attributes:true, attributeFilter:['class']});
document.querySelector('#settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await api('/admin/settings/draft', {method:'PUT', body:JSON.stringify(editedSettings())}); settingsNote('پیش‌نویس ذخیره شد؛ مصاحبه عمومی تغییر نکرد.'); } catch(error) { settingsNote(error.message); }
});
document.querySelector('#settings-publish').addEventListener('click', async () => {
  const button = document.querySelector('#settings-publish');
  try {
    const config = editedSettings();
    if (!confirm('این تنظیمات برای همه مصاحبه‌های جدید منتشر شود؟')) return;
    button.disabled = true;
    const result = await api('/admin/settings/publish', {method:'POST', body:JSON.stringify(config)});
    await openSettings(); settingsNote(`نسخه ${result.version} منتشر شد. مصاحبه‌های در جریان تغییری نمی‌کنند.`);
  } catch(error) { settingsNote(error.message); } finally { button.disabled = false; }
});
document.querySelector('#settings-history').addEventListener('click', async event => {
  const button = event.target.closest('[data-version]'); if (!button) return;
  try { fillSettings(await api(`/admin/settings/versions/${button.dataset.version}`)); settingsBaseVersion = (await api('/admin/settings')).version; settingsNote('نسخه قبلی در ویرایشگر بارگذاری شد؛ برای فعال‌کردن آن انتشار را بزنید.'); } catch(error) { settingsNote(error.message); }
});
function renderPreview() {
  document.querySelector('#preview-messages').innerHTML = previewSession.messages.map(message => `<div class="message ${message.role === 'user' ? 'user' : 'assistant'}">${escapeHtml(message.content)}</div>`).join('');
  document.querySelector('#preview-form').classList.toggle('hidden', previewSession.status !== 'active');
}
document.querySelector('#settings-test').addEventListener('click', async () => {
  if (previewBusy) return;
  try { previewSession = await api('/admin/settings/test', {method:'POST', body:JSON.stringify(editedSettings())}); document.querySelector('#settings-preview').classList.remove('hidden'); renderPreview(); settingsNote('آزمون تازه با پیش‌نویس فعلی آماده شد.'); } catch(error) { settingsNote(error.message); }
});
document.querySelector('#preview-form').addEventListener('submit', async event => {
  event.preventDefault(); if (previewBusy || !previewSession) return;
  const input = document.querySelector('#preview-input');
  const text = input.value.trim(); if (!text) return;
  previewBusy = true; input.disabled = true; settingsNote('مصاحبه‌گر در حال نوشتن است…');
  try { previewSession = await api(`/sessions/${previewSession.id}/turn`, {method:'POST', body:JSON.stringify({text,request_id:crypto.randomUUID()})}); input.value = ''; renderPreview(); settingsNote('پاسخ آزمون دریافت شد.'); } catch(error) { settingsNote(error.message); } finally { previewBusy = false; input.disabled = false; }
});
