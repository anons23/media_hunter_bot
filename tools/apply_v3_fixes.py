from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "media_hunter_bot" / "handlers.py"
s = P.read_text(encoding="utf-8")

def replace_once(old, new, label):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected 1 match, found {n}")
    s = s.replace(old, new)

# 1. Remove the broken duplicate line in dele().
replace_once(
'''@router.callback_query(F.data.startswith("del:"))
async def dele(c: CallbackQuery):
    await db.aremove_channel(c.from_user.id, int(c.data.split(":", 1)
    await db.aremove_channel(c.from_user.id, int(c.data.split(":", 1)[1]))
    await c.answer("Удалено")
    await channels(c)
''',
'''@router.callback_query(F.data.startswith("del:"))
async def dele(c: CallbackQuery):
    await db.aremove_channel(c.from_user.id, int(c.data.split(":", 1)[1]))
    await c.answer("Удалено")
    await channels(c)
''', "dele")

# 2. A normal video URL is not a playlist: empty playlist_items must fall through to download().
replace_once(
'''                items = await asyncio.to_thread(playlist_items, j.url, MAX_PLAYLIST_ITEMS)
                if len(items) > 1:
                    for u in items:
                        await self.add(j.uid, url=u)
                    await self.bot.send_message(
                        j.uid,
                        f"📚 Плейлист: {len(items)} видео добавлено в очередь.",
                    )
                    return
                if not items:
                    raise RuntimeError(
                        "Плейлист или ссылка не содержит доступного видео"
                    )
                source = await asyncio.to_thread(download, j.url, work, register)
''',
'''                items = await asyncio.to_thread(playlist_items, j.url, MAX_PLAYLIST_ITEMS)
                if len(items) > 1:
                    premium = await db.ais_premium(j.uid)
                    async with self._lock:
                        free = self._max_queue - self._queue_size
                        if len(items) > free:
                            raise RuntimeError(
                                f"Плейлист содержит {len(items)} видео, но свободно только {free} мест в очереди."
                            )
                        jobs = []
                        for u in items:
                            self.seq += 1
                            self._queue_size += 1
                            jobs.append(Job(0 if premium else 1, self.seq, j.uid, self.gen.get(j.uid, 0), u, None))
                        for job in jobs:
                            await self.q.put(job)
                    await self.bot.send_message(
                        j.uid,
                        f"📚 Плейлист: {len(items)} видео добавлено в очередь.",
                    )
                    return
                source_url = items[0] if len(items) == 1 else j.url
                source = await asyncio.to_thread(download, source_url, work, register)
''', "playlist")

# 3. Do not mutate _queue_size by draining PriorityQueue during restart.
start = s.index("    async def restart(self, uid: int):")
end = s.index("    async def _worker(self):", start)
s = s[:start] + '''    async def restart(self, uid: int):
        self.gen[uid] = self.gen.get(uid, 0) + 1
        tasks = list(self.tasks.get(uid, set()))
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.pop(uid, None)

        with self._proc_lock:
            procs = list(self.processes.get(uid, set()))
            self.processes.pop(uid, None)
        for p in procs:
            try:
                if p.returncode is None:
                    p.terminate()
                    try:
                        await asyncio.wait_for(asyncio.to_thread(p.wait), timeout=5)
                    except asyncio.TimeoutError:
                        p.kill()
            except Exception:
                pass

        for root in list(self.uploads.pop(uid, set())):
            await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)

'''+s[end:]

# 4. Cleaner must preserve logos referenced by users/channels in the DB.
replace_once(
'''                await asyncio.to_thread(
                    cleanup_logos, CLEANER_AGE_HOURS * 7, set()
                )
''',
'''                active_logos = await db.aactive_logo_paths()
                await asyncio.to_thread(
                    cleanup_logos, CLEANER_AGE_HOURS * 7, active_logos
                )
''', "cleaner")

# 5. Private invite links cannot be membership-checked. Do not block all users forever.
replace_once(
'''        if not ok:
            missing = True
            rows.append([B(r["title"] or f'ОПП {r["slot"]}', url=r["url"])])
''',
'''        if target is None:
            logger.warning("OPP slot %s uses a private invite link; membership cannot be verified", r["slot"])
            continue
        if not ok:
            missing = True
            rows.append([B(r["title"] or f'ОПП {r["slot"]}', url=r["url"])])
''', "opp-private")

