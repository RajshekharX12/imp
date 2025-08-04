# File: fragment_bot.py

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
from playwright.async_api import async_playwright, BrowserContext, Page
from dotenv import load_dotenv

# ─── CONFIG & LOGGING ───────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logging.error("BOT_TOKEN is not set in .env")
    exit(1)

# ─── GLOBAL BROWSER STATE ────────────────────────────────────────────────────────
_playwright = None          # type: ignore
_context: BrowserContext = None  # type: ignore
_page: Page = None          # type: ignore

async def init_browser() -> Page:
    """
    Launch or return a persistent headless Chromium context emulating iPhone 13.
    """
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright in headless iPhone 13 mode…")
    _playwright = await async_playwright().start()

    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        # Hard-coded iPhone 13 parameters:
        viewport={"width": 390, "height": 844},
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
        ),
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        permissions=["clipboard-read"],
    )

    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com (mobile view)")
    return _page

async def shutdown_browser():
    """Close browser context & Playwright to clear session."""
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    """
    1) Click ‘Connect TON’ 
    2) Open QR modal 
    3) Copy the deep-link 
    4) Send link + logout button 
    5) Wait for handshake
    """
    page = await init_browser()
    try:
        # 1) Tap the header’s Connect TON button
        await page.click("button:has-text('Connect TON'):visible")

        # 2) Wait for wallet dialog
        await page.wait_for_selector("text=Connect your TON wallet", timeout=10000)

        # 3) In that dialog, click the QR-grid icon (second button)
        dialog = page.locator("div:has-text('Connect your TON wallet')").first
        await dialog.locator("button").nth(1).click()

        # 4) Grab the ‘Copy Link’ button’s data attribute
        copy_btn = await dialog.wait_for_selector("button:has-text('Copy Link')", timeout=10000)
        link = await copy_btn.get_attribute("data-clipboard-text") or ""
        if not link:
            return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

        # 5) Send it with a Log out inline button
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
        ])
        await msg.answer(
            f"🔗 Copy this link into your TON wallet app to connect:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb
        )

        # 6) Wait up to 60s for the Connect button to disappear (handshake)
        try:
            await page.wait_for_selector("button:has-text('Connect TON')",
                                         state="detached",
                                         timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("Handshake timeout; maybe you've already connected.")

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

# ─── Inline Query ────────────────────────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    """
    Inline '<suffix>' → fetch login code for +888<suffix>.
    """
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full = f"+888{suffix}"
    code = "❌ Error"

    page = await init_browser()
    try:
        await page.goto("https://fragment.com/my/numbers", wait_until="domcontentloaded")
        row = await page.wait_for_selector(
            f"xpath=//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']",
            timeout=7000
        )
        await row.click("button:has-text('Get Login Code')")
        el = await page.wait_for_selector("div.login-code", timeout=10000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        code = f"⚠️ {e}"

    result = InlineQueryResultArticle(
        id=suffix,
        title=f"{full} → {code}",
        input_message_content=InputTextMessageContent(f"Login code for {full}: {code}")
    )
    await inline_q.answer(results=[result], cache_time=5)

# ─── Bot Setup & Run ─────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started — commands: /connect, /logout; inline → type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
