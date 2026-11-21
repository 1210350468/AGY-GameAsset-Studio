import argparse
import json
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:18333/")
args = parser.parse_args()
with urlopen(args.url + "api/config", timeout=12) as response:
    capability = json.load(response)["pixal_multiview_ready"]


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    response = page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
    assert response.status == 200
    assert page.locator("#quality-target").input_value() == "production"
    if capability:
        assert page.locator("#multi-views").is_checked()
    else:
        assert page.locator("#multi-views").is_disabled()
    assert page.locator("#multi-view-strategy").input_value() == "four"
    page.locator("#asset-title").fill("赛季四视角输入质量检查")
    page.locator("#asset-prompt").fill("华夏武侠游戏角色，完整四肢和可拆卸服饰")
    page.locator("#submit-job").click()
    page.locator("#notification").get_by_text("四张实际参考图", exact=False).wait_for(timeout=12000)
    assert page.locator("#submit-job").is_enabled()
    page.locator("#quality-target").select_option("prototype")
    assert page.locator("#quality-target").input_value() == "prototype"
    browser.close()

print("BROWSER_QUALITY_GUARD_OK：赛季四视角限制和概念实验切换均通过实际浏览器检查")
