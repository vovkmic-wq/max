"use strict";
let token = "", tab = "channels";
const $ = id => document.getElementById(id);
// Отправляем авторизованный запрос и проверяем безопасный ответ сервера.
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST",
    headers: {Authorization: "Bearer " + token, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const value = await response.json();
  // Проверяем условие перед изменением интерфейса или выполнением действия.
  if (!response.ok) throw new Error(value.code || "Ошибка запроса");
  return value;
}
// Выполняем действие и обновляем данные панели после успеха.
async function action(path, body = {}) {
  // Отображаем ошибку пользователю, сохраняя возможность следующего действия.
  try { $("result").textContent = JSON.stringify(await api(path, body), null, 2); await refresh(); }
  // Показываем безопасный код ошибки без сохранения ключа доступа.
  catch(error) { $("result").textContent = error.message; }
}
// Обновляем вкладку и создаём доступные действия для каждой записи.
async function refresh() {
  // Отображаем ошибку пользователю, сохраняя возможность следующего действия.
  try {
    const rows = await api("/api/v1/" + tab);
    $("content").replaceChildren();
    // Создаём обработчики для каждого доступного действия или элемента.
    for (const row of rows) {
      const card = document.createElement("article"); card.className = "card";
      const pre = document.createElement("pre"); pre.textContent = JSON.stringify(row, null, 2); card.append(pre);
      // Для выбранной вкладки показываем соответствующие действия над записью.
      if (tab === "videos") {
        // Создаём обработчики для каждого доступного действия или элемента.
        for (const [name,label] of [["approve-generation","Одобрить генерацию"],["poll","Проверить результат"],["assemble","Собрать ролик"],["cancel","Остановить проект"]]) {
          const b=document.createElement("button"); b.textContent=label;
          // Связываем действие пользователя с запросом к API проекта.
          b.onclick=()=>action(`/api/v1/videos/${row.id}/${name}`, {revision:row.revision,plan_hash:row.plan_hash});card.append(b);
        }
        const index=document.createElement("input");index.type="number";index.value="0";index.min="0";card.append(index);
        const file=document.createElement("input");file.placeholder="data/incoming/scene.mp4";card.append(file);
        const rights=document.createElement("input");rights.placeholder="Права на сцену";card.append(rights);
        const b=document.createElement("button");b.textContent="Импортировать готовую сцену";
        // Связываем действие пользователя с запросом к API проекта.
        b.onclick=()=>action(`/api/v1/videos/${row.id}/import-scene`,{index:Number(index.value),path:file.value,rights_basis:rights.value});card.append(b);
      }
      // Для выбранной вкладки показываем соответствующие действия над записью.
      if (tab === "source-media") {
        const caption=document.createElement("textarea");caption.placeholder="Русская подпись с подтверждёнными фактами";card.append(caption);
        const b=document.createElement("button");b.textContent="Подготовить подборку";
        // Связываем действие пользователя с запросом к API проекта.
        b.onclick=()=>action("/api/v1/curate",{channel_id:$("channel").value,media_id:row.id,caption:caption.value});card.append(b);
      }
      // Для выбранной вкладки показываем соответствующие действия над записью.
      if (tab === "assets") {
        const b=document.createElement("button");b.textContent="Просмотреть ролик";
        // Связываем действие пользователя с запросом к API проекта.
        b.onclick=async()=>{try {
          const r=await fetch(`/api/v1/assets/${row.id}/preview`,{headers:{Authorization:"Bearer "+token}});
          if(!r.ok)throw new Error("Нет доступа к видео");
          const v=document.createElement("video");v.controls=true;v.width=280;v.src=URL.createObjectURL(await r.blob());
          v.onloadeddata=()=>URL.revokeObjectURL(v.src);card.append(v);b.disabled=true;
        }catch(e){$("status").textContent=e.message;}};card.append(b);
      }
      // Для выбранной вкладки показываем соответствующие действия над записью.
      if (tab === "drafts" && row.state === "published") {
        const caption = document.createElement("textarea"); caption.value = row.current.body; card.append(caption);
        const save = document.createElement("button"); save.textContent = "Исправить опубликованную подпись";
        // Связываем действие пользователя с запросом к API проекта.
        save.onclick = async () => {
          // Отображаем ошибку пользователю, сохраняя возможность следующего действия.
          try {
            const publications = await api("/api/v1/publications");
            const intent = publications.find(p => p.draft_id === row.id && p.state === "confirmed");
            // Проверяем условие перед изменением интерфейса или выполнением действия.
            if (!intent) throw new Error("Подтверждённая публикация не найдена");
            await action("/api/v1/publications/" + intent.id + "/correct", {revision:row.revision,body:caption.value});
          } catch (e) { $("result").textContent = e.message; }
        }; card.append(save);
      }
      // Для выбранной вкладки показываем соответствующие действия над записью.
      if (tab === "drafts" && row.state !== "published") {
        const path = document.createElement("input"); path.placeholder = "data/incoming/clip.mp4"; card.append(path);
        const rights = document.createElement("input"); rights.placeholder = "Основание права на публикацию ролика"; card.append(rights);
        const attach = document.createElement("button"); attach.textContent = "Приложить MP4";
        // Связываем действие пользователя с запросом к API проекта.
        attach.onclick = () => action(`/api/v1/drafts/${row.id}/video`, {path:path.value, rights_basis:rights.value}); card.append(attach);
        const commercial = document.createElement("button"); commercial.textContent = row.commercial ? "Снять коммерческую отметку" : "Коммерческий материал";
        // Связываем действие пользователя с запросом к API проекта.
        commercial.onclick = () => action(`/api/v1/drafts/${row.id}/commercial`, {revision:row.revision, commercial:!row.commercial}); card.append(commercial);
        const edit = document.createElement("textarea"); edit.value = row.current.body; card.append(edit);
        const save = document.createElement("button"); save.textContent = "Сохранить новую ревизию";
        // Связываем действие пользователя с запросом к API проекта.
        save.onclick = () => action(`/api/v1/drafts/${row.id}/revise`, {revision:row.revision, body:edit.value}); card.append(save);
        const approve = document.createElement("button"); approve.textContent = "Одобрить в календарь";
        // Связываем действие пользователя с запросом к API проекта.
        approve.onclick = () => action(`/api/v1/drafts/${row.id}/approve`, {revision:row.revision, content_hash:row.content_hash}); card.append(approve);
        const reject = document.createElement("button"); reject.textContent = "Отклонить";
        // Связываем действие пользователя с запросом к API проекта.
        reject.onclick = () => action(`/api/v1/drafts/${row.id}/reject`, {revision:row.revision}); card.append(reject);
      }
      // Для выбранной вкладки показываем соответствующие действия над записью.
      if (tab === "publications" && ["sending","unknown"].includes(row.state)) {
        const reconcile = document.createElement("button"); reconcile.textContent = "Сверить результат";
        // Связываем действие пользователя с запросом к API проекта.
        reconcile.onclick = () => action(`/api/v1/publications/${row.id}/reconcile`); card.append(reconcile);
      }
      $("content").append(card);
    }
    $("status").textContent = "Подключено. " + rows.length + " записей.";
  } catch(error) { $("status").textContent = error.message; }
}
// Связываем действие пользователя с запросом к API проекта.
$("login").onclick = async () => {token = $("token").value; $("token").value = ""; await loadImageChannels(); await refresh();};
// Связываем действие пользователя с запросом к API проекта.
$("refresh").onclick = refresh;
// Создаём обработчики для каждого доступного действия или элемента.
for (const button of document.querySelectorAll("[data-tab]")) button.onclick = () => {
  tab = button.dataset.tab; $("heading").textContent = button.textContent; refresh();
};
const channelPath = actionName => `/api/v1/channels/${encodeURIComponent($("channel").value)}/${actionName}`;
// Связываем действие пользователя с запросом к API проекта.
$("connect").onclick = () => action(channelPath("connect"), {chat_id:$("chat").value});
// Создаём обработчики для каждого доступного действия или элемента.
for (const name of ["pause","resume","bootstrap"]) $(name).onclick = () => action(channelPath(name));
// Связываем действие пользователя с запросом к API проекта.
$("growth").onclick = () => action(channelPath("growth-plan"));
// Связываем действие пользователя с запросом к API проекта.
$("report").onclick = async () => {try { $("result").textContent = JSON.stringify(await api(`/api/v1/reports/${encodeURIComponent($("channel").value)}`), null, 2); } catch(e) {$("result").textContent=e.message;}};
// Связываем действие пользователя с запросом к API проекта.
$("validate").onclick = () => action("/api/v1/config/validate");
// Связываем действие пользователя с запросом к API проекта.
$("activate").onclick = () => action("/api/v1/config/activate");
// Связываем действие пользователя с запросом к API проекта.
$("generate-plan").onclick=()=>action("/api/v1/videos",{channel_id:$("channel").value,idea:$("video-idea").value});
// Связываем действие пользователя с запросом к API проекта.
$("create-plan").onclick=()=>{try{action("/api/v1/videos",{channel_id:$("channel").value,plan:JSON.parse($("video-plan").value)});}catch(e){$("result").textContent="Ошибка JSON сценария";}};

