import {AuthClient} from "./auth-client.js";
import {bindCameraLifecycle, cameraBlobToFile, captureCameraPhoto, openEnvironmentCamera, stopCamera} from "./camera.js";
import {copy, editorCopy} from "./i18n.js";
import {defaultCorners, filterPreview, movePage, qualityPrompt, updateCorner} from "./page-editor.js";
import {downloadBlob, exportQualityLabel, exportStatusLabel, jobKindLabel, jobStatusLabel, projectJobs, shareOrDownload, shouldPollJobs} from "./project-files.js";
import {uploadResumable} from "./resumable-upload.js";

const defaultApi = ["localhost", "127.0.0.1"].includes(location.hostname) ? "http://localhost:8000" : `${location.origin}/api`;
const API = localStorage.getItem("smartscan.api") || defaultApi;
localStorage.removeItem("smartscan.token");
let locale = localStorage.getItem("smartscan.locale") || (navigator.language.startsWith("zh") ? "zh-CN" : "en");
let mode = "document";
let cameraStream = null;
let capturedFile = null;
let previewUrl = null;
let bindingTicket = null;
let bindingChallengeId = null;
let editorProject = null;
let editorPages = [];
let editorIndex = -1;
let editorCorners = defaultCorners();
let editorCornersDirty = false;
let editorFilter = "original";
let editorImageUrl = null;
let draggedCorner = null;
let editorJobs = [];
let editorExports = [];
let editorArtifacts = [];
let editorPollTimer = null;
let restoredProjectId = new URLSearchParams(location.hash.slice(1)).get("project");
let preserveEditorRestore = false;
const $ = selector => document.querySelector(selector);
function t(key){ return copy[locale][key] || key; }
function renderLocale(){ document.documentElement.lang=locale; document.querySelectorAll("[data-i18n]").forEach(el=>el.textContent=t(el.dataset.i18n)); document.querySelectorAll("[data-editor-i18n]").forEach(el=>el.textContent=editorCopy[locale][el.dataset.editorI18n]); document.querySelectorAll("[data-i18n-aria-label]").forEach(el=>el.setAttribute("aria-label",t(el.dataset.i18nAriaLabel))); document.querySelectorAll("[data-i18n-alt]").forEach(el=>el.setAttribute("alt",t(el.dataset.i18nAlt))); if(editorProject){ if(editorIndex>=0) renderEditorState(); renderProjectFiles(); } }
function browserDeviceName(){ const platform=navigator.userAgentData?.platform||navigator.platform||"Web"; return `SmartScan H5 · ${platform}`.slice(0,100); }
const auth=new AuthClient({api:API,fetchImpl:fetch,sessionStorage,deviceStorage:localStorage,deviceName:browserDeviceName(),onAuthLost:()=>{ showAuth(); $("#authMessage").textContent=locale==="zh-CN"?"登录已失效，请重新登录。":"Your session expired. Please sign in again."; }});
function localizedError(error){ const messages={"invalid credentials":["用户名或密码错误。","Incorrect username or password."],account_unavailable:["账号当前不可用。","This account is unavailable."],wecom_disabled:["企业微信登录尚未配置。","WeCom sign-in is not configured."],wecom_identity_conflict:["账号身份存在冲突，请联系管理员处理。","This identity needs administrator review."],wecom_intent_invalid:["登录状态已失效，请重新发起企业微信登录。","The sign-in state expired. Start WeCom sign-in again."],sms_provider_disabled:["短信服务尚未配置。","SMS service is not configured."],sms_challenge_invalid:["验证码无效，请重新获取。","The SMS code is invalid. Request a new one."],sms_challenge_expired:["验证码已过期，请重新获取。","The SMS code expired. Request a new one."],refresh_token_replayed:["会话存在异常，所有令牌已撤销，请重新登录。","The session was revoked. Please sign in again."],camera_insecure_context:["实时相机需要 HTTPS，请改用系统相机或选择文件。","Live camera requires HTTPS. Use the system camera or choose a file."],camera_not_supported:["当前浏览器不支持实时相机，请使用系统相机。","This browser does not support live camera. Use the system camera."],camera_permission_denied:["相机权限被拒绝，可在浏览器设置中允许或使用系统相机。","Camera permission was denied. Allow it in browser settings or use the system camera."],camera_not_found:["未找到可用相机，请使用系统相机或选择文件。","No camera was found. Use the system camera or choose a file."],camera_in_use:["相机正被其他应用占用，请关闭后重试或使用系统相机。","The camera is in use. Close the other app or use the system camera."],camera_open_failed:["实时相机打开失败，请使用系统相机或选择文件。","Live camera could not open. Use the system camera or choose a file."],camera_capture_failed:["拍摄失败，请重试或使用系统相机。","Capture failed. Try again or use the system camera."],camera_frame_unavailable:["相机画面尚未就绪，请重试。","The camera frame is not ready. Try again."]}; const pair=messages[error.message]; return pair?pair[locale==="zh-CN"?0:1]:error.message; }
async function request(path,options={}){ return auth.request(path,options); }
function showAuth(){ if(editorProject){ restoredProjectId=editorProject.id; preserveEditorRestore=true; if($("#editorDialog").open) $("#editorDialog").close(); } $("#authView").classList.remove("hidden"); $("#homeView").classList.add("hidden"); $(".bottom-nav").classList.add("hidden"); $("#logoutButton").classList.add("hidden"); $("#loginForm").classList.remove("hidden"); $("#wecomActions").classList.remove("hidden"); $("#phoneBindingForm").classList.add("hidden"); }
function showPhoneBinding(ticket){ bindingTicket=ticket; bindingChallengeId=null; $("#authMessage").textContent=""; $("#bindingMessage").textContent=""; $("#authView").classList.remove("hidden"); $("#homeView").classList.add("hidden"); $(".bottom-nav").classList.add("hidden"); $("#logoutButton").classList.add("hidden"); $("#loginForm").classList.add("hidden"); $("#wecomActions").classList.add("hidden"); $("#phoneBindingForm").classList.remove("hidden"); }
function showHome(){ $("#authView").classList.add("hidden"); $("#homeView").classList.remove("hidden"); $(".bottom-nav").classList.remove("hidden"); $("#logoutButton").classList.remove("hidden"); loadProjects(); }
async function loadProjects(){ try{ const projects=await request("/v1/projects"); const list=$("#projectList"); if(!projects.length){ list.innerHTML=`<div class="empty-state"><span>⌁</span><b>${t("empty")}</b><small>${t("emptyHint")}</small></div>`; return; } list.innerHTML=projects.map(p=>`<button class="project" type="button" data-project-id="${p.id}"><div class="project-top"><span class="project-icon"></span><small>${t(p.mode==="document"?"smartScan":p.mode)}</small></div><div><h3>${escapeHtml(p.title)}</h3><small>${new Date(p.updated_at).toLocaleDateString(locale)}</small></div></button>`).join(""); if(restoredProjectId){ const restored=projects.find(project=>project.id===restoredProjectId); restoredProjectId=null; if(restored) openProjectEditor(restored.id,restored.title); } }catch(error){ $("#projectList").innerHTML=`<div class="empty-state"><b>${escapeHtml(localizedError(error))}</b></div>`; } }
function escapeHtml(value){ const node=document.createElement("div"); node.textContent=value; return node.innerHTML; }

