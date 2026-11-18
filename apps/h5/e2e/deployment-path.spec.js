import {expect, test} from "@playwright/test";

test("H5 可从 /smartscan/ 子路径加载并保留 Hash 路由", async ({page}) => {
  await page.goto("/smartscan/#home");

  await expect(page).toHaveURL(/\/smartscan\/#home$/);
  await expect(page.locator(".brand")).toContainText("SmartScan");
  await expect(page.locator("script[src='app.js']")).toHaveCount(1);
});
