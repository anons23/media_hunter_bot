from pathlib import Path
import subprocess
p=Path('media_hunter_bot/handlers.py')
s=p.read_text(encoding='utf-8')
needle='''@router.callback_query(F.data == "check_opp")\n'''
insert='''@router.callback_query(F.data == "menu_ref")\nasync def menu_ref(c: CallbackQuery, bot: Bot):\n    me = await bot.get_me()\n    username = me.username\n    if not username:\n        await c.answer("Не удалось получить ссылку реферала.", show_alert=True)\n        return\n    count = await db.aget_referrals(c.from_user.id)\n    link = f"https://t.me/{username}?start=ref_{c.from_user.id}"\n    await c.answer()\n    await c.message.edit_text(\n        f"🎁 Ваша реферальная ссылка:\\n{link}\\n\\nПриглашено пользователей: {count}",\n        reply_markup=kb([[B("◀️ Назад", "back")]]),\n    )\n\n\n'''
if s.count(needle)!=1: raise SystemExit('anchor mismatch')
s=s.replace(needle,insert+needle)
p.write_text(s,encoding='utf-8')
subprocess.run(['python','-m','py_compile',str(p)],check=True)
