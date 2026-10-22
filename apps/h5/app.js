import {AuthClient} from "./auth-client.js";
import {aiCandidateSummary, canDecideEnhancement, confidencePercent, createAiIdempotencyKey, latestEnhancement, shouldPollEnhancements, sourceVersionPreview} from "./ai-enhancements.js";
import {analyzeBookLuma, initialBookAutoCaptureState, lumaFromImageData, reduceBookAutoCapture} from "./book-auto-capture.js";
import {bindCameraLifecycle, cameraBlobToFile, captureCameraPhoto, openEnvironmentCamera, stopCamera} from "./camera.js";
import {integrityDecisionOptions, integrityIssueLabel, pageNumberBadge, supplementDefaults} from "./book-integrity.js";
import {copy, editorCopy} from "./i18n.js";
import {bookSideLabel, canDismissExamSuggestion, canRetakeBookSide, defaultCorners, examSuggestionPrompt, filterPreview, movePage, qualityPrompt, updateCorner} from "./page-editor.js";
import {downloadBlob, exportQualityLabel, exportStatusLabel, jobKindLabel, jobStatusLabel, projectJobs, shareOrDownload, shouldPollJobs} from "./project-files.js";
import {uploadResumable} from "./resumable-upload.js";

const defaultApi = ["localhost", "127.0.0.1"].includes(location.hostname) ? "http://localhost:8000" : `${location.origin}/api`;
const API = localStorage.getItem("smartscan.api") || defaultApi;
localStorage.removeItem("smartscan.token");
let locale = localStorage.getItem("smartscan.locale") || (navigator.language.startsWith("zh") ? "zh-CN" : "en");
let mode = "document";
let cameraStream = null;
let bookAutoTimer = null;
let bookAutoState = initialBookAutoCaptureState();
let previousBookLuma = null;
let bookAutoCaptureBusy = false;
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
let editorBookIntegrity = null;
let pendingBookSupplement = null;
let editorPollTimer = null;
let homeProjects = [];
let aiCapabilities = null;
let aiEnhancements = [];
let aiPollTimer = null;
let aiBusy = false;
let aiPreviewingSource = false;
let aiDesiredEnabled = null;
let aiEnhancementKind = "recommended";
let restoredProjectId = new URLSearchParams(location.hash.slice(1)).get("project");
let preserveEditorRestore = false;
const $ = selector => document.querySelector(selector);
function t(key){ return copy[locale][key] || key; }
function renderLocale(){ document.documentElement.lang=locale; document.querySelectorAll("[data-i18n]").forEach(el=>el.textContent=t(el.dataset.i18n)); document.querySelectorAll("[data-editor-i18n]").forEach(el=>el.textContent=editorCopy[locale][el.dataset.editorI18n]); document.querySelectorAll("[data-i18n-aria-label]").forEach(el=>el.setAttribute("aria-label",t(el.dataset.i18nAriaLabel))); document.querySelectorAll("[data-i18n-alt]").forEach(el=>el.setAttribute("alt",t(el.dataset.i18nAlt))); renderBookAutoStatus(); if(editorProject){ if(editorIndex>=0) renderEditorState(); renderProjectFiles(); renderBookIntegrity(); renderAiWorkspace(); } }
function browserDeviceName(){ const platform=navigator.userAgentData?.platform||navigator.platform||"Web"; return `SmartScan H5 · ${platform}`.slice(0,100); }
const auth=new AuthClient({api:API,fetchImpl:fetch,sessionStorage,deviceStorage:localStorage,deviceName:browserDeviceName(),onAuthLost:()=>{ showAuth(); $("#authMessage").textContent=locale==="zh-CN"?"登录已失效，请重新登录。":"Your session expired. Please sign in again."; }});
function localizedError(error){ const messages={"invalid credentials":["用户名或密码错误。","Incorrect username or password."],account_unavailable:["账号当前不可用。","This account is unavailable."],wecom_disabled:["企业微信登录尚未配置。","WeCom sign-in is not configured."],wecom_identity_conflict:["账号身份存在冲突，请联系管理员处理。","This identity needs administrator review."],wecom_intent_invalid:["登录状态已失效，请重新发起企业微信登录。","The sign-in state expired. Start WeCom sign-in again."],sms_provider_disabled:["短信服务尚未配置。","SMS service is not configured."],sms_challenge_invalid:["验证码无效，请重新获取。","The SMS code is invalid. Request a new one."],sms_challenge_expired:["验证码已过期，请重新获取。","The SMS code expired. Request a new one."],refresh_token_replayed:["会话存在异常，所有令牌已撤销，请重新登录。","The session was revoked. Please sign in again."],camera_insecure_context:["实时相机需要 HTTPS，请改用系统相机或选择文件。","Live camera requires HTTPS. Use the system camera or choose a file."],camera_not_supported:["当前浏览器不支持实时相机，请使用系统相机。","This browser does not support live camera. Use the system camera."],camera_permission_denied:["相机权限被拒绝，可在浏览器设置中允许或使用系统相机。","Camera permission was denied. Allow it in browser settings or use the system camera."],camera_not_found:["未找到可用相机，请使用系统相机或选择文件。","No camera was found. Use the system camera or choose a file."],camera_in_use:["相机正被其他应用占用，请关闭后重试或使用系统相机。","The camera is in use. Close the other app or use the system camera."],camera_open_failed:["实时相机打开失败，请使用系统相机或选择文件。","Live camera could not open. Use the system camera or choose a file."],camera_capture_failed:["拍摄失败，请重试或使用系统相机。","Capture failed. Try again or use the system camera."],camera_frame_unavailable:["相机画面尚未就绪，请重试。","The camera frame is not ready. Try again."],ai_consent_required:["请先为项目启用 AI 并确认数据传输说明。","Enable AI for this project and confirm the data transfer notice first."],ai_consent_version_required:["数据传输说明版本已更新，请重新确认。","The data transfer notice changed. Confirm it again."],ai_runtime_unavailable:["AI 服务暂不可用，基础扫描与导出不受影响。","AI is temporarily unavailable; core scanning and exports remain available."],ai_source_version_conflict:["页面版本已变化，请重新获取建议。","The page changed. Request new suggestions."],ai_candidate_not_ready:["建议尚未就绪，请稍后刷新。","Suggestions are not ready yet."],ai_budget_exceeded:["AI 使用额度已达上限，基础功能仍可使用。","The AI budget limit was reached; core features remain available."]}; const pair=messages[error.message]; return pair?pair[locale==="zh-CN"?0:1]:error.message; }
async function request(path,options={}){ return auth.request(path,options); }
function showAuth(){ if(editorProject){ restoredProjectId=editorProject.id; preserveEditorRestore=true; if($("#editorDialog").open) $("#editorDialog").close(); } $("#authView").classList.remove("hidden"); $("#homeView").classList.add("hidden"); $(".bottom-nav").classList.add("hidden"); $("#logoutButton").classList.add("hidden"); $("#loginForm").classList.remove("hidden"); $("#wecomActions").classList.remove("hidden"); $("#phoneBindingForm").classList.add("hidden"); }
function showPhoneBinding(ticket){ bindingTicket=ticket; bindingChallengeId=null; $("#authMessage").textContent=""; $("#bindingMessage").textContent=""; $("#authView").classList.remove("hidden"); $("#homeView").classList.add("hidden"); $(".bottom-nav").classList.add("hidden"); $("#logoutButton").classList.add("hidden"); $("#loginForm").classList.add("hidden"); $("#wecomActions").classList.add("hidden"); $("#phoneBindingForm").classList.remove("hidden"); }
function showHome(){ $("#authView").classList.add("hidden"); $("#homeView").classList.remove("hidden"); $(".bottom-nav").classList.remove("hidden"); $("#logoutButton").classList.remove("hidden"); loadProjects(); }
async function loadProjects(){ try{ const projects=await request("/v1/projects"); homeProjects=projects; const list=$("#projectList"); if(!projects.length){ list.innerHTML=`<div class="empty-state"><span>⌁</span><b>${t("empty")}</b><small>${t("emptyHint")}</small></div>`; return; } list.innerHTML=projects.map(p=>`<button class="project" type="button" data-project-id="${p.id}" data-project-mode="${p.mode}"><div class="project-top"><span class="project-icon"></span><small>${t(p.mode==="document"?"smartScan":p.mode)}</small></div><div><h3>${escapeHtml(p.title)}</h3><small>${new Date(p.updated_at).toLocaleDateString(locale)}</small></div></button>`).join(""); if(restoredProjectId){ const restored=projects.find(project=>project.id===restoredProjectId); restoredProjectId=null; if(restored) openProjectEditor(restored); } }catch(error){ $("#projectList").innerHTML=`<div class="empty-state"><b>${escapeHtml(localizedError(error))}</b></div>`; } }
function escapeHtml(value){ const node=document.createElement("div"); node.textContent=value; return node.innerHTML; }

