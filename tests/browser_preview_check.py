import argparse
import json
import sys

from playwright.sync_api import sync_playwright


parser = argparse.ArgumentParser(description="在真实浏览器中检查游戏资产 3D 模型加载")
parser.add_argument("--url", default="http://127.0.0.1:18333/")
parser.add_argument("--job-id", default="f16ce50380cc4b49a79e5aa1b8747747")
parser.add_argument("--second-job-id", default="90ab7d5eb7ec4f5eab4cd6b87cb38a62")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")

issues = []
console_errors = []
http_errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        channel="msedge",
        headless=True,
        args=["--enable-webgl", "--enable-unsafe-swiftshader"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    navigations = []
    document_requests = []
    page.on("framenavigated", lambda frame: navigations.append(frame.url) if frame == page.main_frame else None)
    page.on("request", lambda request: document_requests.append(request.url) if request.is_navigation_request() and request.resource_type == "document" else None)
    page.on("pageerror", lambda error: issues.append(str(error)))
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("requestfailed", lambda request: issues.append(f"failed: {request.url} {request.failure}"))
    page.on("response", lambda response: http_errors.append({"status": response.status, "url": response.url}) if response.status >= 400 else None)

    response = page.goto(f"{args.url}?asset={args.job_id}", wait_until="domcontentloaded", timeout=30000)
    assert response.status == 200
    page.wait_for_function("document.querySelector('#viewer-canvas')?.dataset.loadState === 'ready'", timeout=80000)
    print(json.dumps({
        "navigation": response.status,
        "asset_page_visible": page.locator("#view-assets").is_visible(),
        "viewer_panel_visible": page.locator("#viewer-panel").is_visible(),
        "viewer_title": page.locator("#viewer-title").inner_text(),
        "canvas_count": page.locator("#viewer-canvas canvas").count(),
        "model_loading_status": page.locator("#viewer-canvas").get_attribute("data-load-state"),
        "model_meshes": page.locator("#viewer-canvas").get_attribute("data-mesh-count"),
        "loading_overlay_count": page.locator("#viewer-canvas .viewer-loading").count(),
        "canvas_dimensions": page.locator("#viewer-canvas").evaluate("el => ({width: el.clientWidth, height: el.clientHeight})"),
        "quality_message": page.locator("#viewer-quality").inner_text()[:360],
        "page_errors": issues,
        "console_errors": console_errors,
        "http_errors": http_errors[:12],
    }, ensure_ascii=False, indent=2))
    assert page.locator("#viewer-canvas").get_attribute("data-load-state") == "ready"
    assert page.locator("#viewer-canvas .viewer-loading").count() == 0
    assert page.locator("#viewer-canvas canvas").count() == 1
    assert int(page.locator("#viewer-canvas").get_attribute("data-mesh-count")) > 0
    assert not issues

    page.locator('[data-view-mode="wire"]').click()
    assert page.locator('[data-view-mode="wire"]').get_attribute("class").endswith("active")
    page.locator('[data-view-mode="material"]').click()
    assert page.locator('[data-view-mode="material"]').get_attribute("class").endswith("active")
    link = page.locator(f'a[href="/?asset={args.second_job_id}"]').first
    link.scroll_into_view_if_needed()
    overlap_check = link.evaluate("""el => {
      const bounds = el.getBoundingClientRect();
      const centerX = bounds.left + bounds.width / 2;
      const centerY = bounds.top + bounds.height / 2;
      const top = document.elementFromPoint(centerX, centerY);
      const image = el.closest('.asset-card')?.querySelector('.asset-thumb img');
      return {
        target: {x: centerX, y: centerY, width: bounds.width, height: bounds.height},
        clicked_element: top?.tagName,
        clicked_class: top?.className,
        image_bounds: image?.getBoundingClientRect().toJSON(),
      };
    }""")
    print(json.dumps({"asset_link_hit_test": overlap_check}, ensure_ascii=False, indent=2))
    link.click()
    page.wait_for_function("document.querySelector('#viewer-canvas')?.dataset.loadState === 'ready'", timeout=80000)
    assert page.locator("#viewer-title").inner_text()
    assert len(document_requests) == 1, "资产切换触发了页面重新加载"
    assert not issues
    print(json.dumps({
        "second_asset_id": args.second_job_id,
        "second_asset_model_state": page.locator("#viewer-canvas").get_attribute("data-load-state"),
        "second_asset_meshes": page.locator("#viewer-canvas").get_attribute("data-mesh-count"),
        "full_page_navigations": len(navigations),
        "document_requests": len(document_requests),
        "http_errors_count": len(http_errors),
    }, ensure_ascii=False, indent=2))
    browser.close()
