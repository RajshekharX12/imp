# file: fragment_bot.py

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
    logging.error("❌ BOT_TOKEN is not set in .env")
    exit(1)

# ─── GLOBAL BROWSER STATE ────────────────────────────────────────────────────────
_playwright = None      # async_playwright() instance
_browser: Browser = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """
    Launch a headless Chromium + iPhone13 emulation & return the Page.
    Reuses the same page until shutdown_browser() is called.
    """
    global _playwright, _browser, _context, _page
    if _page:
        return _page

    logging.info("🚀 Starting Playwright…")
    _playwright = await async_playwright().start()

    # Launch browser headless
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )

    # Grab the Python-style device descriptor
    device = _playwright.devices["iPhone 13"]

    # Create a mobile-emulated context
    _context = await _browser.new_context(
        **device,
        permissions=["clipboard-read"],  # allow clipboard access
    )

    # Open a new page, navigate to fragment.com
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com (iPhone 13 view)")
    return _page

async def shutdown_browser():
    """Tear down everything and clear session."""
    global _playwright, _browser, _context, _page
    if _context:
        await _context.close()
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _browser = None
    _playwright = None
    logging.info("🔒 Browser & context closed, session cleared.")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    page = await init_browser()

    try:
        # 1) Tap the header “Connect TON” button
        await page.locator("button.ton-auth-link:visible").click()

        # 2) Wait for the TON-Connect sheet to show
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10_000)
        sheet = page.locator("#tc-widget-root")

        # 3) Tap the QR-grid icon (first button in the sheet)
        await sheet.locator("button").first.click()

        # 4) Wait for & extract the deep link from “Copy Link”
        copy_btn = sheet.locator("button:has-text('Copy Link')")
        await copy_btn.wait_for(timeout=10_000)
        link = await copy_btn.get_attribute("data-clipboard-text")
        if not link:
            return await msg.answer("⚠️ Couldn't read the TON-Connect link – please try again.")

        # 5) Send it with a Log out button
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
            ]
        )
        await msg.answer(
            f"🔗 Paste this link into your wallet to connect:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb
        )

        # 6) Wait up to 60 s for the handshake (button disappears)
        try:
            await page.wait_for_selector("button.ton-auth-link", state="detached", timeout=60_000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("⏱ Handshake timeout – perhaps already connected.")
    except Exception as e:
        logging.exception("❌ /connect failed")
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

# ─── Inline Query (login codes) ───────────────────────────────────────────────────
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
        row = await page.wait_for_selector(
            f"xpath=//div[contains(text(),'{suffix}')]/ancestor::div[@role='row']",
            timeout=7_000
        )
        await row.click("button:has-text('Get Login Code')")
        el = await page.wait_for_selector("div.login-code", timeout=10_000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        logging.exception("⚠️ Inline query failed")
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

    logging.info("🤖 Bot started: /connect, /logout; inline → digits for codes.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