// Связываем действие пользователя с запросом к API проекта.
$("browser-login").onclick=()=>action("/api/v1/browser/login",{chat_id:$("chat").value});
// Связываем действие пользователя с запросом к API проекта.
$("browser-check").onclick=()=>action("/api/v1/browser/check",{chat_id:$("chat").value});

// Блокируем кнопки на время операции и показываем её результат.
async function imageAction(path, body) {
  const buttons = [...document.querySelectorAll("button[id^='images-']")];
  buttons.forEach(b => b.disabled = true);
  $("images-result").textContent = "Выполняется…";
  // Отображаем ошибку пользователю, сохраняя возможность следующего действия.
  try { $("images-result").textContent = JSON.stringify(await api(path, body), null, 2); }
  // Показываем безопасный код ошибки без сохранения ключа доступа.
  catch (e) { $("images-result").textContent = e.message; }
  // Восстанавливаем доступность кнопок после любого результата.
  finally { buttons.forEach(b => b.disabled = false); }
}
const imageChannel = () => encodeURIComponent($("image-channel").value);
// Связываем действие пользователя с запросом к API проекта.
$("images-status").onclick = () => imageAction("/api/v1/images/status?channel_id=" + imageChannel());
// Связываем действие пользователя с запросом к API проекта.
$("images-scan").onclick = () => imageAction("/api/v1/images/scan", {all_sources:true, channel_id:$("image-channel").value});
// Создаём обработчики для каждого доступного действия или элемента.
for (const name of ["pause", "resume", "tick"])
  // Связываем действие пользователя с запросом к API проекта.
  $("images-" + name).onclick = () => imageAction("/api/v1/images/schedule/" + name + "?channel_id=" + imageChannel(), {});

