import {expect, test} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const tinyPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");

async function expectNoWcagViolations(page) {
  const result = await new AxeBuilder({page}).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(result.violations, result.violations.map(item => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
}

async function installMockApi(page, {authenticated = false} = {}) {
  let exports = [];
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
    if (path === "/v1/projects" && request.method() === "GET") return json([{id:"p1",title:"期中资料",mode:"document",updated_at:"2026-10-20T00:00:00Z"}]);
    if (path === "/v1/projects/p1/pages") return json([{id:"page1",page_number:1,quality_warning:"low_contrast",review_status:"pending"}]);
    if (path === "/v1/pages/page1/content") return route.fulfill({status:200,contentType:"image/png",body:tinyPng});
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
