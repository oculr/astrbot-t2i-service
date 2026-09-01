import asyncio

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.render import ScreenshotOptions, Text2ImgRender


class FakePage:
    def __init__(self, time_out: bool = False):
        self.calls = []
        self.time_out = time_out

    async def wait_for_selector(self, selector, timeout=None):
        self.calls.append(("selector", selector, timeout))

    async def wait_for_timeout(self, timeout):
        self.calls.append(("delay", timeout))

    async def evaluate(self, expression):
        self.calls.append(("evaluate", "scrollBy" in expression))

    async def wait_for_load_state(self, state, timeout=None):
        self.calls.append(("load_state", state, timeout))
        if self.time_out:
            raise PlaywrightTimeoutError("network remains active")

    async def wait_for_function(self, expression, timeout=None):
        self.calls.append(("function", "document.images" in expression, timeout))
        if self.time_out:
            raise PlaywrightTimeoutError("image remains active")


def test_dynamic_content_waits_for_lazy_images():
    renderer = Text2ImgRender()
    page = FakePage()
    options = ScreenshotOptions(
        timeout=20_000,
        wait_for_selector=".page-ready",
        wait_after_load=1_500,
        auto_scroll=True,
        wait_for_network_idle=True,
        wait_for_images=True,
    )

    asyncio.run(renderer._wait_for_dynamic_content(page, options))

    assert page.calls == [
        ("selector", ".page-ready", 20_000),
        ("delay", 1_500),
        ("evaluate", True),
        ("load_state", "networkidle", 10_000),
        ("function", True, 10_000),
    ]


def test_dynamic_content_timeouts_are_best_effort():
    renderer = Text2ImgRender()
    page = FakePage(time_out=True)

    asyncio.run(
        renderer._wait_for_dynamic_content(
            page,
            ScreenshotOptions(wait_for_network_idle=True, wait_for_images=True),
        )
    )

    assert page.calls == [
        ("load_state", "networkidle", 10_000),
        ("function", True, 10_000),
    ]


def test_dynamic_content_waits_can_be_disabled():
    renderer = Text2ImgRender()
    page = FakePage()

    asyncio.run(
        renderer._wait_for_dynamic_content(
            page,
            ScreenshotOptions(
                auto_scroll=False,
                wait_for_network_idle=False,
                wait_for_images=False,
            ),
        )
    )

    assert page.calls == []
