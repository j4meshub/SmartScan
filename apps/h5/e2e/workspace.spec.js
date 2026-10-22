import {expect, test} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const tinyPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");

async function expectNoWcagViolations(page) {
  const result = await new AxeBuilder({page}).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(result.violations, result.violations.map(item => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
}

async function installMockApi(page, {authenticated = false, aiAvailable = true, aiExecutionMode = "mock"} = {}) {
  let exports = [];
  let project = {id:"p1",owner_user_id:"u1",title:"期中资料",suggested_name:null,suggested_name_source:null,mode:"document",reading_order:"ltr",ai_enabled:false,ai_consent_version:null,ai_enabled_by_user_id:null,ai_enabled_at:null,created_at:"2026-10-20T00:00:00Z",updated_at:"2026-10-20T00:00:00Z"};
  let scanPage = {id:"page1",project_id:"p1",page_number:1,size_bytes:68,mime_type:"image/png",original_mime_type:"image/png",quality_warning:"low_contrast",quality_score:.7,quality_details:{},rotation_degrees:0,active_result_version:1,review_status:"pending",review_reason:null,reviewed_by_user_id:null,reviewed_at:null,ocr_text:null};
  let enhancements = [];
  await page.addInitScript(({authenticated}) => {
    localStorage.setItem("smartscan.api", `${location.origin}/api`);
    localStorage.setItem("smartscan.locale", "zh-CN");
    if (authenticated) sessionStorage.setItem("smartscan.auth.session.v1", JSON.stringify({access_token:"access",refresh_token:"refresh"}));
  }, {authenticated});
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    const json = body => route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
    if (path === "/v1/auth/login" && request.method() === "POST") return json({access_token:"access",refresh_token:"refresh",expires_at:"2099-01-01T00:00:00Z",refresh_expires_at:"2099-02-01T00:00:00Z",session_id:"session",device_id:"web:test"});
    if (path === "/v1/projects" && request.method() === "GET") return json([project]);
    if (path === "/v1/projects/p1/pages") return json([scanPage]);
    if (path === "/v1/pages/page1/content") return route.fulfill({status:200,contentType:"image/png",body:tinyPng});
    if (path === "/v1/ai/capabilities") return json({available:aiAvailable,business_orchestration_ready:true,execution_mode:aiAvailable?aiExecutionMode:"unavailable",consent_version:"2026-10-01",transmission_notice_code:"project_page_to_deployment_ai",enhancement_kinds:["recommended","complex_ocr"],task_types:["classify_page","detect_orientation","extract_title","extract_page_number","ocr_formula"]});
    if (path === "/v1/projects/p1/ai-settings" && request.method() === "PUT") {
      const payload=request.postDataJSON();
      project={...project,ai_enabled:payload.enabled,ai_consent_version:payload.enabled?payload.consent_version:null,ai_enabled_by_user_id:payload.enabled?"u1":null,ai_enabled_at:payload.enabled?"2026-10-20T00:02:00Z":null};
      return json(project);
    }
    if (path === "/v1/pages/page1/ai-enhancements" && request.method() === "GET") return json(enhancements);
    if (path === "/v1/pages/page1/ai-enhancements" && request.method() === "POST") {
      const payload=request.postDataJSON();
      const complex=payload.enhancement_kind==="complex_ocr";
      const tasks=complex
        ?{ocr_formula:{task_type:"ocr_formula",confidence:.92,blocks:[{block_type:"formula",block_id:"f1",box:{x0:.1,y0:.1,x1:.5,y1:.2},confidence:.96,latex_candidate:"x^2 + y^2 = z^2"},{block_type:"table",block_id:"t1",box:{x0:.1,y0:.3,x1:.9,y1:.6},confidence:.9,cells:[{row:0,column:0,text_candidate:"科目"},{row:0,column:1,text_candidate:"成绩"}]},{block_type:"layout",block_id:"l1",box:{x0:.1,y0:.7,x1:.9,y1:.9},confidence:.89,role:"paragraph",text_candidate:"复杂版面正文"}]}}
        :{classify_page:{label:"document",confidence:.91},detect_orientation:{rotation_degrees:90,confidence:.88},extract_title:{candidates:[{text:"期中复习提纲",confidence:.96}]},extract_page_number:{status:"not_found",confidence:.2}};
      const item={id:complex?"ai-complex":"ai1",project_id:"p1",page_id:"page1",processing_job_id:complex?"job-ai-complex":"job-ai1",enhancement_kind:payload.enhancement_kind,requested_tasks:complex?["ocr_formula"]:["classify_page","detect_orientation","extract_title","extract_page_number"],source_result_version:payload.source_result_version,status:"candidate_ready",candidate_result:{schema_version:"1.0",tasks},evidence:{mock:true},provider_id:"internal-provider",model:"internal-model",confidence:.91,error_code:null,accepted_by_user_id:null,accepted_at:null,rejected_at:null,created_at:"2026-10-20T00:03:00Z",updated_at:"2026-10-20T00:03:00Z"};
      enhancements=[item];
      return route.fulfill({status:202,contentType:"application/json",body:JSON.stringify(item)});
    }
    if (["/v1/ai-enhancements/ai1/accept","/v1/ai-enhancements/ai-complex/accept"].includes(path) && request.method() === "POST") {
      if (enhancements[0].enhancement_kind==="complex_ocr") scanPage={...scanPage,ocr_status:"ready",ocr_result_version:scanPage.active_result_version,ocr_text:"x^2 + y^2 = z^2\n科目 | 成绩\n复杂版面正文"};
      else { scanPage={...scanPage,rotation_degrees:90,active_result_version:2}; project={...project,suggested_name:"期中复习提纲",suggested_name_source:"ai"}; }
      enhancements=[{...enhancements[0],status:"accepted",accepted_by_user_id:"u1",accepted_at:"2026-10-20T00:04:00Z"}];
      return json(enhancements[0]);
    }
    if (path === "/v1/ai-enhancements/ai1/reject" && request.method() === "POST") {
      enhancements=[{...enhancements[0],status:"rejected",rejected_at:"2026-10-20T00:04:00Z"}];
      return json(enhancements[0]);
    }
    if (path === "/v1/jobs") return json([{id:"job1",project_id:"p1",kind:"baseline",status:"ready",progress:100,updated_at:"2026-10-20T00:00:00Z"}]);
    if (path === "/v1/projects/p1/exports" && request.method() === "GET") return json(exports);
    if (path === "/v1/projects/p1/exports" && request.method() === "POST") {
      exports = [{id:"export1",format:"pdf",quality:"balanced",status:"ready",created_at:"2026-10-20T00:01:00Z",artifacts:[{id:"artifact1",file_name:"期中资料.pdf",mime_type:"application/pdf",size_bytes:24}]}];
      return route.fulfill({status:201,contentType:"application/json",body:JSON.stringify(exports[0])});
    }
    if (path === "/v1/export-artifacts/artifact1/content") return route.fulfill({status:200,contentType:"application/pdf",body:"%PDF-1.4\n% SmartScan\n"});
    return route.fulfill({status:404,contentType:"application/json",body:JSON.stringify({detail:"not found"})});
  });
}

