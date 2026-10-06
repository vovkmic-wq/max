"use strict";
let token = "", tab = "channels";
const $ = id => document.getElementById(id);
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST",
    headers: {Authorization: "Bearer " + token, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.code || "Ошибка запроса");
  return value;
}
async function action(path, body = {}) {
  try { $("result").textContent = JSON.stringify(await api(path, body), null, 2); await refresh(); }
  catch(error) { $("result").textContent = error.message; }
}
async function refresh() {
  try {
    const rows = await api("/api/v1/" + tab);
    $("content").replaceChildren();
    for (const row of rows) {
      const card = document.createElement("article"); card.className = "card";
      const pre = document.createElement("pre"); pre.textContent = JSON.stringify(row, null, 2); card.append(pre);
      if (tab === "videos") {
        for (const [name,label] of [["approve-generation","Одобрить генерацию"],["poll","Проверить результат"],["assemble","Собрать ролик"],["cancel","Остановить проект"]]) {
          const b=document.createElement("button"); b.textContent=label;
          b.onclick=()=>action(`/api/v1/videos/${row.id}/${name}`, {revision:row.revision,plan_hash:row.plan_hash});card.append(b);
        }
        const index=document.createElement("input");index.type="number";index.value="0";index.min="0";card.append(index);
        const file=document.createElement("input");file.placeholder="data/incoming/scene.mp4";card.append(file);
        const rights=document.createElement("input");rights.placeholder="Права на сцену";card.append(rights);
        const b=document.createElement("button");b.textContent="Импортировать готовую сцену";
        b.onclick=()=>action(`/api/v1/videos/${row.id}/import-scene`,{index:Number(index.value),path:file.value,rights_basis:rights.value});card.append(b);
      }
      if (tab === "source-media") {
        const caption=document.createElement("textarea");caption.placeholder="Русская подпись с подтверждёнными фактами";card.append(caption);
        const b=document.createElement("button");b.textContent="Подготовить подборку";
        b.onclick=()=>action("/api/v1/curate",{channel_id:$("channel").value,media_id:row.id,caption:caption.value});card.append(b);
      }
      if (tab === "assets") {
        const b=document.createElement("button");b.textContent="Просмотреть ролик";
        b.onclick=async()=>{try {
          const r=await fetch(`/api/v1/assets/${row.id}/preview`,{headers:{Authorization:"Bearer "+token}});
          if(!r.ok)throw new Error("Нет доступа к видео");
          const v=document.createElement("video");v.controls=true;v.width=280;v.src=URL.createObjectURL(await r.blob());
          v.onloadeddata=()=>URL.revokeObjectURL(v.src);card.append(v);b.disabled=true;
        }catch(e){$("status").textContent=e.message;}};card.append(b);
      }
      if (tab === "drafts" && row.state !== "published") {
        const path = document.createElement("input"); path.placeholder = "data/incoming/clip.mp4"; card.append(path);
        const rights = document.createElement("input"); rights.placeholder = "Основание права на публикацию ролика"; card.append(rights);
        const attach = document.createElement("button"); attach.textContent = "Приложить MP4";
        attach.onclick = () => action(`/api/v1/drafts/${row.id}/video`, {path:path.value, rights_basis:rights.value}); card.append(attach);
        const commercial = document.createElement("button"); commercial.textContent = row.commercial ? "Снять коммерческую отметку" : "Коммерческий материал";
        commercial.onclick = () => action(`/api/v1/drafts/${row.id}/commercial`, {revision:row.revision, commercial:!row.commercial}); card.append(commercial);
        const edit = document.createElement("textarea"); edit.value = row.current.body; card.append(edit);
        const save = document.createElement("button"); save.textContent = "Сохранить новую ревизию";
        save.onclick = () => action(`/api/v1/drafts/${row.id}/revise`, {revision:row.revision, body:edit.value}); card.append(save);
        const approve = document.createElement("button"); approve.textContent = "Одобрить в календарь";
        approve.onclick = () => action(`/api/v1/drafts/${row.id}/approve`, {revision:row.revision, content_hash:row.content_hash}); card.append(approve);
        const reject = document.createElement("button"); reject.textContent = "Отклонить";
        reject.onclick = () => action(`/api/v1/drafts/${row.id}/reject`, {revision:row.revision}); card.append(reject);
      }
      if (tab === "publications" && ["sending","unknown"].includes(row.state)) {
        const reconcile = document.createElement("button"); reconcile.textContent = "Сверить результат";
        reconcile.onclick = () => action(`/api/v1/publications/${row.id}/reconcile`); card.append(reconcile);
      }
      $("content").append(card);
    }
    $("status").textContent = "Подключено. " + rows.length + " записей.";
  } catch(error) { $("status").textContent = error.message; }
}
$("login").onclick = async () => {token = $("token").value; $("token").value = ""; await refresh();};
$("refresh").onclick = refresh;
for (const button of document.querySelectorAll("[data-tab]")) button.onclick = () => {
  tab = button.dataset.tab; $("heading").textContent = button.textContent; refresh();
};
const channelPath = actionName => `/api/v1/channels/${encodeURIComponent($("channel").value)}/${actionName}`;
$("connect").onclick = () => action(channelPath("connect"), {chat_id:$("chat").value});
for (const name of ["pause","resume","bootstrap"]) $(name).onclick = () => action(channelPath(name));
$("growth").onclick = () => action(channelPath("growth-plan"));
$("report").onclick = async () => {try { $("result").textContent = JSON.stringify(await api(`/api/v1/reports/${encodeURIComponent($("channel").value)}`), null, 2); } catch(e) {$("result").textContent=e.message;}};
$("validate").onclick = () => action("/api/v1/config/validate");
$("activate").onclick = () => action("/api/v1/config/activate");
$("generate-plan").onclick=()=>action("/api/v1/videos",{channel_id:$("channel").value,idea:$("video-idea").value});
$("create-plan").onclick=()=>{try{action("/api/v1/videos",{channel_id:$("channel").value,plan:JSON.parse($("video-plan").value)});}catch(e){$("result").textContent="Ошибка JSON сценария";}};
