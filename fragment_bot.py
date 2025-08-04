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
_playwright = None  # type: async_playwright.Playwright
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """
    Launch or return a persistent headless Chromium context emulating iPhone 13.
    Strips out unsupported keys from the Playwright device descriptor.
    """
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright in headless mobile (iPhone 13) mode…")
    _playwright = await async_playwright().start()

    # Get the raw iPhone 13 descriptor
    raw = _playwright.devices["iPhone 13"]
    # Map its camelCase fields into snake_case for launch_persistent_context
    device_args = {}
    for k, v in raw.items():
        if k == "userAgent":
            device_args["user_agent"] = v
        elif k == "viewport":
            device_args["viewport"] = v
        elif k == "deviceScaleFactor":
            device_args["device_scale_factor"] = v
        elif k == "isMobile":
            device_args["is_mobile"] = v
        elif k == "hasTouch":
            device_args["has_touch"] = v
        # skip fields like "defaultBrowserType", "name", etc.

    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        **device_args,
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
    page = await init_browser()

    try:
        # 1) Click “Connect TON”
        await page.click("button:has-text('Connect TON')")

        # 2) Wait for the TON-Connect dialog
        await page.wait_for_selector("text=Connect your TON wallet", timeout=10000)

        # 3) Open the QR modal by clicking the grid icon (second button)
        dialog = page.locator("div:has-text('Connect your TON wallet')")
        await dialog.locator("button").nth(1).click()

        # 4) Wait for “Scan with your mobile wallet”
        await page.wait_for_selector("text=Scan with your mobile wallet", timeout=10000)

        # 5) Extract the “Open Link” href if present
        open_link = await page.get_attribute("a:has-text('Open Link')", "href")
        link = open_link or "❌ No link found"

        # 6) Send the link with a logout button
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
        ])
        await msg.answer(
            f"🔗 Copy this link into Tonkeeper to connect:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb
        )

        # 7) Wait for handshake: the Connect TON button disappears
        try:
            await page.wait_for_selector("button:has-text('Connect TON')",
                                         state="detached",
                                         timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("Handshake timeout — maybe already connected.")
    except Exception as e:
        logging.error(f"/connect failed: {e}", exc_info=True)
        await msg.answer(f"⚠️ Error during connect:\n```\n{e}\n```")

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

    logging.info("🤖 Bot started: /connect, /logout; inline → type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
