import {AuthClient} from "./auth-client.js";
import {bindCameraLifecycle, cameraBlobToFile, captureCameraPhoto, openEnvironmentCamera, stopCamera} from "./camera.js";
import {defaultCorners, filterPreview, movePage, qualityPrompt, updateCorner} from "./page-editor.js";
import {downloadBlob, jobStatusLabel, projectJobs, shareOrDownload, shouldPollJobs} from "./project-files.js";
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
const copy = {
  "zh-CN": {eyebrow:"让纸张重新变得清晰",authTitle:"扫描、整理，一气呵成。",authText:"一套账号连接企微、Android 与 iOS，原图始终由你掌控。",username:"用户名",password:"密码",login:"登录",wecomLogin:"企业微信登录",or:"或",logout:"退出登录",bindingTitle:"验证安全手机号",bindingText:"企业微信未提供可信手机号，请用短信验证后完成绑定。",phone:"手机号（含国家码）",smsCode:"短信验证码",sendCode:"发送验证码",finishBinding:"完成绑定",backToLogin:"返回账号登录",processingLogin:"正在完成企业微信登录…",welcome:"下午好",capture:"捕捉纸上的",clarity:"每一分清晰。",localCore:"基础能力可用",smartScan:"智能扫描",smartScanDesc:"自动裁边 · 文字转正 · 清晰增强",exam:"试卷净化",examDesc:"保留印刷内容，标记低置信区域",book:"连续扫书",bookDesc:"双页拆分 · 页码检查 · 快速成册",library:"资料库",recent:"最近项目",refresh:"刷新",empty:"还没有扫描项目",emptyHint:"选择上方模式开始第一份扫描",home:"首页",scan:"扫描",files:"文件",newProject:"新建项目",projectTitle:"项目名称",openCamera:"打开实时相机",takePhoto:"拍摄页面",closeCamera:"关闭相机",selectPage:"使用系统相机或选择文件",originalKept:"原图会一直保留到你删除项目",createUpload:"创建并上传",uploading:"正在上传"},
  en: {eyebrow:"Bring clarity back to paper",authTitle:"Scan. Organize. Done.",authText:"One account across WeCom, Android and iOS. Your originals remain yours.",username:"Username",password:"Password",login:"Sign in",wecomLogin:"Continue with WeCom",or:"or",logout:"Sign out",bindingTitle:"Verify a secure phone",bindingText:"WeCom did not provide a trusted phone number. Verify one by SMS to finish binding.",phone:"Phone with country code",smsCode:"SMS code",sendCode:"Send code",finishBinding:"Finish binding",backToLogin:"Back to account sign-in",processingLogin:"Completing WeCom sign-in…",welcome:"Good afternoon",capture:"Capture every",clarity:"detail on paper.",localCore:"Core scanning ready",smartScan:"Smart Scan",smartScanDesc:"Auto crop · Rotate text · Enhance",exam:"Clean Exam",examDesc:"Keep print, flag uncertain regions",book:"Scan a Book",bookDesc:"Split spreads · Check pages · Export",library:"Library",recent:"Recent projects",refresh:"Refresh",empty:"No scan projects yet",emptyHint:"Choose a mode above to begin",home:"Home",scan:"Scan",files:"Files",newProject:"New project",projectTitle:"Project title",openCamera:"Open live camera",takePhoto:"Capture page",closeCamera:"Close camera",selectPage:"Use system camera or choose a file",originalKept:"Originals stay until you delete the project",createUpload:"Create & upload",uploading:"Uploading"}
};
const editorCopy = {
  "zh-CN": {title:"页面编辑",close:"关闭",rotateLeft:"左转",rotateRight:"右转",moveLeft:"前移",moveRight:"后移",resetCorners:"重置四角",save:"应用裁切与滤镜",confirm:"确认已复核",original:"原图",enhance:"增强",grayscale:"灰度",bw:"黑白",empty:"项目还没有可编辑页面",loading:"正在加载页面…",saved:"页面编辑已保存，新结果版本已生成。",ordered:"页面顺序已保存。",confirmed:"页面已标记为复核完成。",noChange:"请先调整四角或选择滤镜。",filesTitle:"处理与导出",refreshFiles:"刷新状态",format:"格式",quality:"质量",qualityClear:"清晰",qualityBalanced:"均衡",qualitySmall:"小文件",includeOcr:"PDF 包含 OCR 文本层",createExport:"生成导出",noJobs:"暂无处理任务",noExports:"还没有导出文件",download:"下载",share:"分享",exporting:"正在生成导出…",exported:"导出已生成。",downloaded:"文件已下载。",shared:"文件已分享。",shareCanceled:"已取消分享。",shareFallback:"当前浏览器无法分享文件，已改为下载。"},
  en: {title:"Edit pages",close:"Close",rotateLeft:"Rotate left",rotateRight:"Rotate right",moveLeft:"Move earlier",moveRight:"Move later",resetCorners:"Reset corners",save:"Apply crop & filter",confirm:"Confirm reviewed",original:"Original",enhance:"Enhance",grayscale:"Grayscale",bw:"Black & white",empty:"This project has no editable pages",loading:"Loading page…",saved:"Page edit saved as a new result version.",ordered:"Page order saved.",confirmed:"Page marked as reviewed.",noChange:"Adjust corners or choose a filter first.",filesTitle:"Processing & exports",refreshFiles:"Refresh status",format:"Format",quality:"Quality",qualityClear:"Clear",qualityBalanced:"Balanced",qualitySmall:"Small file",includeOcr:"Include OCR text layer in PDF",createExport:"Create export",noJobs:"No processing jobs",noExports:"No exports yet",download:"Download",share:"Share",exporting:"Creating export…",exported:"Export created.",downloaded:"File downloaded.",shared:"File shared.",shareCanceled:"Sharing canceled.",shareFallback:"File sharing is unavailable, so the file was downloaded."},
};
const $ = selector => document.querySelector(selector);
function t(key){ return copy[locale][key] || key; }
function renderLocale(){ document.documentElement.lang=locale; document.querySelectorAll("[data-i18n]").forEach(el=>el.textContent=t(el.dataset.i18n)); document.querySelectorAll("[data-editor-i18n]").forEach(el=>el.textContent=editorCopy[locale][el.dataset.editorI18n]); $("#capturePreview").alt=locale==="zh-CN"?"待上传页面预览":"Preview of the page to upload"; if(editorProject){ if(editorIndex>=0) renderEditorState(); renderProjectFiles(); } }
function browserDeviceName(){ const platform=navigator.userAgentData?.platform||navigator.platform||"Web"; return `SmartScan H5 · ${platform}`.slice(0,100); }
const auth=new AuthClient({api:API,fetchImpl:fetch,sessionStorage,deviceStorage:localStorage,deviceName:browserDeviceName(),onAuthLost:()=>{ showAuth(); $("#authMessage").textContent=locale==="zh-CN"?"登录已失效，请重新登录。":"Your session expired. Please sign in again."; }});
function localizedError(error){ const messages={"invalid credentials":["用户名或密码错误。","Incorrect username or password."],account_unavailable:["账号当前不可用。","This account is unavailable."],wecom_disabled:["企业微信登录尚未配置。","WeCom sign-in is not configured."],wecom_identity_conflict:["账号身份存在冲突，请联系管理员处理。","This identity needs administrator review."],wecom_intent_invalid:["登录状态已失效，请重新发起企业微信登录。","The sign-in state expired. Start WeCom sign-in again."],sms_provider_disabled:["短信服务尚未配置。","SMS service is not configured."],sms_challenge_invalid:["验证码无效，请重新获取。","The SMS code is invalid. Request a new one."],sms_challenge_expired:["验证码已过期，请重新获取。","The SMS code expired. Request a new one."],refresh_token_replayed:["会话存在异常，所有令牌已撤销，请重新登录。","The session was revoked. Please sign in again."],camera_insecure_context:["实时相机需要 HTTPS，请改用系统相机或选择文件。","Live camera requires HTTPS. Use the system camera or choose a file."],camera_not_supported:["当前浏览器不支持实时相机，请使用系统相机。","This browser does not support live camera. Use the system camera."],camera_permission_denied:["相机权限被拒绝，可在浏览器设置中允许或使用系统相机。","Camera permission was denied. Allow it in browser settings or use the system camera."],camera_not_found:["未找到可用相机，请使用系统相机或选择文件。","No camera was found. Use the system camera or choose a file."],camera_in_use:["相机正被其他应用占用，请关闭后重试或使用系统相机。","The camera is in use. Close the other app or use the system camera."],camera_open_failed:["实时相机打开失败，请使用系统相机或选择文件。","Live camera could not open. Use the system camera or choose a file."],camera_capture_failed:["拍摄失败，请重试或使用系统相机。","Capture failed. Try again or use the system camera."],camera_frame_unavailable:["相机画面尚未就绪，请重试。","The camera frame is not ready. Try again."]}; const pair=messages[error.message]; return pair?pair[locale==="zh-CN"?0:1]:error.message; }
async function request(path,options={}){ return auth.request(path,options); }
function showAuth(){ if(editorProject){ restoredProjectId=editorProject.id; preserveEditorRestore=true; if($("#editorDialog").open) $("#editorDialog").close(); } $("#authView").classList.remove("hidden"); $("#homeView").classList.add("hidden"); $(".bottom-nav").classList.add("hidden"); $("#logoutButton").classList.add("hidden"); $("#loginForm").classList.remove("hidden"); $("#wecomActions").classList.remove("hidden"); $("#phoneBindingForm").classList.add("hidden"); }
function showPhoneBinding(ticket){ bindingTicket=ticket; bindingChallengeId=null; $("#authMessage").textContent=""; $("#bindingMessage").textContent=""; $("#authView").classList.remove("hidden"); $("#homeView").classList.add("hidden"); $(".bottom-nav").classList.add("hidden"); $("#logoutButton").classList.add("hidden"); $("#loginForm").classList.add("hidden"); $("#wecomActions").classList.add("hidden"); $("#phoneBindingForm").classList.remove("hidden"); }
function showHome(){ $("#authView").classList.add("hidden"); $("#homeView").classList.remove("hidden"); $(".bottom-nav").classList.remove("hidden"); $("#logoutButton").classList.remove("hidden"); loadProjects(); }
async function loadProjects(){ try{ const projects=await request("/v1/projects"); const list=$("#projectList"); if(!projects.length){ list.innerHTML=`<div class="empty-state"><span>⌁</span><b>${t("empty")}</b><small>${t("emptyHint")}</small></div>`; return; } list.innerHTML=projects.map(p=>`<button class="project" type="button" data-project-id="${p.id}"><div class="project-top"><span class="project-icon"></span><small>${p.mode.toUpperCase()}</small></div><div><h3>${escapeHtml(p.title)}</h3><small>${new Date(p.updated_at).toLocaleDateString(locale)}</small></div></button>`).join(""); if(restoredProjectId){ const restored=projects.find(project=>project.id===restoredProjectId); restoredProjectId=null; if(restored) openProjectEditor(restored.id,restored.title); } }catch(error){ $("#projectList").innerHTML=`<div class="empty-state"><b>${escapeHtml(localizedError(error))}</b></div>`; } }
function escapeHtml(value){ const node=document.createElement("div"); node.textContent=value; return node.innerHTML; }

