#!/usr/bin/env python3
"""
Playwright tests for CURE UI tabs, file browser, and logs viewer.
Tests the new tab navigation, Reports file browser, and Logs console viewer.

Run with:
    cd /Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro
    python -m pytest tests/integration/test_cure_ui_tabs.py -v

Requirements:
    - Server running on localhost:5555
    - playwright installed (pip install playwright && playwright install)
"""

import pytest
from playwright.sync_api import sync_playwright, expect
import time

# Server URL
BASE_URL = "http://localhost:5555"


@pytest.fixture(scope="module")
def browser():
    """Launch browser for tests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def page(browser):
    """Create a new page for each test."""
    page = browser.new_page()
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    yield page
    page.close()


class TestTabNavigation:
    """Test the tab navigation system."""

    def test_tabs_exist(self, page):
        """Verify all three tabs are present."""
        tabs = page.locator(".tab-btn")
        expect(tabs).to_have_count(3)

        # Check tab labels
        tab_texts = [t.inner_text() for t in tabs.all()]
        assert "Generate Report" in tab_texts[0]
        assert "Reports" in tab_texts[1]
        assert "Logs" in tab_texts[2]

    def test_generate_report_tab_active_by_default(self, page):
        """Verify Generate Report tab is active on load."""
        generate_tab = page.locator('.tab-btn[data-tab="generate"]')
        expect(generate_tab).to_have_class(/active/)

        # Tab content should be visible
        content = page.locator("#tab-generate")
        expect(content).to_have_class(/active/)

    def test_switch_to_reports_tab(self, page):
        """Test switching to Reports tab."""
        reports_tab = page.locator('.tab-btn[data-tab="reports"]')
        reports_tab.click()

        # Wait for tab switch
        page.wait_for_timeout(500)

        # Reports tab should now be active
        expect(reports_tab).to_have_class(/active/)

        # Reports content should be visible
        content = page.locator("#tab-reports")
        expect(content).to_have_class(/active/)

        # Generate Report content should be hidden
        generate_content = page.locator("#tab-generate")
        expect(generate_content).not_to_have_class(/active/)

    def test_switch_to_logs_tab(self, page):
        """Test switching to Logs tab."""
        logs_tab = page.locator('.tab-btn[data-tab="logs"]')
        logs_tab.click()

        page.wait_for_timeout(500)

        expect(logs_tab).to_have_class(/active/)

        content = page.locator("#tab-logs")
        expect(content).to_have_class(/active/)

    def test_switch_back_to_generate(self, page):
        """Test switching tabs back and forth."""
        # Go to Reports
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(300)

        # Go back to Generate
        generate_tab = page.locator('.tab-btn[data-tab="generate"]')
        generate_tab.click()
        page.wait_for_timeout(300)

        expect(generate_tab).to_have_class(/active/)
        expect(page.locator("#tab-generate")).to_have_class(/active/)


class TestThemeToggle:
    """Test the theme toggle functionality."""

    def test_theme_toggle_exists(self, page):
        """Verify theme toggle button exists."""
        toggle = page.locator(".theme-toggle-btn")
        expect(toggle).to_be_visible()

    def test_default_theme_is_dark(self, page):
        """Verify default theme is dark mode."""
        body = page.locator("body")
        # Should NOT have light-theme class
        expect(body).not_to_have_class(/light-theme/)

        # Theme label should say "Dark"
        label = page.locator("#themeLabel")
        expect(label).to_have_text("Dark")

    def test_toggle_to_light_theme(self, page):
        """Test switching to light theme."""
        toggle = page.locator(".theme-toggle-btn")
        toggle.click()

        page.wait_for_timeout(300)

        body = page.locator("body")
        expect(body).to_have_class(/light-theme/)

        label = page.locator("#themeLabel")
        expect(label).to_have_text("Light")

    def test_toggle_back_to_dark(self, page):
        """Test switching back to dark theme."""
        toggle = page.locator(".theme-toggle-btn")

        # First click - go to light
        toggle.click()
        page.wait_for_timeout(200)

        # Second click - back to dark
        toggle.click()
        page.wait_for_timeout(200)

        body = page.locator("body")
        expect(body).not_to_have_class(/light-theme/)


class TestFileBrowser:
    """Test the Reports tab file browser."""

    def test_file_browser_loads(self, page):
        """Verify file browser loads when Reports tab is clicked."""
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(1000)

        # Folder tree should be visible
        folder_tree = page.locator(".folder-tree")
        expect(folder_tree).to_be_visible()

        # File list panel should be visible
        file_panel = page.locator(".file-list-panel")
        expect(file_panel).to_be_visible()

    def test_folder_tree_has_root(self, page):
        """Verify root folder (downloaded_doc) is in the tree."""
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(1000)

        root_folder = page.locator('.folder-item:has-text("downloaded_doc")')
        expect(root_folder).to_be_visible()

    def test_view_toggle_exists(self, page):
        """Verify grid/list view toggle exists."""
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(500)

        view_toggle = page.locator(".view-toggle")
        expect(view_toggle).to_be_visible()

        buttons = view_toggle.locator("button")
        expect(buttons).to_have_count(2)

    def test_switch_to_list_view(self, page):
        """Test switching to list view."""
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(1000)

        # Click list view button
        list_btn = page.locator('.view-toggle button:nth-child(2)')
        list_btn.click()
        page.wait_for_timeout(300)

        # List view should be active
        list_view = page.locator("#fileListView")
        expect(list_view).to_have_class(/active/)

    def test_breadcrumb_exists(self, page):
        """Verify breadcrumb navigation exists."""
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(500)

        breadcrumb = page.locator(".breadcrumb")
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text("downloaded_doc")

    def test_refresh_button(self, page):
        """Test refresh button in file browser."""
        page.locator('.tab-btn[data-tab="reports"]').click()
        page.wait_for_timeout(500)

        refresh_btn = page.locator('button:has-text("Refresh")')
        expect(refresh_btn).to_be_visible()

        # Click should not error
        refresh_btn.click()
        page.wait_for_timeout(500)


class TestLogsViewer:
    """Test the Logs tab console viewer."""

    def test_logs_container_loads(self, page):
        """Verify logs container loads when Logs tab is clicked."""
        page.locator('.tab-btn[data-tab="logs"]').click()
        page.wait_for_timeout(1000)

        logs_container = page.locator(".logs-container")
        expect(logs_container).to_be_visible()

    def test_logs_header_exists(self, page):
        """Verify logs header with controls exists."""
        page.locator('.tab-btn[data-tab="logs"]').click()
        page.wait_for_timeout(500)

        header = page.locator(".logs-header")
        expect(header).to_be_visible()
        expect(header).to_contain_text("Server Console Output")

    def test_auto_scroll_button(self, page):
        """Test auto-scroll toggle button."""
        page.locator('.tab-btn[data-tab="logs"]').click()
        page.wait_for_timeout(500)

        auto_scroll_btn = page.locator("#autoScrollBtn")
        expect(auto_scroll_btn).to_be_visible()
        expect(auto_scroll_btn).to_have_class(/active/)

        # Click to disable
        auto_scroll_btn.click()
        page.wait_for_timeout(200)
        expect(auto_scroll_btn).not_to_have_class(/active/)

    def test_search_input(self, page):
        """Test logs search input exists."""
        page.locator('.tab-btn[data-tab="logs"]').click()
        page.wait_for_timeout(500)

        search_input = page.locator("#logsSearch")
        expect(search_input).to_be_visible()

        # Type in search
        search_input.fill("test")
        page.wait_for_timeout(300)

    def test_clear_view_button(self, page):
        """Test clear view button."""
        page.locator('.tab-btn[data-tab="logs"]').click()
        page.wait_for_timeout(500)

        clear_btn = page.locator('button:has-text("Clear View")')
        expect(clear_btn).to_be_visible()

    def test_refresh_button(self, page):
        """Test logs refresh button."""
        page.locator('.tab-btn[data-tab="logs"]').click()
        page.wait_for_timeout(500)

        refresh_btn = page.locator('.logs-controls button:has-text("Refresh")')
        expect(refresh_btn).to_be_visible()


class TestGenerateReportTab:
    """Test the Generate Report tab (original functionality)."""

    def test_input_panel_exists(self, page):
        """Verify input panel exists in Generate Report tab."""
        input_panel = page.locator(".input-panel")
        expect(input_panel).to_be_visible()

    def test_owner_name_input(self, page):
        """Verify owner name input field."""
        owner_input = page.locator("#ownerName")
        expect(owner_input).to_be_visible()

    def test_county_dropdown(self, page):
        """Verify county dropdown has options."""
        county_select = page.locator("#county")
        expect(county_select).to_be_visible()

        # Should have multiple options (23 counties)
        options = county_select.locator("option")
        count = options.count()
        assert count >= 1, "County dropdown should have options"

    def test_generate_button(self, page):
        """Verify Generate Report button exists."""
        btn = page.locator("#generateBtn")
        expect(btn).to_be_visible()
        expect(btn).to_contain_text("Generate Report")

    def test_status_steps_exist(self, page):
        """Verify all 8 status steps exist."""
        for i in range(1, 9):
            step = page.locator(f"#step{i}")
            expect(step).to_be_visible()


class TestAPIEndpoints:
    """Test API endpoints directly."""

    def test_api_files_endpoint(self, page):
        """Test /api/files endpoint."""
        response = page.request.get(f"{BASE_URL}/api/files")
        assert response.ok

        data = response.json()
        assert data.get("success") is True
        assert "files" in data
        assert "folders" in data

    def test_api_logs_endpoint(self, page):
        """Test /api/logs endpoint."""
        response = page.request.get(f"{BASE_URL}/api/logs")
        assert response.ok

        data = response.json()
        assert data.get("success") is True
        assert "logs" in data

    def test_api_status_endpoint(self, page):
        """Test /status endpoint."""
        response = page.request.get(f"{BASE_URL}/status")
        assert response.ok

        data = response.json()
        assert data.get("status") == "online"

    def test_api_counties_endpoint(self, page):
        """Test /api/counties endpoint."""
        response = page.request.get(f"{BASE_URL}/api/counties")
        assert response.ok

        data = response.json()
        assert "counties" in data
        assert data.get("total", 0) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