# 6. Referral system: /start ref_<user_id> is applied once and atomically.
replace_once(
'''async def start(m: Message, bot: Bot):
    await db.aensure_user(
        m.from_user.id, m.from_user.username, m.from_user.first_name
    )
''',
'''async def start(m: Message, bot: Bot):
    await db.aensure_user(
        m.from_user.id, m.from_user.username, m.from_user.first_name
    )
    if m.text:
        parts = m.text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1][4:])
                await db.aapply_referral(m.from_user.id, referrer_id)
            except ValueError:
                pass
''', "referral-start")

# 7. Do not sell Premium to an account that is permanently premium.
replace_once(
'''    payload = f"premium:{days}:{c.from_user.id}:{secrets.token_hex(8)}"
    await c.answer()
''',
'''    user = await db.aget_user(c.from_user.id)
    if user and user["permanent_premium"]:
        await c.answer("У вас уже постоянный Premium.", show_alert=True)
        return
    payload = f"premium:{days}:{c.from_user.id}:{secrets.token_hex(8)}"
    await c.answer()
''', "permanent-premium")

# 8. Remove hardcoded Stars partner fallback.
replace_once(
'''    url = await db.aget_setting(
        "stars_link", "https://t.me/starslly_bot?start=489552258"
    )
''',
'''    url = await db.aget_setting("stars_link", "")
    if not url:
        await c.answer("Партнёрская ссылка Stars пока не настроена.", show_alert=True)
        return
''', "stars-default")

# 9. Confirm bot restart/reboot before performing destructive admin actions.
replace_once(
'''@router.callback_query(F.data == "abot")
async def abot(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer("Бот перезапускается")
    asyncio.create_task(_exit_later())


@router.callback_query(F.data == "areboot")
async def areboot(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer("VPS перезагружается", show_alert=True)
    asyncio.create_task(_reboot_later())
''',
'''@router.callback_query(F.data == "abot")
async def abot(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer()
    await c.message.edit_text("Перезапустить бота?", reply_markup=kb([
        [B("✅ Подтвердить", "abot:yes"), B("❌ Отмена", "admin")]
    ]))


@router.callback_query(F.data == "abot:yes")
async def abot_yes(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer("Бот перезапускается")
    asyncio.create_task(_exit_later())


@router.callback_query(F.data == "areboot")
async def areboot(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer()
    await c.message.edit_text("Перезагрузить VPS?", reply_markup=kb([
        [B("⚠️ Перезагрузить", "areboot:yes"), B("❌ Отмена", "admin")]
    ]))


@router.callback_query(F.data == "areboot:yes")
async def areboot_yes(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer("VPS перезагружается", show_alert=True)
    asyncio.create_task(_reboot_later())
''', "restart-confirm")

# 10. Cross-platform process exit.
replace_once(
'''async def _exit_later():
    await asyncio.sleep(1)
    os.kill(os.getpid(), signal.SIGTERM)
''',
'''async def _exit_later():
    await asyncio.sleep(1)
    if os.name == "nt":
        os._exit(0)
    os.kill(os.getpid(), signal.SIGTERM)
''', "exit-platform")

# 11. Local Bot API is optional; official API is the default.
replace_once(
'''    session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_BOT_API))
    bot = Bot(BOT_TOKEN, session=session)
''',
'''    if LOCAL_BOT_API:
        session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_BOT_API))
        bot = Bot(BOT_TOKEN, session=session)
    else:
        session = None
        bot = Bot(BOT_TOKEN)
''', "local-api")
replace_once(
'''        await bot.session.close()
        logger.info("Bot stopped cleanly.")
''',
'''        if session is not None:
            await session.close()
        else:
            await bot.session.close()
        logger.info("Bot stopped cleanly.")
''', "session-close")

# The resulting file must be syntactically valid before committing.
P.write_text(s, encoding="utf-8")
subprocess.run(["python", "-m", "py_compile", str(P)], check=True)
print("handlers.py repaired successfully")
