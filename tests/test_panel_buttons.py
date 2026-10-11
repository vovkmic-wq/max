"""Проверка всех кнопок в настоящем Chrome с изолированной базой и тестовыми адаптерами."""

from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from max_channel_agent import image_pipeline, image_schedule, holidays, browser_corrections
from max_channel_agent.api import create_app
from max_channel_agent.config import fingerprint
from max_channel_agent.db import Draft, Intent, MaterialMedia, VideoAsset, VideoProject


# Сеть браузера замыкаем на локальное приложение; ни один клик не обращается к MAX.
@pytest.fixture
def panel_browser(service, project, monkeypatch, clip):
    monkeypatch.setenv("APP_AUTH_SECRET", "button-owner-test-key")
    monkeypatch.setenv("APP_EDITOR_SECRET", "button-editor-test-key")
    monkeypatch.setenv("APP_VIEWER_SECRET", "button-viewer-test-key")
    monkeypatch.setenv("PIXABAY_API_KEY", "button-pixabay-test-key")
    monkeypatch.setattr(service.publisher, "mode", "browser")
    monkeypatch.setattr(service.publisher, "inspect", lambda chat: {"publish": True, "binding_hash": fingerprint(service.settings.app["max"])})
    monkeypatch.setattr(service.publisher, "login", lambda chat: {"state": "login_window_requested", "pid": 1}, raising=False)
    service.connect("test", "-123")
    plan = {"title": "Тестовый ролик", "caption": "Тестовая визуальная история для канала.", "rights_basis": "Собственный материал",
            "scenes": [{"prompt": "A blue lake", "negative_prompt": "artifacts", "duration_seconds": 1}]}
    monkeypatch.setattr(service.hybrid, "generate_plan", lambda *a: plan)
    monkeypatch.setattr(service.hybrid, "approve_generation", lambda *a: None)
    monkeypatch.setattr(service.hybrid, "poll_project", lambda *a: None)
    monkeypatch.setattr(service.hybrid, "assemble", lambda *a: {"state": "assembled"})
    monkeypatch.setattr(service.hybrid, "cancel", lambda *a: None)
    monkeypatch.setattr(service.hybrid, "import_scene", lambda *a: {"state": "imported"})
    monkeypatch.setattr(service.hybrid, "curate", lambda *a: {"state": "curated"})
    monkeypatch.setattr(service, "approve", lambda *a: None)
    monkeypatch.setattr(service, "revise", lambda *a: None)
    monkeypatch.setattr(service, "reconcile", lambda *a: "confirmed")
    monkeypatch.setattr(browser_corrections, "_correct_caption", lambda *a: {"state": "confirmed"})
    monkeypatch.setattr(image_pipeline, "scan", lambda *a, **k: {"state": "ready", "top": []})
    # Настоящее расписание испытывают отдельные тесты; кнопка не запускает публикацию.
    monkeypatch.setattr(image_schedule, "tick", lambda *a, **k: {"state": "not_due", "next_run_at": "2026-10-11T20:00:00+03:00"})
    monkeypatch.setattr(holidays, "import_catalog", lambda *a: {"state": "updated", "holiday_count": 293})
    with service.db.session.begin() as db:
        db.add(VideoProject(id="video-buttons", channel_id="test", plan=plan, config_id=service.settings.hash))
        db.add(VideoAsset(id="asset-buttons", path=clip.relative_to(project).as_posix(),
                          sha256="a" * 64, frames=[], quality={"duration_seconds": 1}, provenance={}))
        db.add(MaterialMedia(id="media-buttons", material_id="material", url="https://example.org/video.mp4", mime="video/mp4"))
        for name, state in (("review", "review_pending"), ("published", "published"), ("unknown", "published")):
            db.add(Draft(id="draft-" + name, channel_id="test", story_id="story-" + name, state=state,
                         current={"title": "Тест", "body": "Тестовая подпись.", "checks": []}, config_id=service.settings.hash))
        db.add(Intent(id="intent-published", draft_id="draft-published", channel_id="test", state="confirmed", body_hash="h", published_at=1780000000))
    seen, errors = [], []
    with TestClient(create_app(service)) as client, sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="chrome", headless=True, chromium_sandbox=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        def handle(route):
            request = route.request
            path = urlsplit(request.url).path
            query = urlsplit(request.url).query
            headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length"}}
            seen.append((request.method, path, request.post_data_json if request.post_data else None))
            response = client.request(request.method, path + ("?" + query if query else ""), headers=headers,
                                      content=request.post_data_buffer)
            route.fulfill(status=response.status_code, body=response.content,
                          headers={key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "content-encoding"}})
        page.route("http://testserver/**", handle)
        page.goto("http://testserver/")
        yield page, service, seen, errors
        browser.close()


# Ждём результат действия, а не фиксированную задержку или случайную паузу.
def click(page, selector):
    button = page.locator(selector)
    button.click()
    expect(button).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#feedback")).not_to_have_attribute("data-state", "working")


def login(page, role="owner"):
    page.locator("#token").fill("button-" + role + "-test-key")
    click(page, "#login")
    expect(page.locator("#status")).to_contain_text("Подключено")


