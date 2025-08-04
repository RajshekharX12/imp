# file: fragment_bot.py

import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
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
_playwright = None       # type: async_playwright.Playwright
_browser: Browser = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    global _playwright, _browser, _context, _page

    if _page:
        return _page

    logging.info("🚀 Launching Playwright in headless iPhone 13 mode…")
    _playwright = await async_playwright().start()

    # grab the built-in device descriptor
    device = _playwright.devices.get("iPhone 13", {})

    # launch a fresh Chromium
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )

    # build new-context args from the device descriptor
    context_kwargs = {}
    for key in ("viewport", "deviceScaleFactor", "isMobile", "hasTouch", "userAgent"):
        if key in device:
            context_kwargs[key] = device[key]
    # allow clipboard reads
    context_kwargs["permissions"] = ["clipboard-read"]

    _context = await _browser.new_context(**context_kwargs)
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com (mobile)")

    return _page

async def shutdown_browser():
    global _playwright, _browser, _context, _page
    if _context:
        await _context.close()
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _page = _context = _browser = _playwright = None
    logging.info("🔒 Browser closed, session cleared")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    page = await init_browser()

    try:
        # 1) click the first *visible* TON-Connect button
        btn = page.locator("button.ton-auth-link:visible").first
        await btn.wait_for(state="visible", timeout=10000)
        await btn.click()

        # 2) wait for the "Connect your TON wallet" dialog
        dialog = page.locator("div:has-text('Connect your TON wallet')")
        await dialog.wait_for(timeout=10000)

        # 3) inside that dialog, click the second button (the QR-grid icon)
        await dialog.locator("button").nth(1).click()

        # 4) grab the link from the "Copy Link" button
        copy_btn = dialog.locator("button:has-text('Copy Link')")
        await copy_btn.wait_for(timeout=10000)

        link = await copy_btn.get_attribute("data-clipboard-text")
        if not link:
            # fallback: click it, wait for toast, then read from clipboard
            await copy_btn.click()
            await page.wait_for_selector("text=Link Copied", timeout=5000)
            link = await page.evaluate("() => navigator.clipboard.readText()")

        if not link:
            return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

        # 5) send it with a logout button
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
        ])
        await msg.answer(f"🔗 Copy this link into your mobile wallet:\n\n`{link}`",
                         parse_mode="Markdown",
                         reply_markup=kb)

        # 6) wait up to 60s for the handshake (button disappears)
        try:
            await btn.wait_for(state="detached", timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("⏱ Handshake timeout—maybe you're already connected.")

    except Exception as e:
        logging.exception("❌ Error during /connect")
        await msg.answer(f"⚠️ Error during /connect:\n```\n{e}\n```")

# ─── /logout ─────────────────────────────────────────────────────────────────────
async def on_logout_cmd(msg: types.Message):
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    await call.answer()
    await do_logout(call.message)

async def do_logout(dst):
    await shutdown_browser()
    await dst.answer("🔒 You’ve been logged out. Use `/connect` to reconnect.", parse_mode="Markdown")

# ─── Inline Query (unchanged) ────────────────────────────────────────────────────
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