function clearEditorImage(){ if(editorImageUrl) URL.revokeObjectURL(editorImageUrl); editorImageUrl=null; $("#editorImage").removeAttribute("src"); }
function renderEditorCorners(){ const points=editorCorners.map(corner=>`${corner.x*1000},${corner.y*1000}`).join(" "); $("#cornerPolygon").setAttribute("points",points); document.querySelectorAll("[data-corner]").forEach((handle,index)=>{ handle.setAttribute("cx",editorCorners[index].x*1000); handle.setAttribute("cy",editorCorners[index].y*1000); }); }
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
  $("#projectJobList").innerHTML=editorJobs.length?editorJobs.map(job=>`<div class="job-row"><div><p><b>${escapeHtml(jobStatusLabel(job.status,locale))}</b></p><small>${escapeHtml(job.kind)} · ${job.progress}%</small></div><progress max="100" value="${Math.max(0,Math.min(100,job.progress))}"></progress></div>`).join(""):`<div class="empty-state"><small>${editorCopy[locale].noJobs}</small></div>`;
  editorArtifacts=[];
  $("#exportList").innerHTML=editorExports.length?editorExports.map(item=>{
    const artifacts=item.artifacts.map(artifact=>{ const index=editorArtifacts.push(artifact)-1; return `<div class="artifact-row"><p><b>${escapeHtml(artifact.file_name)}</b><br><small>${formatBytes(artifact.size_bytes)}</small></p><div class="artifact-actions"><button class="secondary" type="button" data-artifact-index="${index}" data-file-action="download">${editorCopy[locale].download}</button><button class="secondary" type="button" data-artifact-index="${index}" data-file-action="share">${editorCopy[locale].share}</button></div></div>`; }).join("");
    const status=item.status==="ready"?(locale==="zh-CN"?"已就绪":"Ready"):item.status==="failed"?(locale==="zh-CN"?"失败":"Failed"):(locale==="zh-CN"?"生成中":"Generating");
    return `<article class="export-card"><div><b>${item.format.toUpperCase()} · ${escapeHtml(item.quality)}</b><small> · ${status} · ${new Date(item.created_at).toLocaleString(locale)}</small></div>${artifacts}</article>`;
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