// Список адресатов строим из профилей проекта; свободный ввод ID не нужен.
async function loadImageChannels() {
  const rows = await api("/api/v1/channel-profiles");
  const select = $("image-channel"), previous = select.value;
  select.replaceChildren();
  // Создаём обработчики для каждого доступного действия или элемента.
  for (const row of rows) {
    // Проверяем условие перед изменением интерфейса или выполнением действия.
    if (row.schedule.state === "not_configured") continue;
    const option = document.createElement("option");
    option.value = row.channel.id; option.textContent = row.channel.name + " (" + row.channel.id + ")";
    select.append(option);
  }
  // Проверяем условие перед изменением интерфейса или выполнением действия.
  if ([...select.options].some(option => option.value === previous)) select.value = previous;
}
// Полный профиль позволяет согласованно изменить тему, рубрики и критерии модели.
$("channel-profiles").onclick = async () => {
  // Отображаем ошибку пользователю, сохраняя возможность следующего действия.
  try { $("channel-profile-json").value = JSON.stringify(await api("/api/v1/channel-profiles"), null, 2); }
  // Показываем безопасный код ошибки без сохранения ключа доступа.
  catch (e) { $("result").textContent = e.message; }
};
// Связываем действие пользователя с запросом к API проекта.
$("channel-apply").onclick = async () => {
  // Отображаем ошибку пользователю, сохраняя возможность следующего действия.
  try {
    const value = JSON.parse($("channel-profile-json").value);
    // Проверяем условие перед изменением интерфейса или выполнением действия.
    if (Array.isArray(value)) throw new Error("Оставьте один объект профиля из списка.");
    const document = {channel:value.channel, images:value.images};
    // Проверяем условие перед изменением интерфейса или выполнением действия.
    if (value.chat_id && value.chat_title) { document.chat_id = value.chat_id; document.chat_title = value.chat_title; }
    await action("/api/v1/channel-profiles", document);
    await loadImageChannels();
  } catch (e) { $("result").textContent = e.message; }
};