function clearEditorImage(){ if(editorImageUrl) URL.revokeObjectURL(editorImageUrl); editorImageUrl=null; $("#editorImage").removeAttribute("src"); }
function renderEditorCorners(){ const points=editorCorners.map(corner=>`${corner.x*1000},${corner.y*1000}`).join(" "); const labels=["cornerTopLeft","cornerTopRight","cornerBottomRight","cornerBottomLeft"]; $("#cornerPolygon").setAttribute("points",points); document.querySelectorAll("[data-corner]").forEach((handle,index)=>{ const corner=editorCorners[index]; handle.setAttribute("cx",corner.x*1000); handle.setAttribute("cy",corner.y*1000); handle.setAttribute("aria-label",editorCopy[locale][labels[index]]); handle.setAttribute("aria-valuenow",Math.round(corner.x*100)); handle.setAttribute("aria-valuetext",`x ${Math.round(corner.x*100)}%, y ${Math.round(corner.y*100)}%`); }); }
function renderEditorState(){
  const page=editorPages[editorIndex];
  $("#editorProjectTitle").textContent=editorProject?.title||editorCopy[locale].title;
  $("#editorPageList").innerHTML=editorPages.map((item,index)=>`<button type="button" class="page-chip ${index===editorIndex?"active":""}" data-page-index="${index}"><b>${index+1}</b><small>${escapeHtml(bookSideLabel(item,locale)||(item.quality_warning?"!":"✓"))}</small></button>`).join("");
  $("#movePageLeft").disabled=editorIndex<=0;
  $("#movePageRight").disabled=editorIndex<0||editorIndex>=editorPages.length-1;
  $("#qualityMessage").textContent=qualityPrompt(page,locale);
  $("#confirmReview").classList.toggle("hidden",!page||page.review_status!=="pending");
  const examPrompt=examSuggestionPrompt(page,locale);
  $("#examSuggestion").classList.toggle("hidden",!examPrompt);
  $("#examSuggestionText").textContent=examPrompt;
  $("#dismissExamSuggestion").disabled=!canDismissExamSuggestion(page);
  $("#bookRetake").classList.toggle("hidden",!canRetakeBookSide(page));
  document.querySelectorAll("[data-page-filter]").forEach(button=>button.classList.toggle("active",button.dataset.pageFilter===editorFilter));
  $("#editorImage").style.filter=filterPreview(editorFilter);
  renderEditorCorners();
  if(editorProject?.mode==="book") renderBookIntegrity();
}
function aiText(key, values={}){ return Object.entries(values).reduce((text,[name,value])=>text.replace(`{${name}}`,String(value)),editorCopy[locale][key]||key); }
function aiStatusText(status){ return editorCopy[locale][{queued:"aiQueued",processing:"aiProcessing",candidate_ready:"aiCandidateReady",accepted:"aiAccepted",rejected:"aiRejected",stale:"aiStale",failed:"aiFailed",canceled:"aiCanceled"}[status]]||status||editorCopy[locale].aiNoSuggestion; }
function aiCandidateLabel(row){
  const label=editorCopy[locale][{classification:"aiClassification",orientation:"aiOrientation",title:"aiTitleSuggestion",pageNumber:"aiPageNumber",formula:"aiFormula",table:"aiTable",layout:"aiLayout"}[row.kind]]||row.kind;
  let value=row.value;
  if(row.kind==="classification") value=t(row.value==="document"?"smartScan":row.value);
  if(row.kind==="orientation") value=aiText("aiOrientationValue",{value:row.value});
  const confidence=confidencePercent(row.confidence);
  return {label,value,confidence:confidence===null?"":aiText("aiConfidence",{value:confidence})};
}
function currentAiEnhancement(){ const page=editorPages[editorIndex]; return latestEnhancement(aiEnhancements,page?.active_result_version,aiEnhancementKind); }
function stopAiPolling(){ if(aiPollTimer!==null) clearTimeout(aiPollTimer); aiPollTimer=null; }
function scheduleAiPolling(){ stopAiPolling(); if(editorProject&&shouldPollEnhancements(aiEnhancements)) aiPollTimer=setTimeout(()=>loadAiWorkspace({silent:true}),2500); }
function renderAiWorkspace(){
  const page=editorPages[editorIndex];
  const available=Boolean(aiCapabilities?.available&&aiCapabilities?.business_orchestration_ready);
  const capabilityKey=!aiCapabilities?.business_orchestration_ready&&aiCapabilities?"aiOrchestrationUnavailable":available?"aiAvailable":"aiUnavailable";
  $("#aiAvailability").textContent=editorCopy[locale][capabilityKey];
  const executionMode=aiCapabilities?.execution_mode;
  const modeBadge=$("#aiModeBadge");
  modeBadge.classList.toggle("hidden",!available||!(["mock","provider"].includes(executionMode)));
  modeBadge.textContent=executionMode==="mock"?editorCopy[locale].aiMockMode:executionMode==="provider"?editorCopy[locale].aiProviderMode:"";
  $("#aiProjectEnabled").checked=aiDesiredEnabled===null?Boolean(editorProject?.ai_enabled):aiDesiredEnabled;
  $("#aiProjectEnabled").disabled=aiBusy||(!aiCapabilities&&!editorProject?.ai_enabled);
  $("#aiTransmissionNotice").textContent=editorCopy[locale].aiTransmissionNotice;
  $("#aiConsentVersion").textContent=aiCapabilities?.consent_version?aiText("aiConsentVersion",{version:aiCapabilities.consent_version}):"";
  const enhancement=currentAiEnhancement();
  const kindSelect=$("#aiEnhancementKind");
  const supportsComplex=Boolean(aiCapabilities?.enhancement_kinds?.includes("complex_ocr")&&aiCapabilities?.task_types?.includes("ocr_formula"));
  kindSelect.value=aiEnhancementKind;
  kindSelect.disabled=aiBusy;
  kindSelect.querySelector('option[value="complex_ocr"]').disabled=!supportsComplex;
  const badge=$("#aiStatusBadge");
  badge.dataset.status=enhancement?.status||"idle";
  badge.textContent=enhancement?aiStatusText(enhancement.status):(editorProject?.ai_enabled?editorCopy[locale].aiNoSuggestion:editorCopy[locale].aiDisabled);
  const kindSupported=aiEnhancementKind==="complex_ocr"?supportsComplex:Boolean(aiCapabilities?.enhancement_kinds?.includes("recommended"));
  const canRequest=available&&kindSupported&&editorProject?.ai_enabled&&page?.active_result_version>0&&!aiBusy&&!shouldPollEnhancements(aiEnhancements);
  $("#requestAiSuggestion").disabled=!canRequest;
  $("#refreshAiSuggestion").disabled=!page||aiBusy;
  const rows=aiCandidateSummary(enhancement).map(aiCandidateLabel);
  const comparison=$("#aiComparison");
  comparison.classList.toggle("hidden",!enhancement||(!rows.length&&!enhancement.source_result_version));
  $("#aiBaseSummary").textContent=enhancement?aiText("aiBaseVersion",{version:enhancement.source_result_version}):aiText("aiCurrentVersion",{version:page?.active_result_version||0});
  $("#aiCandidateList").innerHTML=rows.length?rows.map(row=>`<div class="ai-candidate-row"><div><b>${escapeHtml(row.label)}</b><small>${escapeHtml(row.confidence)}</small></div><span>${escapeHtml(row.value)}</span></div>`).join(""):`<small>${editorCopy[locale].aiNoCandidate}</small>`;
  const canDecide=canDecideEnhancement(enhancement,page?.active_result_version)&&!aiBusy;
  $("#aiDecisionActions").classList.toggle("hidden",!canDecide);
  $("#acceptAiSuggestion").disabled=!canDecide;
  $("#rejectAiSuggestion").disabled=!canDecide;
  const sourcePreview=sourceVersionPreview(enhancement,page);
  $("#previewAiBase").classList.toggle("hidden",!sourcePreview||aiPreviewingSource);
  $("#previewAiCurrent").classList.toggle("hidden",!sourcePreview||!aiPreviewingSource);
}
async function loadAiWorkspace({silent=false}={}){
  const page=editorPages[editorIndex];
  if(!editorProject||!page){ aiEnhancements=[]; renderAiWorkspace(); return; }
  const expectedPageId=page.id;
  stopAiPolling();
  try{
    const [capabilities,enhancements]=await Promise.all([request("/v1/ai/capabilities"),request(`/v1/pages/${expectedPageId}/ai-enhancements`)]);
    if(editorPages[editorIndex]?.id!==expectedPageId) return;
    aiCapabilities=capabilities;
    aiEnhancements=enhancements;
    if(!silent) $("#aiMessage").textContent=editorProject.ai_enabled?editorCopy[locale].aiEnabled:editorCopy[locale].aiDisabled;
  }catch(error){
    if(editorPages[editorIndex]?.id===expectedPageId){ aiCapabilities=null; aiEnhancements=[]; $("#aiMessage").textContent=`${editorCopy[locale].aiFailed}：${localizedError(error)}`; }
  }finally{
    if(editorPages[editorIndex]?.id===expectedPageId){ renderAiWorkspace(); scheduleAiPolling(); }
  }
}
async function updateProjectAiSetting(enabled){
  if(!editorProject||aiBusy) return;
  if(enabled&&!(aiCapabilities?.available&&aiCapabilities?.business_orchestration_ready)){ $("#aiProjectEnabled").checked=false; $("#aiMessage").textContent=editorCopy[locale].aiUnavailable; return; }
  aiBusy=true; aiDesiredEnabled=enabled; $("#aiMessage").textContent=editorCopy[locale].aiEnabling; renderAiWorkspace();
  try{
    editorProject=await request(`/v1/projects/${editorProject.id}/ai-settings`,{method:"PUT",body:JSON.stringify({enabled,consent_version:enabled?aiCapabilities.consent_version:null})});
    $("#aiMessage").textContent=editorCopy[locale].aiSettingsSaved;
  }catch(error){ $("#aiMessage").textContent=localizedError(error); }
  finally{ aiBusy=false; aiDesiredEnabled=null; renderAiWorkspace(); }
}
async function requestAiSuggestion(){
  const page=editorPages[editorIndex];
  if(!page||!editorProject?.ai_enabled||aiBusy) return;
  aiBusy=true; $("#aiMessage").textContent=editorCopy[locale].aiRequesting; renderAiWorkspace();
  try{
    const enhancement=await request(`/v1/pages/${page.id}/ai-enhancements`,{method:"POST",headers:{"Idempotency-Key":createAiIdempotencyKey(page.id,page.active_result_version)},body:JSON.stringify({enhancement_kind:aiEnhancementKind,source_result_version:page.active_result_version})});
    aiEnhancements=[enhancement,...aiEnhancements.filter(item=>item.id!==enhancement.id)];
    $("#aiMessage").textContent=aiStatusText(enhancement.status);
  }catch(error){ $("#aiMessage").textContent=`${editorCopy[locale].aiFailed}：${localizedError(error)}`; }
  finally{ aiBusy=false; renderAiWorkspace(); scheduleAiPolling(); }
}
async function decideAiSuggestion(accept){
  const page=editorPages[editorIndex],enhancement=currentAiEnhancement();
  if(!canDecideEnhancement(enhancement,page?.active_result_version)||aiBusy) return;
  aiBusy=true; renderAiWorkspace();
  try{
    const updated=await request(`/v1/ai-enhancements/${enhancement.id}/${accept?"accept":"reject"}`,{method:"POST"});
    aiEnhancements=aiEnhancements.map(item=>item.id===updated.id?updated:item);
    if(accept){
      const pageId=page.id;
      editorPages=await request(`/v1/projects/${editorProject.id}/pages`);
      const index=Math.max(0,editorPages.findIndex(item=>item.id===pageId));
      await selectEditorPage(index);
      $("#aiMessage").textContent=editorCopy[locale].aiAcceptedDone;
      loadProjects();
    }else $("#aiMessage").textContent=editorCopy[locale].aiRejectedDone;
  }catch(error){ $("#aiMessage").textContent=localizedError(error); }
  finally{ aiBusy=false; renderAiWorkspace(); scheduleAiPolling(); }
}
async function previewAiSource(useSource){
  const page=editorPages[editorIndex],enhancement=currentAiEnhancement();
  const version=sourceVersionPreview(enhancement,page);
  if(!page||!version) return;
  if(!useSource){ aiPreviewingSource=false; await selectEditorPage(editorIndex); $("#aiMessage").textContent=editorCopy[locale].aiCurrentPreviewing; return; }
  try{
    const blob=await auth.requestBlob(`/v1/pages/${page.id}/content?version=${version}`);
    clearEditorImage(); editorImageUrl=URL.createObjectURL(blob); $("#editorImage").src=editorImageUrl; aiPreviewingSource=true; renderAiWorkspace(); $("#aiMessage").textContent=editorCopy[locale].aiBasePreviewing;
  }catch(error){ $("#aiMessage").textContent=localizedError(error); }
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
function bookDecisionLabel(action){ return editorCopy[locale][{ignored:"bookIgnore",confirmed_absent:"bookConfirmAbsent",keep_both:"bookKeepBoth",exclude_duplicate:"bookExcludeDuplicate",reopen:"bookReopen"}[action]]||action; }
function renderBookIntegrity(){
  const section=$("#bookIntegrity");
  const visible=editorProject?.mode==="book";
  section.classList.toggle("hidden",!visible);
  if(!visible) return;
  const summary=$("#bookIntegritySummary"),list=$("#bookIntegrityList"),button=$("#completeBook");
  if(!editorBookIntegrity){ summary.textContent=editorCopy[locale].bookIntegrityLoading; list.innerHTML=""; button.disabled=true; return; }
  summary.textContent=editorBookIntegrity.ready_to_assemble
    ?editorCopy[locale].bookReady
    :`${editorCopy[locale].bookNeedsReview} ${editorBookIntegrity.blocking_issue_count}`;
  list.innerHTML=editorBookIntegrity.issues.length?editorBookIntegrity.issues.map((issue,index)=>{
    const actions=integrityDecisionOptions(issue).map(action=>`<button class="secondary" type="button" data-book-decision-index="${index}" data-book-decision="${action}">${escapeHtml(bookDecisionLabel(action))}</button>`).join("");
    const supplement=issue.kind==="missing_page"&&!issue.decision?`<button class="secondary" type="button" data-book-supplement-index="${index}">${editorCopy[locale].bookSupplement}</button>`:"";
    return `<article class="export-card"><div><b>${escapeHtml(integrityIssueLabel(issue,locale))}</b><br><small>${issue.blocking?editorCopy[locale].bookBlocking:editorCopy[locale].bookHandled}</small></div><div class="artifact-actions">${supplement}${actions}</div></article>`;
  }).join(""):`<div class="empty-state"><small>${editorCopy[locale].bookNoIssues}</small></div>`;
  button.disabled=!editorBookIntegrity.ready_to_assemble;
  const page=editorPages[editorIndex];
  $("#bookPageNumber").textContent=page?pageNumberBadge(page,locale):"";
}
function stopProjectFilePolling(){ if(editorPollTimer!==null) clearTimeout(editorPollTimer); editorPollTimer=null; }
function scheduleProjectFilePolling(){ stopProjectFilePolling(); if(editorProject&&shouldPollJobs(editorJobs)) editorPollTimer=setTimeout(()=>loadProjectFiles({silent:true}),3000); }
async function loadProjectFiles({silent=false}={}){
  if(!editorProject) return;
  const projectId=editorProject.id;
  if(!silent) $("#projectFilesMessage").textContent=editorCopy[locale].loading;
  stopProjectFilePolling();
  try{ const [jobs,exports,integrity]=await Promise.all([request("/v1/jobs"),request(`/v1/projects/${projectId}/exports`),editorProject.mode==="book"?request(`/v1/projects/${projectId}/book-integrity`):Promise.resolve(null)]); if(editorProject?.id!==projectId) return; editorJobs=projectJobs(jobs,projectId); editorExports=exports; editorBookIntegrity=integrity; renderProjectFiles(); renderBookIntegrity(); if(!silent) $("#projectFilesMessage").textContent=""; }
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
  editorIndex=index; editorCorners=defaultCorners(); editorCornersDirty=false; editorFilter="original"; aiEnhancements=[]; aiPreviewingSource=false; clearEditorImage(); renderEditorState(); renderAiWorkspace(); loadAiWorkspace(); $("#editorMessage").textContent=editorCopy[locale].loading;
  const expectedId=editorPages[index].id;
  try{ const blob=await auth.requestBlob(`/v1/pages/${expectedId}/content`); if(editorPages[editorIndex]?.id!==expectedId) return; editorImageUrl=URL.createObjectURL(blob); $("#editorImage").src=editorImageUrl; $("#editorMessage").textContent=""; }
  catch(error){ $("#editorMessage").textContent=localizedError(error); }
}
async function openProjectEditor(project){
  const projectId=project.id; editorProject=project; editorPages=[]; editorJobs=[]; editorExports=[]; editorArtifacts=[]; editorBookIntegrity=null; pendingBookSupplement=null; editorIndex=-1; aiCapabilities=null; aiEnhancements=[]; aiPreviewingSource=false; aiDesiredEnabled=null; aiEnhancementKind="recommended"; clearEditorImage(); history.replaceState(null,"",`#project=${encodeURIComponent(projectId)}`); $("#editorDialog").showModal(); $("#editorMessage").textContent=editorCopy[locale].loading; renderProjectFiles(); renderBookIntegrity(); renderAiWorkspace(); loadProjectFiles();
  try{ editorPages=await request(`/v1/projects/${projectId}/pages`); if(!editorPages.length){ $("#editorPageList").innerHTML=""; $("#editorMessage").textContent=editorCopy[locale].empty; renderAiWorkspace(); return; } await selectEditorPage(0); }
  catch(error){ $("#editorMessage").textContent=localizedError(error); }
}
async function rotateEditorPage(degrees){ const page=editorPages[editorIndex]; if(!page) return; try{ const updated=await request(`/v1/pages/${page.id}/rotations`,{method:"POST",body:JSON.stringify({degrees})}); editorPages[editorIndex]=updated; await selectEditorPage(editorIndex); }catch(error){ $("#editorMessage").textContent=localizedError(error); } }
async function reorderEditorPage(delta){ const moved=movePage(editorPages,editorIndex,delta); if(moved.index===editorIndex) return; try{ const ordered=await request(`/v1/projects/${editorProject.id}/pages/order`,{method:"PATCH",body:JSON.stringify({page_ids:moved.pages.map(page=>page.id)})}); editorPages=ordered; editorIndex=moved.index; renderEditorState(); $("#editorMessage").textContent=editorCopy[locale].ordered; }catch(error){ $("#editorMessage").textContent=localizedError(error); } }
async function saveEditorPage(){ const page=editorPages[editorIndex]; if(!page) return; if(!editorCornersDirty&&editorFilter==="original"){ $("#editorMessage").textContent=editorCopy[locale].noChange; return; } const payload={filter:editorFilter}; if(editorCornersDirty) payload.corners=editorCorners; try{ const updated=await request(`/v1/pages/${page.id}/edits`,{method:"POST",body:JSON.stringify(payload)}); editorPages[editorIndex]=updated; await selectEditorPage(editorIndex); $("#editorMessage").textContent=editorCopy[locale].saved; }catch(error){ $("#editorMessage").textContent=localizedError(error); } }
async function retakeBookSide(file){ const page=editorPages[editorIndex]; if(!canRetakeBookSide(page)||!file) return; const form=new FormData(); form.append("file",file,file.name); $("#retakeBookSide").disabled=true; $("#editorMessage").textContent=editorCopy[locale].retakingBookSide; try{ const replacement=await request(`/v1/pages/${page.id}/book-retakes`,{method:"POST",body:form}); editorPages[editorIndex]=replacement; await selectEditorPage(editorIndex); await loadProjectFiles({silent:true}); $("#editorMessage").textContent=editorCopy[locale].retakenBookSide; }catch(error){ $("#editorMessage").textContent=localizedError(error); }finally{ $("#retakeBookSide").disabled=false; $("#bookRetakeFile").value=""; } }
async function decideBookIntegrity(issue,decision){ if(!editorProject||!issue) return; try{ editorBookIntegrity=await request(`/v1/projects/${editorProject.id}/book-integrity/decision`,{method:"PUT",body:JSON.stringify({issue_key:issue.key,decision})}); renderBookIntegrity(); }catch(error){ $("#bookIntegrityMessage").textContent=localizedError(error); } }
async function uploadBookSupplement(file){ if(!editorProject||!pendingBookSupplement||!file) return; const form=new FormData(); form.append("file",file,file.name); form.append("insert_at",String(pendingBookSupplement.insertAt)); form.append("expected_page_label",pendingBookSupplement.expectedPageLabel); try{ $("#bookIntegrityMessage").textContent=editorCopy[locale].bookSupplementing; await request(`/v1/projects/${editorProject.id}/book-supplements`,{method:"POST",body:form}); editorPages=await request(`/v1/projects/${editorProject.id}/pages`); pendingBookSupplement=null; await loadProjectFiles({silent:true}); renderEditorState(); $("#bookIntegrityMessage").textContent=editorCopy[locale].bookSupplemented; }catch(error){ $("#bookIntegrityMessage").textContent=localizedError(error); }finally{ $("#bookSupplementFile").value=""; } }
async function completeBook(){ if(!editorProject||!editorBookIntegrity?.ready_to_assemble) return; const button=$("#completeBook"); button.disabled=true; try{ $("#bookIntegrityMessage").textContent=editorCopy[locale].bookAssembling; await request(`/v1/projects/${editorProject.id}/book-assemblies`,{method:"POST",body:JSON.stringify({quality:$("#exportQuality").value,include_ocr_text:$("#exportOcr").checked})}); await loadProjectFiles({silent:true}); $("#bookIntegrityMessage").textContent=editorCopy[locale].bookAssembled; }catch(error){ $("#bookIntegrityMessage").textContent=localizedError(error); }finally{ renderBookIntegrity(); } }
function setUploadProgress(uploaded,total){ const percent=Math.min(100,Math.round(uploaded/total*100)); $("#uploadProgressWrap").classList.remove("hidden"); $("#uploadProgress").value=percent; $("#uploadPercent").textContent=`${percent}%`; }
function bookAutoStatusKey(){ const blocker=bookAutoState.blocker; return blocker?{waiting_for_page_change:"bookAutoWaitPage",page_moving:"bookAutoWaitStable",needs_focus:"bookAutoWaitFocus",exposure_invalid:"bookAutoExposure",boundary_incomplete:"bookAutoBoundary",spine_not_found:"bookAutoSpine",occlusion_detected:"bookAutoOcclusion",verifying:"bookAutoVerifying",retry_required:"bookAutoRetry"}[blocker]:bookAutoState.phase==="CAPTURE"?"bookAutoCapturing":"bookAutoChecking"; }
function renderBookAutoStatus(){ $("#bookAutoStatus").textContent=t(bookAutoStatusKey()); }
function stopBookAutoAnalysis(){ if(bookAutoTimer) clearInterval(bookAutoTimer); bookAutoTimer=null; previousBookLuma=null; bookAutoState=initialBookAutoCaptureState(); renderBookAutoStatus(); }
function resetCamera(){ stopBookAutoAnalysis(); stopCamera(cameraStream); cameraStream=null; bookAutoCaptureBusy=false; $("#cameraPreview").srcObject=null; $("#cameraPanel").classList.add("hidden"); }
function clearPreview(){ if(previewUrl) URL.revokeObjectURL(previewUrl); previewUrl=null; $("#capturePreview").removeAttribute("src"); $("#capturePreview").classList.add("hidden"); }
function showPreview(file){ clearPreview(); if(!file?.type?.startsWith("image/")) return; previewUrl=URL.createObjectURL(file); $("#capturePreview").src=previewUrl; $("#capturePreview").classList.remove("hidden"); }
function openCapture(nextMode="document"){ mode=nextMode; capturedFile=null; clearPreview(); $("#pageFile").value=""; $("#fileName").textContent=t("originalKept"); $("#captureTitle").textContent=t(nextMode==="document"?"smartScan":nextMode); $("#projectTitle").value=`${t(nextMode==="document"?"smartScan":nextMode)}_${new Date().toISOString().slice(0,10).replaceAll("-","")}`; $("#bookAutoControls").classList.toggle("hidden",nextMode!=="book"); $("#bookAutoEnabled").checked=nextMode==="book"; renderBookAutoStatus(); $("#captureDialog").showModal(); }
$("#languageButton").addEventListener("click",()=>{ locale=locale==="zh-CN"?"en":"zh-CN"; localStorage.setItem("smartscan.locale",locale); renderLocale(); if(auth.isAuthenticated) loadProjects(); });
$("#loginForm").addEventListener("submit",async event=>{ event.preventDefault(); const data=Object.fromEntries(new FormData(event.currentTarget)); try{ $("#authMessage").textContent=""; await auth.login(data.username,data.password); showHome(); }catch(error){ $("#authMessage").textContent=localizedError(error); } });
$("#wecomLoginButton").addEventListener("click",async event=>{ const button=event.currentTarget; button.disabled=true; try{ $("#authMessage").textContent=t("processingLogin"); const start=await auth.beginWeCom(); location.assign(start.authorization_url); }catch(error){ $("#authMessage").textContent=localizedError(error); button.disabled=false; } });
$("#sendBindingCode").addEventListener("click",async event=>{ const button=event.currentTarget,phone=$("#bindingPhone").value.trim(); if(!phone){ $("#bindingMessage").textContent=locale==="zh-CN"?"请先填写手机号。":"Enter a phone number first."; return; } button.disabled=true; try{ const challenge=await auth.requestBindingCode(phone); bindingChallengeId=challenge.challenge_id; $("#bindingMessage").textContent=locale==="zh-CN"?"验证码已发送，请在有效期内完成验证。":"Code sent. Complete verification before it expires."; setTimeout(()=>{ button.disabled=false; },challenge.retry_after_seconds*1000); }catch(error){ $("#bindingMessage").textContent=localizedError(error); button.disabled=false; } });
$("#phoneBindingForm").addEventListener("submit",async event=>{ event.preventDefault(); if(!bindingChallengeId){ $("#bindingMessage").textContent=locale==="zh-CN"?"请先发送验证码。":"Send an SMS code first."; return; } const data=Object.fromEntries(new FormData(event.currentTarget)); try{ await auth.bindWeComPhone({bindingTicket,phone:data.phone.trim(),challengeId:bindingChallengeId,code:data.sms_code.trim()}); showHome(); }catch(error){ $("#bindingMessage").textContent=localizedError(error); } });
$("#backToLogin").addEventListener("click",()=>{ bindingTicket=null; bindingChallengeId=null; showAuth(); });
$("#logoutButton").addEventListener("click",async()=>{ try{ await auth.logout(); }catch{ /* 本地令牌仍会被清理。 */ } restoredProjectId=null; preserveEditorRestore=false; if($("#editorDialog").open) $("#editorDialog").close(); showAuth(); $("#authMessage").textContent=locale==="zh-CN"?"已安全退出当前设备。":"Signed out on this device."; });
document.querySelectorAll("[data-mode]").forEach(button=>button.addEventListener("click",()=>openCapture(button.dataset.mode)));
$("#quickScan").addEventListener("click",()=>openCapture()); $("#refreshButton").addEventListener("click",loadProjects);
$("#projectList").addEventListener("click",event=>{ const button=event.target.closest("[data-project-id]"); if(button){ const project=homeProjects.find(item=>item.id===button.dataset.projectId); if(project) openProjectEditor(project); } });
$("#editorPageList").addEventListener("click",event=>{ const page=event.target.closest("[data-page-index]"); if(page) selectEditorPage(Number(page.dataset.pageIndex)); });
$("#closeEditor").addEventListener("click",()=>$("#editorDialog").close());
$("#editorDialog").addEventListener("close",()=>{ clearEditorImage(); stopProjectFilePolling(); stopAiPolling(); editorProject=null; editorPages=[]; editorJobs=[]; editorExports=[]; editorArtifacts=[]; editorBookIntegrity=null; pendingBookSupplement=null; aiCapabilities=null; aiEnhancements=[]; aiPreviewingSource=false; aiDesiredEnabled=null; editorIndex=-1; if(!preserveEditorRestore) restoredProjectId=null; preserveEditorRestore=false; history.replaceState(null,"","#home"); });
$("#rotatePageLeft").addEventListener("click",()=>rotateEditorPage(270));
$("#rotatePageRight").addEventListener("click",()=>rotateEditorPage(90));
$("#movePageLeft").addEventListener("click",()=>reorderEditorPage(-1));
$("#movePageRight").addEventListener("click",()=>reorderEditorPage(1));
$("#resetCorners").addEventListener("click",()=>{ editorCorners=defaultCorners(); editorCornersDirty=false; renderEditorState(); });
$("#savePageEdit").addEventListener("click",saveEditorPage);
$("#aiProjectEnabled").addEventListener("change",event=>updateProjectAiSetting(event.currentTarget.checked));
$("#aiEnhancementKind").addEventListener("change",event=>{ aiEnhancementKind=event.currentTarget.value; aiPreviewingSource=false; renderAiWorkspace(); });
$("#requestAiSuggestion").addEventListener("click",requestAiSuggestion);
$("#refreshAiSuggestion").addEventListener("click",()=>loadAiWorkspace());
$("#acceptAiSuggestion").addEventListener("click",()=>decideAiSuggestion(true));
$("#rejectAiSuggestion").addEventListener("click",()=>decideAiSuggestion(false));
$("#previewAiBase").addEventListener("click",()=>previewAiSource(true));
$("#previewAiCurrent").addEventListener("click",()=>previewAiSource(false));
$("#confirmReview").addEventListener("click",async()=>{ const page=editorPages[editorIndex]; if(!page) return; try{ const updated=await request(`/v1/pages/${page.id}/review`,{method:"PATCH",body:JSON.stringify({status:"confirmed",note:qualityPrompt(page,locale)})}); editorPages[editorIndex]=updated; renderEditorState(); $("#editorMessage").textContent=editorCopy[locale].confirmed; }catch(error){ $("#editorMessage").textContent=localizedError(error); } });
$("#dismissExamSuggestion").addEventListener("click",async()=>{ const page=editorPages[editorIndex]; if(!canDismissExamSuggestion(page)) return; try{ const updated=await request(`/v1/pages/${page.id}/exam-suggestion-dismissal`,{method:"PUT",body:JSON.stringify({result_version:page.exam_result_version,reason:"user_dismissed"})}); editorPages[editorIndex]=updated; renderEditorState(); $("#editorMessage").textContent=editorCopy[locale].examDismissed; }catch(error){ $("#editorMessage").textContent=localizedError(error); } });
$("#retakeBookSide").addEventListener("click",()=>$("#bookRetakeFile").click());
$("#bookRetakeFile").addEventListener("change",event=>retakeBookSide(event.target.files[0]));
$("#bookIntegrityList").addEventListener("click",event=>{ const supplement=event.target.closest("[data-book-supplement-index]"); if(supplement){ pendingBookSupplement=supplementDefaults(editorBookIntegrity.issues[Number(supplement.dataset.bookSupplementIndex)],editorPages); if(pendingBookSupplement) $("#bookSupplementFile").click(); return; } const button=event.target.closest("[data-book-decision-index]"); if(button) decideBookIntegrity(editorBookIntegrity.issues[Number(button.dataset.bookDecisionIndex)],button.dataset.bookDecision); });
$("#bookSupplementFile").addEventListener("change",event=>uploadBookSupplement(event.target.files[0]));
$("#completeBook").addEventListener("click",completeBook);
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
async function performCameraCapture(automatic=false){ if(bookAutoCaptureBusy||!cameraStream) return; const message=$("#captureMessage"),button=$("#takePhoto"); bookAutoCaptureBusy=true; button.disabled=true; try{ const blob=await captureCameraPhoto({stream:cameraStream,videoElement:$("#cameraPreview"),imageCaptureCtor:globalThis.ImageCapture}); capturedFile=cameraBlobToFile(blob); $("#pageFile").value=""; $("#fileName").textContent=capturedFile.name; showPreview(capturedFile); message.textContent=automatic?t("bookAutoCaptured"):(locale==="zh-CN"?"页面已拍摄，可创建并上传。":"Page captured and ready to upload."); resetCamera(); }catch(error){ resetCamera(); message.textContent=localizedError(error); }finally{ bookAutoCaptureBusy=false; button.disabled=false; } }
function analyzeBookPreview(){ if(mode!=="book"||!$("#bookAutoEnabled").checked||!cameraStream||bookAutoCaptureBusy) return; const video=$("#cameraPreview"); if(video.readyState<2||!video.videoWidth||!video.videoHeight) return; const canvas=document.createElement("canvas"); canvas.width=96; canvas.height=Math.max(54,Math.round(96*video.videoHeight/video.videoWidth)); const context=canvas.getContext("2d",{willReadFrequently:true}); if(!context) return; context.drawImage(video,0,0,canvas.width,canvas.height); const luma=lumaFromImageData(context.getImageData(0,0,canvas.width,canvas.height)); const analysis=analyzeBookLuma(luma,canvas.width,canvas.height,previousBookLuma); previousBookLuma=analysis.luma; const previous=bookAutoState; bookAutoState=reduceBookAutoCapture(bookAutoState,{type:"frame",signals:analysis.signals}); renderBookAutoStatus(); if(previous.phase!=="CAPTURE"&&bookAutoState.phase==="CAPTURE") performCameraCapture(true); }
function startBookAutoAnalysis(){ stopBookAutoAnalysis(); if(mode!=="book"||!$("#bookAutoEnabled").checked) return; bookAutoTimer=setInterval(analyzeBookPreview,250); }
$("#openCamera").addEventListener("click",async()=>{ const message=$("#captureMessage"); resetCamera(); try{ cameraStream=await openEnvironmentCamera({mediaDevices:navigator.mediaDevices,videoElement:$("#cameraPreview")}); $("#cameraPanel").classList.remove("hidden"); message.textContent=mode==="book"&&$("#bookAutoEnabled").checked?t("bookAutoManualFallback"):(locale==="zh-CN"?"相机已就绪，请手动拍摄。":"Camera ready. Capture when steady."); startBookAutoAnalysis(); }catch(error){ message.textContent=localizedError(error); } });
$("#takePhoto").addEventListener("click",()=>performCameraCapture(false));
$("#bookAutoEnabled").addEventListener("change",event=>{ if(event.currentTarget.checked) startBookAutoAnalysis(); else stopBookAutoAnalysis(); });
$("#stopCamera").addEventListener("click",resetCamera);
$("#captureDialog").addEventListener("close",()=>{ resetCamera(); clearPreview(); });
$("#pageFile").addEventListener("change",event=>{ resetCamera(); capturedFile=null; const file=event.target.files[0]; $("#fileName").textContent=file?.name||t("originalKept"); if(file) showPreview(file); else clearPreview(); });
$("#captureForm").addEventListener("submit",async event=>{ event.preventDefault(); if(event.submitter?.value==="cancel"){ $("#captureDialog").close(); return; } const message=$("#captureMessage"),button=$("#submitCapture"),file=capturedFile||$("#pageFile").files[0],title=$("#projectTitle").value; button.disabled=true; try{ message.textContent=locale==="zh-CN"?"正在校验文件并恢复上传进度…":"Checking the file and resuming upload…"; if(file){ await uploadResumable({file,title,mode,request,storage:localStorage,onProgress:setUploadProgress}); }else{ await request("/v1/projects",{method:"POST",body:JSON.stringify({title,mode,reading_order:"ltr"})}); } capturedFile=null; clearPreview(); $("#captureDialog").close(); message.textContent=""; $("#uploadProgress").value=0; $("#uploadPercent").textContent="0%"; $("#uploadProgressWrap").classList.add("hidden"); loadProjects(); }catch(error){ message.textContent=(locale==="zh-CN"?"上传已暂停，可重新提交继续：":"Upload paused. Submit again to resume: ")+localizedError(error); }finally{ button.disabled=false; } });
bindCameraLifecycle({documentTarget:document,windowTarget:window,onRelease:resetCamera});
async function initialize(){ renderLocale(); const params=new URLSearchParams(location.search),code=params.get("code"),state=params.get("state"); if(code&&state){ showAuth(); $("#authMessage").textContent=t("processingLogin"); try{ const result=await auth.completeWeComCallback(code,state); history.replaceState({},"",`${location.pathname}${location.hash}`); if(result.access_token) showHome(); else if(result.action==="require_phone_binding"&&result.binding_ticket) showPhoneBinding(result.binding_ticket); else throw new Error("wecom_callback_incomplete"); }catch(error){ history.replaceState({},"",`${location.pathname}${location.hash}`); showAuth(); $("#authMessage").textContent=localizedError(error); } return; } auth.isAuthenticated?showHome():showAuth(); }
initialize();

