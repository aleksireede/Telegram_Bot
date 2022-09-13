#!/usr/bin/env python3
import logging
import datetime
import pytz
from wakeonlan import send_magic_packet
from typing import Optional, Tuple
from telegram import __version__ as TG_VER
try:
    from telegram import __version_info__
except ImportError:
    __version_info__ = (0, 0, 0, 0, 0)  # type: ignore[assignment]
if __version_info__ < (20, 0, 0, "alpha", 1):
    raise RuntimeError(
        f"This example is not compatible with your current PTB version {TG_VER}. To view the "
        f"{TG_VER} version of this example, "
        f"visit https://docs.python-telegram-bot.org/en/v{TG_VER}/examples.html"
    )
from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, ChatMemberHandler, MessageHandler, CallbackContext
import telegram.ext.filters as Filters

my_chat_id = 0123456789
wol_mac_address = "AA:bb:CC:dd:EE:ff"
bot_token = "0123456789:AABB_CCddEEffGGhhiiJJkk001_122XX669"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
    of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
    the status didn't change.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member",
                                                                       (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member


async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks the chats the bot is in."""
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    # Let's check who is responsible for the change
    cause_name = update.effective_user.full_name

    # Handle chat types differently:
    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        if not was_member and is_member:
            logger.info("%s started the bot", cause_name)
            context.bot_data.setdefault("user_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s blocked the bot", cause_name)
            context.bot_data.setdefault("user_ids", set()).discard(chat.id)
    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logger.info("%s added the bot to the group %s",
                        cause_name, chat.title)
            context.bot_data.setdefault("group_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s removed the bot from the group %s",
                        cause_name, chat.title)
            context.bot_data.setdefault("group_ids", set()).discard(chat.id)
    else:
        if not was_member and is_member:
            logger.info("%s added the bot to the channel %s",
                        cause_name, chat.title)
            context.bot_data.setdefault("channel_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s removed the bot from the channel %s",
                        cause_name, chat.title)
            context.bot_data.setdefault("channel_ids", set()).discard(chat.id)


async def show_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows which chats the bot is in"""
    user_ids = ", ".join(str(uid)
                         for uid in context.bot_data.setdefault("user_ids", set()))
    group_ids = ", ".join(str(gid)
                          for gid in context.bot_data.setdefault("group_ids", set()))
    channel_ids = ", ".join(
        str(cid) for cid in context.bot_data.setdefault("channel_ids", set()))
    text = (
        f"@{context.bot.username} is currently in a conversation with the user IDs {user_ids}."
        f" Moreover it is a member of the groups with IDs {group_ids} "
        f"and administrator in the channels with IDs {channel_ids}."
    )
    await update.effective_message.reply_text(text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends explanation on how to use the bot."""
    await update.message.reply_text("""Lista komennoista joita voit kirjoittaa chattiin
/set <sekuntia> asettaaksesi ajastimen
/unset poistaa ajastimen käytöstä
/server kertoo Minecraft Palvelimen osoitteen
        """)
    username = update.message.from_user.username
    if update.message.chat_id == my_chat_id:
        await update.message.reply_text(f"""Owner Detected:{username}
/wakeonlan käynnistää palvelimen
/woldaily käynnistää päivittäisen ajastimen,
joka laittaa palvelimen päälle klo 9:00""")


async def callback_wol(context: CallbackContext) -> None:
    send_magic_packet(wol_mac_address)
    await context.bot.send_message(context.job.chat_id, text="Palvelin Käynnistyy.")


async def reminder(update: Update, context: CallbackContext) -> None:
    if update.message.chat_id != my_chat_id:
        return ()
    chat_id = update.message.chat_id
    job_name = str(chat_id)+"_WOL"
    job_removed = remove_job_if_exists(job_name, context)
    text = "Daily reminder has been set! You\'ll get notified at 9 AM daily!"
    if job_removed:
        text += " Vanha poistettu."
    await update.message.reply_text(text)
    context.job_queue.run_daily(callback_wol, time=datetime.time(
        hour=9, minute=00, tzinfo=pytz.timezone('Europe/Helsinki')), name=job_name, chat_id=chat_id)


async def greet_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets new users in chats and announces when someone leaves"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    cause_name = update.chat_member.from_user.mention_html()
    member_name = update.chat_member.new_chat_member.user.mention_html()

    if not was_member and is_member:
        await update.effective_chat.send_message(
            f"{member_name} Lisäsättiin henkilön {cause_name} toimesta.\nTervetuloa!",
            parse_mode=ParseMode.HTML,
        )
    elif was_member and not is_member:
        await update.effective_chat.send_message(
            f"{member_name} poistui. Thanks a lot, {cause_name} ...",
            parse_mode=ParseMode.HTML,
        )


async def alarm(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the alarm message."""
    job = context.job
    await context.bot.send_message(job.chat_id, text=f"{job.data} sekuntia on mennyt!\nAjastin suoritettu onnistuneesti!")


def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a job to the queue."""
    chat_id = update.effective_message.chat_id
    try:
        # args[0] should contain the time for the timer in seconds
        due = float(context.args[0])
        if due < 0:
            await update.effective_message.reply_text("Sorry we can not go back to future!")
            return
        job_removed = remove_job_if_exists(str(chat_id), context)
        context.job_queue.run_once(
            alarm, due, chat_id=chat_id, name=str(chat_id), data=due)
        text = "Ajastin asetettu!"
        if job_removed:
            text += " Vanha poistettu."
        await update.effective_message.reply_text(text)
    except (IndexError, ValueError):
        await update.effective_message.reply_text("käyttö: /set <sekunteja>")


async def unset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the job if the user changed their mind."""
    chat_id = update.message.chat_id
    job_removed = remove_job_if_exists(str(chat_id), context)
    text = "Ajastin pysäytetty!" if job_removed else "Sinulla ei ole aktiivisia ajastimia."
    await update.message.reply_text(text)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("'%s' Ei ole komento jota ymmärrän")


async def texthandler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    sentence = update.message.text.lower()
    if "jonne" in sentence.split():
        await update.message.reply_text(f"@{username} On Jonne!")


async def mcserver_ip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Minecraft Serverin IP osoite:\njonne.ddns.net")


async def wakeonlan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.chat_id == my_chat_id:
        return
    send_magic_packet(wol_mac_address)
    await update.message.reply_text("Käynnistetään Palvelin jonne.ddns.net\nPowered By:Truenas Scale")


def main() -> None:
    application = Application.builder().token(bot_token).build()
    job_queue = application.job_queue
    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("set", set_timer))
    application.add_handler(CommandHandler("wakeonlan", wakeonlan))
    application.add_handler(CommandHandler("woldaily", reminder))
    application.add_handler(CommandHandler("unset", unset))
    application.add_handler(CommandHandler("server", mcserver_ip))
    application.add_handler(ChatMemberHandler(
        track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(CommandHandler("show_chats", show_chats))
    application.add_handler(ChatMemberHandler(
        greet_chat_members, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(Filters.COMMAND, unknown))
    application.add_handler(MessageHandler(Filters.TEXT, texthandler))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