function clearEditorImage(){ if(editorImageUrl) URL.revokeObjectURL(editorImageUrl); editorImageUrl=null; $("#editorImage").removeAttribute("src"); }
function renderEditorCorners(){ const points=editorCorners.map(corner=>`${corner.x*1000},${corner.y*1000}`).join(" "); const labels=["cornerTopLeft","cornerTopRight","cornerBottomRight","cornerBottomLeft"]; $("#cornerPolygon").setAttribute("points",points); document.querySelectorAll("[data-corner]").forEach((handle,index)=>{ const corner=editorCorners[index]; handle.setAttribute("cx",corner.x*1000); handle.setAttribute("cy",corner.y*1000); handle.setAttribute("aria-label",editorCopy[locale][labels[index]]); handle.setAttribute("aria-valuenow",Math.round(corner.x*100)); handle.setAttribute("aria-valuetext",`x ${Math.round(corner.x*100)}%, y ${Math.round(corner.y*100)}%`); }); }
function renderEditorState(){
  const page=editorPages[editorIndex];
  $("#editorProjectTitle").textContent=editorProject?.title||editorCopy[locale].title;
  $("#editorPageList").innerHTML=editorPages.map((item,index)=>`<button type="button" class="page-chip ${index===editorIndex?"active":""}" data-page-index="${index}"><b>${index+1}</b><small>${item.quality_warning?"!":"✓"}</small></button>`).join("");
  $("#movePageLeft").disabled=editorIndex<=0;
  $("#movePageRight").disabled=editorIndex<0||editorIndex>=editorPages.length-1;
  $("#qualityMessage").textContent=qualityPrompt(page,locale);
  $("#confirmReview").classList.toggle("hidden",!page||page.review_status!=="pending");
  document.querySelectorAll("[data-page-filter]").forEach(button=>button.classList.toggle("active",button.dataset.pageFilter===editorFilter));
  $("#editorImage").style.filter=filterPreview(editorFilter);
  renderEditorCorners();
}
function formatBytes(size){ if(size<1024) return `${size} B`; if(size<1024*1024) return `${(size/1024).toFixed(1)} KB`; return `${(size/1024/1024).toFixed(1)} MB`; }
function renderProjectFiles(){
  $("#projectJobList").innerHTML=editorJobs.length?editorJobs.map(job=>`<div class="job-row"><div><p><b>${escapeHtml(jobStatusLabel(job.status,locale))}</b></p><small>${escapeHtml(jobKindLabel(job.kind,locale))} · ${job.progress}%</small></div><progress max="100" value="${Math.max(0,Math.min(100,job.progress))}"></progress></div>`).join(""):`<div class="empty-state"><small>${editorCopy[locale].noJobs}</small></div>`;
  editorArtifacts=[];
  $("#exportList").innerHTML=editorExports.length?editorExports.map(item=>{
    const artifacts=item.artifacts.map(artifact=>{ const index=editorArtifacts.push(artifact)-1; return `<div class="artifact-row"><p><b>${escapeHtml(artifact.file_name)}</b><br><small>${formatBytes(artifact.size_bytes)}</small></p><div class="artifact-actions"><button class="secondary" type="button" data-artifact-index="${index}" data-file-action="download">${editorCopy[locale].download}</button><button class="secondary" type="button" data-artifact-index="${index}" data-file-action="share">${editorCopy[locale].share}</button></div></div>`; }).join("");
    return `<article class="export-card"><div><b>${item.format.toUpperCase()} · ${escapeHtml(exportQualityLabel(item.quality,locale))}</b><small> · ${escapeHtml(exportStatusLabel(item.status,locale))} · ${new Date(item.created_at).toLocaleString(locale)}</small></div>${artifacts}</article>`;
  }).join(""):`<div class="empty-state"><small>${editorCopy[locale].noExports}</small></div>`;
}
function stopProjectFilePolling(){ if(editorPollTimer!==null) clearTimeout(editorPollTimer); editorPollTimer=null; }
function scheduleProjectFilePolling(){ stopProjectFilePolling(); if(editorProject&&shouldPollJobs(editorJobs)) editorPollTimer=setTimeout(()=>loadProjectFiles({silent:true}),3000); }
async function loadProjectFiles({silent=false}={}){
  if(!editorProject) return;
  const projectId=editorProject.id;
  if(!silent) $("#projectFilesMessage").textContent=editorCopy[locale].loading;
  stopProjectFilePolling();
  try{ const [jobs,exports]=await Promise.all([request("/v1/jobs"),request(`/v1/projects/${projectId}/exports`)]); if(editorProject?.id!==projectId) return; editorJobs=projectJobs(jobs,projectId); editorExports=exports; renderProjectFiles(); if(!silent) $("#projectFilesMessage").textContent=""; }
  catch(error){ if(editorProject?.id===projectId) $("#projectFilesMessage").textContent=localizedError(error); }
  finally{ if(editorProject?.id===projectId) scheduleProjectFilePolling(); }
}
async function createProjectExport(){
  if(!editorProject) return;
  const button=$("#createExport"); button.disabled=true; $("#projectFilesMessage").textContent=editorCopy[locale].exporting;
  try{ await request(`/v1/projects/${editorProject.id}/exports`,{method:"POST",body:JSON.stringify({format:$("#exportFormat").value,quality:$("#exportQuality").value,include_ocr_text:$("#exportFormat").value==="pdf"&&$("#exportOcr").checked})}); await loadProjectFiles({silent:true}); $("#projectFilesMessage").textContent=editorCopy[locale].exported; }
  catch(error){ $("#projectFilesMessage").textContent=localizedError(error); }
  finally{ button.disabled=false; }
}
async function deliverArtifact(artifact,action){
  $("#projectFilesMessage").textContent=editorCopy[locale].loading;
  try{ const blob=await auth.requestBlob(`/v1/export-artifacts/${artifact.id}/content`); if(action==="download"){ downloadBlob({blob,fileName:artifact.file_name}); $("#projectFilesMessage").textContent=editorCopy[locale].downloaded; return; } const result=await shareOrDownload({blob,fileName:artifact.file_name,mimeType:artifact.mime_type,title:editorProject?.title||editorCopy[locale].title}); $("#projectFilesMessage").textContent=result==="shared"?editorCopy[locale].shared:result==="canceled"?editorCopy[locale].shareCanceled:editorCopy[locale].shareFallback; }
  catch(error){ $("#projectFilesMessage").textContent=localizedError(error); }
}
async function selectEditorPage(index){
  if(index<0||index>=editorPages.length) return;
  editorIndex=index; editorCorners=defaultCorners(); editorCornersDirty=false; editorFilter="original"; clearEditorImage(); renderEditorState(); $("#editorMessage").textContent=editorCopy[locale].loading;
  const expectedId=editorPages[index].id;
  try{ const blob=await auth.requestBlob(`/v1/pages/${expectedId}/content`); if(editorPages[editorIndex]?.id!==expectedId) return; editorImageUrl=URL.createObjectURL(blob); $("#editorImage").src=editorImageUrl; $("#editorMessage").textContent=""; }
  catch(error){ $("#editorMessage").textContent=localizedError(error); }
}
async function openProjectEditor(projectId,title){
  editorProject={id:projectId,title}; editorPages=[]; editorJobs=[]; editorExports=[]; editorArtifacts=[]; editorIndex=-1; clearEditorImage(); history.replaceState(null,"",`#project=${encodeURIComponent(projectId)}`); $("#editorDialog").showModal(); $("#editorMessage").textContent=editorCopy[locale].loading; renderProjectFiles(); loadProjectFiles();
  try{ editorPages=await request(`/v1/projects/${projectId}/pages`); if(!editorPages.length){ $("#editorPageList").innerHTML=""; $("#editorMessage").textContent=editorCopy[locale].empty; return; } await selectEditorPage(0); }
  catch(error){ $("#editorMessage").textContent=localizedError(error); }
}
async function rotateEditorPage(degrees){ const page=editorPages[editorIndex]; if(!page) return; try{ const updated=await request(`/v1/pages/${page.id}/rotations`,{method:"POST",body:JSON.stringify({degrees})}); editorPages[editorIndex]=updated; await selectEditorPage(editorIndex); }catch(error){ $("#editorMessage").textContent=localizedError(error); } }
async function reorderEditorPage(delta){ const moved=movePage(editorPages,editorIndex,delta); if(moved.index===editorIndex) return; try{ const ordered=await request(`/v1/projects/${editorProject.id}/pages/order`,{method:"PATCH",body:JSON.stringify({page_ids:moved.pages.map(page=>page.id)})}); editorPages=ordered; editorIndex=moved.index; renderEditorState(); $("#editorMessage").textContent=editorCopy[locale].ordered; }catch(error){ $("#editorMessage").textContent=localizedError(error); } }
async function saveEditorPage(){ const page=editorPages[editorIndex]; if(!page) return; if(!editorCornersDirty&&editorFilter==="original"){ $("#editorMessage").textContent=editorCopy[locale].noChange; return; } const payload={filter:editorFilter}; if(editorCornersDirty) payload.corners=editorCorners; try{ const updated=await request(`/v1/pages/${page.id}/edits`,{method:"POST",body:JSON.stringify(payload)}); editorPages[editorIndex]=updated; await selectEditorPage(editorIndex); $("#editorMessage").textContent=editorCopy[locale].saved; }catch(error){ $("#editorMessage").textContent=localizedError(error); } }
function setUploadProgress(uploaded,total){ const percent=Math.min(100,Math.round(uploaded/total*100)); $("#uploadProgressWrap").classList.remove("hidden"); $("#uploadProgress").value=percent; $("#uploadPercent").textContent=`${percent}%`; }
function resetCamera(){ stopCamera(cameraStream); cameraStream=null; $("#cameraPreview").srcObject=null; $("#cameraPanel").classList.add("hidden"); }
function clearPreview(){ if(previewUrl) URL.revokeObjectURL(previewUrl); previewUrl=null; $("#capturePreview").removeAttribute("src"); $("#capturePreview").classList.add("hidden"); }
function showPreview(file){ clearPreview(); if(!file?.type?.startsWith("image/")) return; previewUrl=URL.createObjectURL(file); $("#capturePreview").src=previewUrl; $("#capturePreview").classList.remove("hidden"); }
function openCapture(nextMode="document"){ mode=nextMode; capturedFile=null; clearPreview(); $("#pageFile").value=""; $("#fileName").textContent=t("originalKept"); $("#captureTitle").textContent=t(nextMode==="document"?"smartScan":nextMode); $("#projectTitle").value=`${t(nextMode==="document"?"smartScan":nextMode)}_${new Date().toISOString().slice(0,10).replaceAll("-","")}`; $("#captureDialog").showModal(); }
$("#languageButton").addEventListener("click",()=>{ locale=locale==="zh-CN"?"en":"zh-CN"; localStorage.setItem("smartscan.locale",locale); renderLocale(); if(auth.isAuthenticated) loadProjects(); });
$("#loginForm").addEventListener("submit",async event=>{ event.preventDefault(); const data=Object.fromEntries(new FormData(event.currentTarget)); try{ $("#authMessage").textContent=""; await auth.login(data.username,data.password); showHome(); }catch(error){ $("#authMessage").textContent=localizedError(error); } });
$("#wecomLoginButton").addEventListener("click",async event=>{ const button=event.currentTarget; button.disabled=true; try{ $("#authMessage").textContent=t("processingLogin"); const start=await auth.beginWeCom(); location.assign(start.authorization_url); }catch(error){ $("#authMessage").textContent=localizedError(error); button.disabled=false; } });
$("#sendBindingCode").addEventListener("click",async event=>{ const button=event.currentTarget,phone=$("#bindingPhone").value.trim(); if(!phone){ $("#bindingMessage").textContent=locale==="zh-CN"?"请先填写手机号。":"Enter a phone number first."; return; } button.disabled=true; try{ const challenge=await auth.requestBindingCode(phone); bindingChallengeId=challenge.challenge_id; $("#bindingMessage").textContent=locale==="zh-CN"?"验证码已发送，请在有效期内完成验证。":"Code sent. Complete verification before it expires."; setTimeout(()=>{ button.disabled=false; },challenge.retry_after_seconds*1000); }catch(error){ $("#bindingMessage").textContent=localizedError(error); button.disabled=false; } });
$("#phoneBindingForm").addEventListener("submit",async event=>{ event.preventDefault(); if(!bindingChallengeId){ $("#bindingMessage").textContent=locale==="zh-CN"?"请先发送验证码。":"Send an SMS code first."; return; } const data=Object.fromEntries(new FormData(event.currentTarget)); try{ await auth.bindWeComPhone({bindingTicket,phone:data.phone.trim(),challengeId:bindingChallengeId,code:data.sms_code.trim()}); showHome(); }catch(error){ $("#bindingMessage").textContent=localizedError(error); } });
$("#backToLogin").addEventListener("click",()=>{ bindingTicket=null; bindingChallengeId=null; showAuth(); });
$("#logoutButton").addEventListener("click",async()=>{ try{ await auth.logout(); }catch{ /* 本地令牌仍会被清理。 */ } restoredProjectId=null; preserveEditorRestore=false; if($("#editorDialog").open) $("#editorDialog").close(); showAuth(); $("#authMessage").textContent=locale==="zh-CN"?"已安全退出当前设备。":"Signed out on this device."; });
document.querySelectorAll("[data-mode]").forEach(button=>button.addEventListener("click",()=>openCapture(button.dataset.mode)));
$("#quickScan").addEventListener("click",()=>openCapture()); $("#refreshButton").addEventListener("click",loadProjects);
$("#projectList").addEventListener("click",event=>{ const project=event.target.closest("[data-project-id]"); if(project) openProjectEditor(project.dataset.projectId,project.querySelector("h3")?.textContent||""); });
$("#editorPageList").addEventListener("click",event=>{ const page=event.target.closest("[data-page-index]"); if(page) selectEditorPage(Number(page.dataset.pageIndex)); });
$("#closeEditor").addEventListener("click",()=>$("#editorDialog").close());
$("#editorDialog").addEventListener("close",()=>{ clearEditorImage(); stopProjectFilePolling(); editorProject=null; editorPages=[]; editorJobs=[]; editorExports=[]; editorArtifacts=[]; editorIndex=-1; if(!preserveEditorRestore) restoredProjectId=null; preserveEditorRestore=false; history.replaceState(null,"","#home"); });
$("#rotatePageLeft").addEventListener("click",()=>rotateEditorPage(270));
$("#rotatePageRight").addEventListener("click",()=>rotateEditorPage(90));
$("#movePageLeft").addEventListener("click",()=>reorderEditorPage(-1));
$("#movePageRight").addEventListener("click",()=>reorderEditorPage(1));
$("#resetCorners").addEventListener("click",()=>{ editorCorners=defaultCorners(); editorCornersDirty=false; renderEditorState(); });
$("#savePageEdit").addEventListener("click",saveEditorPage);
$("#confirmReview").addEventListener("click",async()=>{ const page=editorPages[editorIndex]; if(!page) return; try{ const updated=await request(`/v1/pages/${page.id}/review`,{method:"PATCH",body:JSON.stringify({status:"confirmed",note:qualityPrompt(page,locale)})}); editorPages[editorIndex]=updated; renderEditorState(); $("#editorMessage").textContent=editorCopy[locale].confirmed; }catch(error){ $("#editorMessage").textContent=localizedError(error); } });
document.querySelectorAll("[data-page-filter]").forEach(button=>button.addEventListener("click",()=>{ editorFilter=button.dataset.pageFilter; renderEditorState(); }));
$("#cornerOverlay").addEventListener("pointerdown",event=>{ const handle=event.target.closest("[data-corner]"); if(!handle) return; draggedCorner=Number(handle.dataset.corner); event.currentTarget.setPointerCapture?.(event.pointerId); });
$("#cornerOverlay").addEventListener("pointermove",event=>{ if(draggedCorner===null) return; const rect=event.currentTarget.getBoundingClientRect(); editorCorners=updateCorner(editorCorners,draggedCorner,(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height); editorCornersDirty=true; renderEditorState(); });
$("#cornerOverlay").addEventListener("pointerup",()=>{ draggedCorner=null; });
$("#cornerOverlay").addEventListener("pointercancel",()=>{ draggedCorner=null; });
$("#cornerOverlay").addEventListener("keydown",event=>{ const handle=event.target.closest("[data-corner]"); if(!handle) return; const movement={ArrowLeft:[-.01,0],ArrowRight:[.01,0],ArrowUp:[0,-.01],ArrowDown:[0,.01]}[event.key]; if(!movement) return; event.preventDefault(); const index=Number(handle.dataset.corner),corner=editorCorners[index]; editorCorners=updateCorner(editorCorners,index,corner.x+movement[0],corner.y+movement[1]); editorCornersDirty=true; renderEditorState(); });
$("#refreshProjectFiles").addEventListener("click",()=>loadProjectFiles());
$("#createExport").addEventListener("click",createProjectExport);
$("#exportFormat").addEventListener("change",event=>{ $("#exportOcr").disabled=event.target.value!=="pdf"; if(event.target.value!=="pdf") $("#exportOcr").checked=false; });
$("#exportList").addEventListener("click",event=>{ const button=event.target.closest("[data-artifact-index]"); if(!button) return; const artifact=editorArtifacts[Number(button.dataset.artifactIndex)]; if(artifact) deliverArtifact(artifact,button.dataset.fileAction); });
$("#openCamera").addEventListener("click",async()=>{ const message=$("#captureMessage"); resetCamera(); try{ cameraStream=await openEnvironmentCamera({mediaDevices:navigator.mediaDevices,videoElement:$("#cameraPreview")}); $("#cameraPanel").classList.remove("hidden"); message.textContent=locale==="zh-CN"?"相机已就绪，请手动拍摄。":"Camera ready. Capture when steady."; }catch(error){ message.textContent=localizedError(error); } });
$("#takePhoto").addEventListener("click",async event=>{ const message=$("#captureMessage"),button=event.currentTarget; button.disabled=true; try{ const blob=await captureCameraPhoto({stream:cameraStream,videoElement:$("#cameraPreview"),imageCaptureCtor:globalThis.ImageCapture}); capturedFile=cameraBlobToFile(blob); $("#pageFile").value=""; $("#fileName").textContent=capturedFile.name; showPreview(capturedFile); message.textContent=locale==="zh-CN"?"页面已拍摄，可创建并上传。":"Page captured and ready to upload."; resetCamera(); }catch(error){ resetCamera(); message.textContent=localizedError(error); }finally{ button.disabled=false; } });
$("#stopCamera").addEventListener("click",resetCamera);
$("#captureDialog").addEventListener("close",()=>{ resetCamera(); clearPreview(); });
$("#pageFile").addEventListener("change",event=>{ resetCamera(); capturedFile=null; const file=event.target.files[0]; $("#fileName").textContent=file?.name||t("originalKept"); if(file) showPreview(file); else clearPreview(); });
$("#captureForm").addEventListener("submit",async event=>{ event.preventDefault(); if(event.submitter?.value==="cancel"){ $("#captureDialog").close(); return; } const message=$("#captureMessage"),button=$("#submitCapture"),file=capturedFile||$("#pageFile").files[0],title=$("#projectTitle").value; button.disabled=true; try{ message.textContent=locale==="zh-CN"?"正在校验文件并恢复上传进度…":"Checking the file and resuming upload…"; if(file){ await uploadResumable({file,title,mode,request,storage:localStorage,onProgress:setUploadProgress}); }else{ await request("/v1/projects",{method:"POST",body:JSON.stringify({title,mode,reading_order:"ltr"})}); } capturedFile=null; clearPreview(); $("#captureDialog").close(); message.textContent=""; $("#uploadProgress").value=0; $("#uploadPercent").textContent="0%"; $("#uploadProgressWrap").classList.add("hidden"); loadProjects(); }catch(error){ message.textContent=(locale==="zh-CN"?"上传已暂停，可重新提交继续：":"Upload paused. Submit again to resume: ")+localizedError(error); }finally{ button.disabled=false; } });
bindCameraLifecycle({documentTarget:document,windowTarget:window,onRelease:resetCamera});
async function initialize(){ renderLocale(); const params=new URLSearchParams(location.search),code=params.get("code"),state=params.get("state"); if(code&&state){ showAuth(); $("#authMessage").textContent=t("processingLogin"); try{ const result=await auth.completeWeComCallback(code,state); history.replaceState({},"",`${location.pathname}${location.hash}`); if(result.access_token) showHome(); else if(result.action==="require_phone_binding"&&result.binding_ticket) showPhoneBinding(result.binding_ticket); else throw new Error("wecom_callback_incomplete"); }catch(error){ history.replaceState({},"",`${location.pathname}${location.hash}`); showAuth(); $("#authMessage").textContent=localizedError(error); } return; } auth.isAuthenticated?showHome():showAuth(); }
initialize();