test("中文用户可恢复项目、查看任务、导出并在分享不可用时下载", async ({page}) => {
  await installMockApi(page);
  await page.goto("/");
  await page.getByLabel("用户名").fill("demo");
  await page.getByLabel("密码").fill("password");
  await page.getByRole("button", {name:"登录", exact:true}).click();
  await page.getByRole("button", {name:/期中资料/}).click();
  await expect(page).toHaveURL(/#project=p1$/);
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("处理完成")).toBeVisible();
  await expectNoWcagViolations(page);

  const topLeft = page.locator('[data-corner="0"]');
  await topLeft.focus();
  await topLeft.press("ArrowRight");
  await expect(topLeft).toHaveAttribute("aria-valuetext", "x 1%, y 0%");

  await page.getByRole("button", {name:"生成导出"}).click();
  await expect(page.getByText("期中资料.pdf")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", {name:"分享"}).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("期中资料.pdf");
  await expect(page.getByText("当前浏览器无法分享文件，已改为下载。")).toBeVisible();
});

test("英文界面覆盖可见文本与无障碍名称", async ({page}) => {
  await installMockApi(page);
  await page.goto("/");
  await page.getByRole("button", {name:"切换语言"}).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("button", {name:"Sign in", exact:true})).toBeVisible();
  await expect(page.locator("nav.bottom-nav")).toHaveAttribute("aria-label", "Main navigation");
  await expect(page.getByRole("button", {name:"Switch language"})).toBeVisible();
  await expectNoWcagViolations(page);

  const unnamed = await page.locator("button, a, input, select").evaluateAll(elements => elements.filter(element => {
    const label = element.getAttribute("aria-label") || element.textContent?.trim();
    if (element.tagName === "INPUT") return !element.labels?.length && !label;
    return !label;
  }).map(element => element.outerHTML));
  expect(unnamed).toEqual([]);
});

test("已认证刷新会从 URL 项目断点恢复工作区", async ({page}) => {
  await installMockApi(page, {authenticated:true});
  await page.goto("/#project=p1");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("heading", {name:"期中资料"})).toBeVisible();
  await expect(page.getByText("处理完成")).toBeVisible();
});

