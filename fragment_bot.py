import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from dotenv import load_dotenv

# ─── CONFIG & LOGGING ───────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logging.error("BOT_TOKEN is not set in .env")
    exit(1)

# ─── GLOBAL PLAYWRIGHT STATE ─────────────────────────────────────────────────────
_playwright = None           # type: async_playwright.Playwright | None
_browser: Browser | None = None
_context: BrowserContext | None = None
_page: Page | None = None

# iPhone 13 UA + viewport (approx)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
)
VIEWPORT = {"width": 390, "height": 844}

async def init_browser() -> Page:
    """Launch the headless-chromium + mobile‐emulation context once."""
    global _playwright, _browser, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright + mobile emulation…")
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    _context = await _browser.new_context(
        user_agent=MOBILE_UA,
        viewport=VIEWPORT,
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        permissions=["clipboard-read"]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com (mobile view)")
    return _page

async def shutdown_browser():
    """Tear everything down so session/logins are cleared."""
    global _playwright, _browser, _context, _page
    if _context:
        await _context.close()
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _page = _context = _browser = _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    page = await init_browser()
    try:
        # 1) Click the **visible** "Connect TON" button
        btn = page.locator("button.ton-auth-link", has_text="Connect TON").first
        await btn.wait_for(state="visible", timeout=10000)
        await btn.click()

        # 2) Wait for the TON-Connect modal to appear
        modal = page.locator("[data-tc-modal='true']")
        await modal.wait_for(state="visible", timeout=10000)

        # 3) In that modal, click the **second** button (QR-grid tab)
        await modal.locator("button").nth(1).click()

        # 4) Wait for the "Copy Link" button, then read its attribute
        copy_btn = modal.locator("button:has-text('Copy Link')")
        await copy_btn.wait_for(state="visible", timeout=10000)
        link = await copy_btn.get_attribute("data-clipboard-text")
        if not link:
            raise RuntimeError("Couldn’t extract the TON-Connect link")

        # 5) Send it back with a Log out inline button
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
        ])
        await msg.answer(f"🔗 TON-Connect link:\n`{link}`",
                         parse_mode="Markdown",
                         reply_markup=kb)

        # 6) Wait up to 60s for the handshake → button disappears
        try:
            await page.wait_for_selector("button.ton-auth-link", state="detached", timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("⏱️ Handshake timeout (maybe already connected).")

    except Exception as e:
        logging.exception(e)
        await msg.answer(f"⚠️ Error during /connect:\n```\n{e}\n```")

# ─── /logout ─────────────────────────────────────────────────────────────────────
async def on_logout_cmd(msg: types.Message):
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    await call.answer()
    await do_logout(call.message)

async def do_logout(destination):
    await shutdown_browser()
    await destination.answer(
        "🔒 You’ve been logged out. Use `/connect` to reconnect.",
        parse_mode="Markdown"
    )

# ─── Inline Query (for login codes) ──────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full = f"+888{suffix}"
    code = "❌ Error"

    page = await init_browser()
    try:
        await page.goto("https://fragment.com/my/numbers", wait_until="domcontentloaded")
        row_btn = page.locator(
            f"xpath=//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']//button[text()='Get Login Code']"
        )
        await row_btn.wait_for(state="visible", timeout=7000)
        await row_btn.click()
        el = page.locator("div.login-code")
        await el.wait_for(state="visible", timeout=10000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        code = f"⚠️ {e}"

    result = InlineQueryResultArticle(
        id=suffix,
        title=f"{full} → {code}",
        input_message_content=InputTextMessageContent(f"Login code for {full}: {code}")
    )
    await inline_q.answer(results=[result], cache_time=5)

# ─── BOT SETUP & RUN ─────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started (commands: /connect, /logout; inline digit queries).")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
