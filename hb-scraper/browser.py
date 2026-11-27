"""
Headless Chrome for the portals whose job list only exists in the browser
(Careers in Gothenburg, Brainport Eindhoven, VDAB). Playwright drives the
Chrome already installed on GitHub's runner (channel="chrome"), so nothing is
downloaded. A reader opens the portal's own page and keeps the answers the page
itself gets from its job search; it never calls those search services directly.
"""
import json

PAGE_TIMEOUT_MS = 30000
SETTLE_MS = 1500  # after the first matching answer, for any that follow it


class Browser:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            self._pw.stop()
            raise
        self.page = self._browser.new_page()
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def answers(self, action, url_part, accept=None):
        """Runs action(page) (a navigation or a click) and returns the JSON bodies
            of the responses whose URL contains url_part and that accept(response)
            allows, in arrival order. Raises if none arrives in PAGE_TIMEOUT_MS.
        """
        got = []

        def on_response(resp):
            if url_part in resp.url and (accept is None or accept(resp)):
                got.append(resp)

        self.page.on("response", on_response)
        try:
            with self.page.expect_response(lambda r: url_part in r.url and (accept is None or accept(r)),
                                           timeout=PAGE_TIMEOUT_MS):
                action(self.page)
            self.page.wait_for_timeout(SETTLE_MS)
        finally:
            self.page.remove_listener("response", on_response)
        bodies = []
        for resp in got:
            if resp.status != 200:
                raise RuntimeError(f"search answered HTTP {resp.status}")
            try:
                bodies.append(resp.json())
            except (ValueError, json.JSONDecodeError):
                continue
        return bodies


def run_in_browser(collector, read_with):
    """read_with(browser) inside a Browser; a browser that won't start or
        crashes is reported on the collector instead of raised.
    """
    try:
        with Browser() as browser:
            read_with(browser)
    except Exception as e:  # noqa: BLE001 -- report, never break the run
        first_line = str(e).splitlines()[0][:160] if str(e) else ""
        collector.fail(f"browser: {type(e).__name__}: {first_line}")