test("项目授权后可获取、对比、接受 AI 建议并回看基础版本", async ({page}) => {
  await installMockApi(page, {authenticated:true});
  await page.goto("/#project=p1");
  const dialog=page.getByRole("dialog");
  await expect(dialog.getByText("AI 服务可用")).toBeVisible();
  await expect(dialog.getByText("模拟 AI", {exact:true})).toBeVisible();
  await expect(dialog.getByText(/仅在你主动请求建议时/)).toBeVisible();
  await dialog.getByRole("checkbox", {name:"为此项目启用 AI"}).click();
  await expect(dialog.getByText("项目 AI 设置已保存。")).toBeVisible();
  await dialog.getByRole("button", {name:"获取当前页智能建议"}).click();
  await expect(dialog.getByText("AI 候选建议")).toBeVisible();
  await expect(dialog.getByText("期中复习提纲")).toBeVisible();
  await expect(dialog.getByText("顺时针旋转 90°")).toBeVisible();
  await expect(dialog).not.toContainText("internal-provider");
  await expect(dialog).not.toContainText("internal-model");
  await expectNoWcagViolations(page);

  await dialog.getByRole("button", {name:"接受建议"}).click();
  await expect(dialog.getByRole("button", {name:"查看基础版本"})).toBeVisible();
  await dialog.getByRole("button", {name:"查看基础版本"}).click();
  await expect(dialog.getByText(/正在查看建议来源的基础版本/)).toBeVisible();
  await dialog.getByRole("button", {name:"返回当前版本"}).click();
  await expect(dialog.getByText("已返回当前版本预览。")).toBeVisible();
});

test("真实 AI 模式只显示用户可理解的模式标识", async ({page}) => {
  await installMockApi(page, {authenticated:true,aiExecutionMode:"provider"});
  await page.goto("/#project=p1");
  const dialog=page.getByRole("dialog");
  await expect(dialog.getByText("真实 AI", {exact:true})).toBeVisible();
  await expect(dialog).not.toContainText("local-real");
});

test("用户可选择复杂 OCR、核对结构化候选并确认进入文字层", async ({page}) => {
  await installMockApi(page, {authenticated:true});
  await page.goto("/#project=p1");
  const dialog=page.getByRole("dialog");
  await dialog.getByRole("checkbox", {name:"为此项目启用 AI"}).click();
  await dialog.getByLabel("分析类型").selectOption("complex_ocr");
  await dialog.getByRole("button", {name:"获取当前页智能建议"}).click();
  await expect(dialog.getByText("x^2 + y^2 = z^2")).toBeVisible();
  await expect(dialog.getByText("科目 | 成绩")).toBeVisible();
  await expect(dialog.getByText("复杂版面正文")).toBeVisible();
  await expect(dialog).not.toContainText("internal-provider");
  await expectNoWcagViolations(page);
  await dialog.getByRole("button", {name:"接受建议"}).click();
  await expect(dialog.getByRole("button", {name:"查看基础版本"})).toBeHidden();
  await expect(dialog.getByLabel("PDF 包含 OCR 文本层")).toBeEnabled();
});

test("AI 未配置时保持基础编辑与导出可用且不允许发起建议", async ({page}) => {
  await installMockApi(page, {authenticated:true,aiAvailable:false});
  await page.goto("/#project=p1");
  const dialog=page.getByRole("dialog");
  await expect(dialog.getByText(/AI 服务未配置/)).toBeVisible();
  await expect(dialog.getByRole("button", {name:"获取当前页智能建议"})).toBeDisabled();
  await expect(dialog.getByRole("button", {name:"生成导出"})).toBeEnabled();
  await dialog.getByRole("checkbox", {name:"为此项目启用 AI"}).click();
  await expect(dialog.getByRole("checkbox", {name:"为此项目启用 AI"})).not.toBeChecked();
  await expect(dialog.locator("#aiMessage")).toContainText("基础扫描与导出不受影响");
});

test("用户可放弃 AI 候选且基础页面版本保持不变", async ({page}) => {
  await installMockApi(page, {authenticated:true});
  await page.goto("/#project=p1");
  const dialog=page.getByRole("dialog");
  await expect(dialog.getByText("AI 服务可用")).toBeVisible();
  await dialog.getByRole("checkbox", {name:"为此项目启用 AI"}).click();
  await expect(dialog.getByText("项目 AI 设置已保存。")).toBeVisible();
  await dialog.getByRole("button", {name:"获取当前页智能建议"}).click();
  await dialog.getByRole("button", {name:"放弃建议"}).click();
  await expect(dialog.getByText("建议已放弃，基础结果未改变")).toBeVisible();
  await expect(dialog.getByRole("button", {name:"查看基础版本"})).toBeHidden();
});