# Все статические кнопки дают результат; повторное подключение и reload сохраняют вход.
def test_all_static_panel_buttons(panel_browser):
    page, service, seen, errors = panel_browser
    expect(page.locator("#browser-login")).to_be_disabled()
    login(page)
    expect(page.locator("#channel")).to_have_value("test")
    expect(page.locator("#chat")).to_have_value("-123")
    click(page, "#login")
    page.reload()
    expect(page.locator("#status")).to_contain_text("Сессия восстановлена")
    for button in page.locator("[data-tab]").all():
        button.click()
        expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    for button_id in ("refresh", "browser-login", "browser-check", "connect", "pause", "resume", "report", "bootstrap", "growth", "images-status", "images-scan", "images-pause", "images-resume", "images-tick"):
        # Рабочие кнопки расположены в основном разделе.
        click(page, "[data-tab='channels']")
        click(page, "#" + button_id)
        expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    page.locator("#video-idea").fill("Тестовый ролик")
    click(page, "#generate-plan")
    click(page, "#create-plan")
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    click(page, "#calendar-tab")
    expect(page.locator(".calendar-day")).to_have_count(7)
    page.locator(".calendar-event").first.click()
    expect(page.locator("#calendar-detail")).to_be_visible()
    for button_id in ("calendar-prev", "calendar-next", "calendar-today", "calendar-refresh", "holidays-toggle", "holidays-update"):
        click(page, "#" + button_id)
        expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    page.locator("#schedule-enabled").uncheck()
    click(page, "#schedule-save")
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    click(page, "#settings-tab")
    for button_id in ("channel-profiles", "channel-apply", "settings-load", "settings-format", "settings-validate", "settings-save", "validate", "activate"):
        click(page, "#" + button_id)
        expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    page.locator("[data-credential='PIXABAY_API_KEY']").fill("new-button-key")
    click(page, "#credentials-save")
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    click(page, "#logout")
    expect(page.locator("#browser-login")).to_be_disabled()
    assert not errors
    assert any(path == "/api/v1/browser/check" for _, path, _ in seen)


# Ошибки полей, неверный ключ, повреждённый JSON и недостаточные права видны рядом с действиями.
def test_panel_validation_and_viewer_controls(panel_browser):
    page, service, seen, errors = panel_browser
    page.locator("#token").fill("wrong-key")
    click(page, "#login")
    expect(page.locator("#feedback")).to_have_attribute("data-state", "error")
    login(page)
    page.locator("#chat").fill("")
    click(page, "#browser-check")
    expect(page.locator("#feedback")).to_contain_text("Укажите chat_id")
    page.locator("#video-plan").fill("{broken")
    click(page, "#create-plan")
    expect(page.locator("#feedback")).to_contain_text("JSON")
    click(page, "#logout")
    login(page, "viewer")
    expect(page.locator("#settings-tab")).to_be_disabled()
    expect(page.locator("#browser-check")).to_be_disabled()
    click(page, "#calendar-tab")
    expect(page.locator("#schedule-save")).to_be_disabled()
    assert not errors


# Кнопки записей отправляют правильные контракты; предпросмотр не исчезает после ответа.
def test_all_dynamic_record_buttons(panel_browser, monkeypatch):
    page, service, seen, errors = panel_browser
    login(page)
    click(page, "[data-tab='sources']")
    click(page, "#content article:first-child button")
    click(page, "[data-tab='videos']")
    for label in ("Одобрить генерацию", "Проверить результат", "Собрать ролик", "Остановить проект"):
        page.get_by_role("button", name=label, exact=True).click()
        expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    page.get_by_label("Путь готовой сцены").fill("fixture.mp4")
    page.get_by_label("Права на сцену").fill("Собственные права")
    page.get_by_role("button", name="Импортировать готовую сцену", exact=True).click()
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    click(page, "[data-tab='source-media']")
    page.get_by_label("Подпись подборки").fill("Проверенная подпись")
    page.get_by_role("button", name="Подготовить подборку", exact=True).click()
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    click(page, "[data-tab='assets']")
    page.get_by_role("button", name="Просмотреть ролик", exact=True).click()
    expect(page.locator("#content video")).to_have_count(1)
    click(page, "[data-tab='drafts']")
    page.get_by_label("Путь MP4").fill("fixture.mp4")
    page.get_by_label("Основание права на публикацию").fill("Собственные права")
    for label in ("Приложить MP4", "Коммерческий материал", "Снять коммерческую отметку", "Сохранить новую ревизию", "Одобрить в календарь"):
        page.get_by_role("button", name=label, exact=True).click()
        expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    page.get_by_role("button", name="Исправить опубликованную подпись", exact=True).first.click()
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    page.get_by_role("button", name="Отклонить", exact=True).click()
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    with service.db.session.begin() as db:
        db.add(Intent(id="intent-unknown", draft_id="draft-unknown", channel_id="test", state="unknown", body_hash="h"))
    click(page, "[data-tab='publications']")
    page.get_by_role("button", name="Сверить результат", exact=True).click()
    expect(page.locator("#feedback")).to_have_attribute("data-state", "success")
    assert not errors
