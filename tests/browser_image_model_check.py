import json
import sys

from playwright.sync_api import sync_playwright


sys.stdout.reconfigure(encoding="utf-8")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        channel="msedge", headless=True,
        args=["--enable-webgl", "--enable-unsafe-swiftshader"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    problems = []
    page.on("pageerror", lambda error: problems.append(str(error)))
    response = page.goto("http://127.0.0.1:18333/", wait_until="domcontentloaded", timeout=30000)
    assert response.status == 200
    page.wait_for_function(
        "document.querySelector('#image-model-notice').textContent.includes('原画模型决定')",
        timeout=18000,
    )
    available_models = page.locator("#image-model option").evaluate_all(
        "options => options.map(option => ({id: option.value, label: option.textContent, disabled: option.disabled}))"
    )
    assert len(available_models) == 4
    assert page.locator("#image-model").input_value() == "qwen"
    assert not next(option for option in available_models if option["id"] == "qwen")["disabled"]
    columns = page.locator(".studio-create-layout").evaluate("""element => {
      const main = element.querySelector('.studio-create-main').getBoundingClientRect();
      const sidebar = element.querySelector('.pipeline-sidebar').getBoundingClientRect();
      const shortcut = element.querySelector('.model-gallery-shortcut');
      return {mainRight: main.right, sidebarLeft: sidebar.left, shortcutInsideMain: shortcut?.closest('.studio-create-main') !== null};
    }""")
    assert columns["sidebarLeft"] >= columns["mainRight"]
    assert columns["shortcutInsideMain"]

    page.locator("#image-model").select_option("anima")
    page.locator("#image-count").select_option("4")
    page.locator("#multi-views").check()
    assert page.locator("#multi-views").is_checked()
    assert page.locator("#multiview-options").is_visible()
    assert page.locator("#view-back").is_enabled()
    page.locator("#multi-view-strategy").select_option("four")
    assert page.locator("#view-right").is_enabled()
    assert page.locator("#view-left").is_enabled()
    assert page.locator("#image-model").input_value() == "anima"
    assert page.locator("#image-count").input_value() == "4"

    page.locator("#model-mode").select_option("parts")
    assert page.locator("#multi-views").is_disabled()
    assert not page.locator("#multi-views").is_checked()
    assert page.locator("#multiview-options").is_hidden()
    page.locator("#model-mode").select_option("whole")
    assert page.locator("#multi-views").is_enabled()

    page.locator('[data-view="jobs"]').click()
    jobs_response = page.request.get("http://127.0.0.1:18333/api/jobs?limit=10")
    assert jobs_response.status == 200
    jobs = jobs_response.json()["jobs"]
    assert jobs, "真实服务器当前没有可供检查的任务"
    page.wait_for_function(
        "title => document.querySelector('#job-list').textContent.includes(title)",
        arg=jobs[0]["title"],
        timeout=12000,
    )
    assert not problems, problems
    print(json.dumps({
        "home_status": response.status,
        "models": available_models,
        "selected_anima": True,
        "four_candidates": True,
        "multiview_mode_validation": True,
        "real_job_visible": jobs[0]["title"],
        "page_errors": problems,
    }, ensure_ascii=False, indent=2))
    browser.close()
