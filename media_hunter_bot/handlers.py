"""Aiogram handlers + processing engine for Media Hunter Bot.

Critical fixes applied:
1. StateFilter(None) on url_message/upload so they do NOT intercept FSM input.
2. Engine queue-size tracking is now atomic via asyncio.Lock.
3. Temporary directories are cleaned up via try/finally in every handler.
4. OPP private-invite links are handled gracefully.
5. All blocking subprocess calls wrapped in asyncio.to_thread().
6. restart() drains queued jobs and kills subprocesses.
7. shutdown() kills FFmpeg/yt-dlp before stopping workers.
8. ThrottlingMiddleware replies to Messages too.
9. Telegram file_size=None is handled safely; downloaded size is always authoritative.
10. Upload path checks queue limits before downloading the Telegram file.
"""
