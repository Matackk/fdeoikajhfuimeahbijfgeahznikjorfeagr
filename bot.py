#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# python-telegram-bot >= 21 (async, Application.run_polling)
# PicklePersistence (bot_state.pickle)
# Env vars: BOT_TOKEN, ADMIN_CHAT_ID, AFFILIATE_URL, MINIAPP_URL, ADVANTAGES_URL
# Optional: START_IMAGE_URL, START_IMAGE_PATH, KEEPALIVE

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from typing import Any, Final, Mapping, Optional, MutableMapping, cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, User, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

# -------------------------- Config & Constants --------------------------

def _parse_int(s: str) -> int:
    try:
        return int(s)
    except Exception:
        return 0

BOT_TOKEN: Final[str] = os.environ.get('BOT_TOKEN', '').strip()
AFFILIATE_URL: Final[str] = os.environ.get('AFFILIATE_URL', '').strip()
MINIAPP_URL: Final[str] = os.environ.get('MINIAPP_URL', 'https://darkred-mantis-906245.hostingersite.com').strip()
ADVANTAGES_URL: Final[str] = os.environ.get('ADVANTAGES_URL', 'https://mediumaquamarine-crab-726883.hostingersite.com').strip()
ADMIN_CHAT_ID: Final[int] = _parse_int(os.environ.get('ADMIN_CHAT_ID', '').strip())

# Optional start image
START_IMAGE_URL: Final[str] = os.environ.get('START_IMAGE_URL', '').strip()
START_IMAGE_PATH: Final[str] = os.environ.get('START_IMAGE_PATH', 'start_banner.jpg').strip()

if not BOT_TOKEN:
    raise SystemExit('Missing BOT_TOKEN environment variable.')

# Conversation states
CHOOSING_OFFER, ASK_HAS_ACCOUNT, ASK_PSEUDO = range(3)

# Callback data keys
CB_BEGINNER = 'offer_beginner'
CB_PRO = 'offer_pro'
CB_HAS_ACCOUNT_YES = 'has_account_yes'
CB_HAS_ACCOUNT_NO = 'has_account_no'
CB_RESUME_FLOW = 'resume_flow'
CB_BACK_MENU = 'back_to_menu'
CB_EDIT_INFO = 'edit_info'
CB_OPEN_MENU = 'open_menu'
CB_START_FLOW = 'start_flow'
CB_REPLY_PREFIX = 'reply_to:'  # helpdesk: admin reply target
CB_END_REPLY = 'end_reply'  # end current reply thread

# Keys used in user_data
KEY_OFFER = 'offer'              # 'beginner' | 'pro'
KEY_PSEUDO = 'stake_username'
KEY_DATE = 'submitted_utc'       # ISO string
KEY_PENDING = 'pending'          # bool
KEY_EDIT_MODE = 'edit_mode'      # bool
KEY_LAST_WELCOME_TS = 'last_welcome_ts'  # float seconds

# -------------------------- Utils --------------------------

def is_admin_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == ADMIN_CHAT_ID)

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

def offer_human(offer: str) -> str:
    return 'Débutant : 30€ offerts' if offer == 'beginner' else 'Aguerri : Dépôt triplé'

def main_menu_kb() -> InlineKeyboardMarkup:
    # Three buttons: open flow, help mini-app, advantages mini-app
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🎁 Accéder aux bonus', callback_data=CB_START_FLOW)],
        [InlineKeyboardButton('❓ J’ai besoin d’aide', web_app=WebAppInfo(url=MINIAPP_URL))],
        [InlineKeyboardButton('⭐ Découvrir les avantages de Stake', web_app=WebAppInfo(url=ADVANTAGES_URL))],
    ])

def offers_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Débutant : 30€ offerts 🎁', callback_data=CB_BEGINNER)],
        [InlineKeyboardButton('Aguerri : Dépôt triplé 💎', callback_data=CB_PRO)],
        [InlineKeyboardButton('⬅️ Retour', callback_data=CB_BACK_MENU)],
    ])

def has_account_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ Oui', callback_data=CB_HAS_ACCOUNT_YES)],
        [InlineKeyboardButton('❌ Non', callback_data=CB_HAS_ACCOUNT_NO)],
        [InlineKeyboardButton('⬅️ Retour', callback_data=CB_BACK_MENU)],
    ])

def non_account_options_kb() -> InlineKeyboardMarkup:
    # Tutoriel VPN via MiniApp, plus reprendre la procédure, plus retour
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🧭 Tutoriel VPN', web_app=WebAppInfo(url=MINIAPP_URL))],
        [InlineKeyboardButton('🔁 Reprendre la procédure', callback_data=CB_RESUME_FLOW)],
        [InlineKeyboardButton('⬅️ Retour', callback_data=CB_BACK_MENU)],
    ])

def after_pseudo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📝 Modifier mes informations', callback_data=CB_EDIT_INFO)],
        [InlineKeyboardButton('⬅️ Retour', callback_data=CB_BACK_MENU)],
    ])

def info_text(user_data: Mapping[str, Any] | None) -> str:
    ud = user_data or {}
    offer = ud.get(KEY_OFFER)
    pseudo = ud.get(KEY_PSEUDO)
    date = ud.get(KEY_DATE)
    pending = ud.get(KEY_PENDING, False)

    if not offer and not pseudo:
        return (
            '<b>Informations enregistrées</b>\n'
            'Aucune information enregistrée pour le moment.\n'
            'Utilise <b>/start</b> pour commencer.'
        )

    lines = ['<b>Informations enregistrées</b>']
    if offer:
        lines.append(f'• Offre choisie : <b>{offer_human(str(offer))}</b>')
    if pseudo:
        lines.append(f'• Pseudo Stake : <b>{pseudo}</b>')
    if date:
        lines.append(f'• Date d’envoi : <b>{date}</b>')
    if pending:
        lines.append('• Statut : <i>Demande en cours de traitement</i>')

    return '\n'.join(lines)

def udict(context: ContextTypes.DEFAULT_TYPE) -> MutableMapping[str, Any]:
    return cast(MutableMapping[str, Any], context.user_data)

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, user: Optional[User], chat_id: int) -> None:
    if not ADMIN_CHAT_ID:
        return
    uid = user.id if user else 0
    uname = user.first_name if user else 'Utilisateur'
    ud = udict(context)
    text = (
        '<b>Nouvelle soumission</b>\n'
        f'• Utilisateur : <a href="tg://user?id={uid}">{uname}</a> (ID: <code>{uid}</code>)\n'
        f'• Chat ID : <code>{chat_id}</code>\n'
        f'• Offre : <b>{offer_human(str(ud.get(KEY_OFFER, "")))}</b>\n'
        f'• Pseudo Stake : <b>{ud.get(KEY_PSEUDO, "-")}</b>\n'
        f'• Date : <b>{ud.get(KEY_DATE, now_utc_iso())}</b>'
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        # Helpdesk: add 'Reply' control card
        kb = InlineKeyboardMarkup([[InlineKeyboardButton('🗨️ Répondre', callback_data=f'{CB_REPLY_PREFIX}{uid}')]])
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text='👉 Appuie sur “Répondre” pour écrire à cet utilisateur.',
            reply_markup=kb
        )
    except Exception as e:
        logging.exception('Failed to notify admin: %s', e)

# -------------------------- Images / UI helpers --------------------------

async def send_start_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the startup banner image (no buttons)."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        return
    try:
        if START_IMAGE_PATH and os.path.isfile(START_IMAGE_PATH):
            with open(START_IMAGE_PATH, 'rb') as f:
                await context.bot.send_photo(chat_id=chat_id, photo=f)
            return
        if START_IMAGE_URL:
            await context.bot.send_photo(chat_id=chat_id, photo=START_IMAGE_URL)
    except Exception as e:
        logging.warning('Failed to send start image: %s', e)

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the main menu: image + three buttons."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        return
    try:
        if START_IMAGE_PATH and os.path.isfile(START_IMAGE_PATH):
            with open(START_IMAGE_PATH, 'rb') as f:
                await context.bot.send_photo(chat_id=chat_id, photo=f, reply_markup=main_menu_kb())
            return
        if START_IMAGE_URL:
            await context.bot.send_photo(chat_id=chat_id, photo=START_IMAGE_URL, reply_markup=main_menu_kb())
            return
        # Fallback: no image available
        await context.bot.send_message(chat_id=chat_id, text=' ', reply_markup=main_menu_kb())
    except Exception as e:
        logging.warning('Failed to send main menu: %s', e)

# -------------------------- Texts --------------------------

WELCOME_BANNER = (
    '<b>Bienvenue sur le bot telegram de La Menace ! 🎰</b>\n\n'
    'Salut <b>{name}</b> !\n\n'
    'Prêt à tenter ta chance et à vivre l’expérience ultime du casino en ligne ? 💰🔥\n\n'
    'Avant de commencer, dis-moi quel type de joueur de casino tu es :\n\n'
    '<i>Tu auras néanmoins la possibilité d’avoir accès aux 2 bonus.</i>'
)

BEGINNER_TEXT = (
    'Tu as choisi l’offre <b>Débutant : 30€ offerts</b> 🎁\n\n'
    'Quel est ton pseudo Stake ? 😎'
)

PRO_ASK_ACCOUNT = (
    'Tu as sélectionné l’offre : <b>Aguerri : Dépôt triplé</b> 💎\n\n'
    'As-tu déjà créé ton compte Stake ? 🎉'
)

ALREADY_PENDING = 'Tu as déjà une demande en cours, attends que celle-ci soit traitée avant de faire une nouvelle demande ! 😎'

AFFILIATE_MESSAGE = (
    'Crée ton compte grâce au lien ci-dessous, puis clique sur le bouton pour reprendre la procédure ! 😎\n\n'
    '👉 <a href="{url}">Crée ton compte ! 👈</a>\n\n'
    '⚠️ Si le site ne fonctionne pas, il te suffit d’utiliser un VPN (Canada, Norvège). N’hésite pas à utiliser le tutoriel grâce au bouton ci-dessous. 👇'
)

CONFIRM_TEMPLATE = (
    'Tu as sélectionné l’offre : <b>{offer_h}</b>.\n'
    'Merci ! ✅\n\n'
    'Nous avons bien enregistré toutes tes réponses. Nous te recontacterons dans un court délai pour de plus amples vérifications ou pour valider l’option précédemment choisie.\n\n'
    '<b>Cordialement,</b>\n'
    'L’équipe La Menace'
)

CONFIRM_UPDATED = (
    'Tes informations ont bien été mises à jour. ✅\n\n'
    '<b>Offre :</b> {offer_h}\n'
    '<b>Nouveau pseudo Stake :</b> {pseudo}\n'
    '<b>Date :</b> {date}'
)

EDIT_REMINDER = '📝 <b>Modifier mes informations</b>\n\nQuel est ton <b>pseudo Stake</b> ?'

# -------------------------- Handlers --------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Show only the main menu (banner + 3 buttons)
    await send_main_menu(update, context)
    return ConversationHandler.END

async def open_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Back to main menu (keep previous messages; just send menu again)
    q = update.callback_query
    if q:
        await q.answer()
        await send_main_menu(update, context)
    return ConversationHandler.END

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await send_main_menu(update, context)
    return ConversationHandler.END

async def start_flow_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # When user clicks "Accéder aux bonus" → welcome text + offers (no image)
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()

    # Anti-spam: avoid sending multiple welcome messages if user taps rapidly
    try:
        import time as _t
        ud = udict(context)
        last = float(ud.get(KEY_LAST_WELCOME_TS, 0))
        now = _t.time()
        if now - last < 8:
            return CHOOSING_OFFER
        ud[KEY_LAST_WELCOME_TS] = now
    except Exception:
        pass

    name = update.effective_user.first_name if update.effective_user else 'là'
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=WELCOME_BANNER.format(name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=offers_kb(),
        disable_web_page_preview=True,
    )
    return CHOOSING_OFFER

async def choose_offer_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()
    data = q.data or ''

    # Reset flow state when (re)choosing an offer
    ud = udict(context)
    ud.pop(KEY_PSEUDO, None)
    ud.pop(KEY_DATE, None)
    ud.pop(KEY_EDIT_MODE, None)

    if data == CB_BEGINNER:
        ud[KEY_OFFER] = 'beginner'
        await q.edit_message_text(
            BEGINNER_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
        return ASK_PSEUDO

    if data == CB_PRO:
        ud[KEY_OFFER] = 'pro'
        await q.edit_message_text(
            PRO_ASK_ACCOUNT,
            parse_mode=ParseMode.HTML,
            reply_markup=has_account_kb(),
            disable_web_page_preview=True,
        )
        return ASK_HAS_ACCOUNT

    if data == CB_BACK_MENU:
        return await open_menu_cb(update, context)

    return CHOOSING_OFFER

async def has_account_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()

    if q.data == CB_HAS_ACCOUNT_YES:
        await q.edit_message_text(
            'Parfait ! Quel est ton <b>pseudo Stake</b> ? 😎',
            parse_mode=ParseMode.HTML,
        )
        return ASK_PSEUDO

    if q.data == CB_HAS_ACCOUNT_NO:
        text = AFFILIATE_MESSAGE.format(url=(AFFILIATE_URL or 'https://stake.com/'))
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=non_account_options_kb(),
            disable_web_page_preview=False,
        )
        return ASK_HAS_ACCOUNT

    if q.data == CB_RESUME_FLOW:
        await q.edit_message_text(
            PRO_ASK_ACCOUNT,
            parse_mode=ParseMode.HTML,
            reply_markup=has_account_kb(),
        )
        return ASK_HAS_ACCOUNT

    if q.data == CB_BACK_MENU:
        return await open_menu_cb(update, context)

    return ASK_HAS_ACCOUNT

async def capture_pseudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg is None:
        return ConversationHandler.END
    pseudo = (msg.text or '').strip()

    ud = udict(context)
    is_edit = bool(ud.get(KEY_EDIT_MODE))

    # If a previous request is pending and not editing, block but offer actions
    if ud.get(KEY_PENDING) and not is_edit:
        await msg.reply_text(ALREADY_PENDING, reply_markup=after_pseudo_kb())
        return ConversationHandler.END

    # Save / update
    ud[KEY_PSEUDO] = pseudo
    ud[KEY_DATE] = now_utc_iso()
    ud[KEY_PENDING] = True
    ud.pop(KEY_EDIT_MODE, None)  # clear edit mode if present

    # Notify admin of (new or updated) submission
    await notify_admin(context, update.effective_user, update.effective_chat.id if update.effective_chat else 0)

    # Confirmation to user
    if is_edit:
        confirm = CONFIRM_UPDATED.format(
            offer_h=offer_human(str(ud.get(KEY_OFFER, ''))),
            pseudo=pseudo,
            date=ud.get(KEY_DATE, now_utc_iso()),
        )
    else:
        confirm = CONFIRM_TEMPLATE.format(offer_h=offer_human(str(ud.get(KEY_OFFER, ''))))

    await msg.reply_text(confirm, parse_mode=ParseMode.HTML, reply_markup=after_pseudo_kb())
    return ConversationHandler.END

async def edit_info_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()
    ud = udict(context)
    ud[KEY_EDIT_MODE] = True
    await q.edit_message_text(EDIT_REMINDER, parse_mode=ParseMode.HTML)
    return ASK_PSEUDO

# -------------------------- Helpdesk (Admin ⇄ User) --------------------------

async def handle_user_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mirror any non-command message from users to ADMIN_CHAT_ID with a reply button.
    Admin chat is ignored here to avoid loops.
    """
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    # Ignore admin chat here; admin messages handled by a dedicated handler
    if chat.id == ADMIN_CHAT_ID:
        return
    # Ignore commands - conversation handlers already process those
    if msg.text and msg.text.startswith('/'):
        return
    # Copy the original message to admin (keeps media & caption)
    try:
        await context.bot.copy_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=chat.id,
            message_id=msg.message_id,
            protect_content=True,
        )
        # Send a control card with reply button
        kb = InlineKeyboardMarkup([[InlineKeyboardButton('🗨️ Répondre', callback_data=f'{CB_REPLY_PREFIX}{user.id}')]])
        info = (
            '<b>Nouveau message utilisateur</b>\n'
            f'• De : <a href="tg://user?id={user.id}">{user.first_name or "Utilisateur"}</a> '
            f'(ID: <code>{user.id}</code>)\n'
            f'• Chat ID : <code>{chat.id}</code>'
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=info,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        # Auto-thread: set current reply target to this user so admin can just type to continue
        context.chat_data['reply_to'] = user.id
    except Exception as e:
        logging.warning('Failed to mirror to admin: %s', e)

async def reply_to_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicked 'Répondre' under a mirrored user message."""
    if not is_admin_chat(update):
        q = update.callback_query
        if q:
            await q.answer('Action réservée à l’admin.', show_alert=True)
        return ConversationHandler.END
    q = update.callback_query
    if not q or not q.data or not q.data.startswith(CB_REPLY_PREFIX):
        return ConversationHandler.END
    await q.answer()
    try:
        target_id = int(q.data.split(':', 1)[1])
    except Exception:
        await q.edit_message_text('ID utilisateur invalide.')
        return ConversationHandler.END
    # Store target in admin chat_data
    context.chat_data['reply_to'] = target_id
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f'🧵 Réponse active à <code>{target_id}</code>. Envoyez vos messages. Tapez /done pour terminer.',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⛔ Terminer', callback_data=CB_END_REPLY)]])
        )
    except Exception:
        pass
    await q.edit_message_text(
        f'🗨️ Répondre à <code>{target_id}</code> — envoie maintenant ton message (texte, photo, doc…).',
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def admin_outbound_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When admin sends any message while a reply target is set, copy it to the user.
    Also implements /pm <user_id> <message> as a direct text-send fallback."""
    if not is_admin_chat(update):
        return
    msg = update.effective_message
    if not msg:
        return

    # /pm <user_id> <message>
    if msg.text and msg.text.startswith('/pm'):
        parts = msg.text.split(maxsplit=2)
        if len(parts) < 3:
            await msg.reply_text('Usage: /pm <user_id> <message>')
            return
        try:
            uid = int(parts[1])
        except Exception:
            await msg.reply_text('User ID invalide.')
            return
        text = parts[2]
        try:
            await context.bot.send_message(chat_id=uid, text=text, protect_content=True)
            await msg.reply_text(f'✅ Message envoyé à {uid}.')
        except Exception as e:
            await msg.reply_text(f'❌ Échec de l’envoi: {e}')
        return

    # End the current thread with /done or /fin
    if msg.text and msg.text.strip() in ('/done', '/fin'):
        if context.chat_data.pop('reply_to', None):
            await msg.reply_text('⛔ Fil terminé. Cliquez de nouveau sur 🗨️ Répondre pour choisir une cible, ou utilisez /pm.')
        else:
            await msg.reply_text('Aucun fil actif. Cliquez sur 🗨️ Répondre sous un message utilisateur, ou utilisez /pm.')
        return

    target_id = context.chat_data.get('reply_to')
    if not target_id:
        return  # Not in reply mode; ignore

    try:
        await context.bot.copy_message(
            chat_id=target_id,
            from_chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            protect_content=True,
        )
        await msg.reply_text(f'✅ Message transmis à <code>{target_id}</code>.', parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.reply_text(f'❌ Échec de la transmission: {e}')

async def end_reply_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Admin-only
    if not is_admin_chat(update):
        q = update.callback_query
        if q:
            await q.answer('Action réservée à l’admin.', show_alert=True)
        return ConversationHandler.END
    q = update.callback_query
    if q:
        await q.answer()
        context.chat_data.pop('reply_to', None)
        try:
            await q.edit_message_text('⛔ Fil terminé.')
        except Exception:
            pass
    return ConversationHandler.END

# -------------------------- Other Commands --------------------------

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            info_text(udict(context)),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await open_menu_cb(update, context)
    return ConversationHandler.END

# -------------------------- Keepalive (optional) --------------------------
# Some hosts (ex: Replit) sleep on inactivity. Enable a tiny HTTP server with KEEPALIVE=1.

def _keepalive_server(port: int = int(os.environ.get('PORT', '8000'))) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'OK')  # simple health check
        def log_message(self, *args, **kwargs):  # silence
            return
    try:
        httpd = HTTPServer(('', port), Handler)
        httpd.serve_forever()
    except Exception as e:
        logging.warning('Keepalive server error: %s', e)

def start_keepalive_if_needed() -> None:
    if os.environ.get('KEEPALIVE', '0') == '1':
        t = threading.Thread(target=_keepalive_server, daemon=True)
        t.start()

# -------------------------- Application --------------------------

def build_application() -> Application:
    persistence = PicklePersistence(filepath='bot_state.pickle')
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(start_flow_from_menu, pattern=f'^{CB_START_FLOW}$'),
            CallbackQueryHandler(edit_info_cb, pattern=f'^{CB_EDIT_INFO}$'),
        ],
        states={
            CHOOSING_OFFER: [
                CallbackQueryHandler(choose_offer_cb, pattern=f'^{CB_BEGINNER}$|^{CB_PRO}$|^{CB_BACK_MENU}$'),
                CallbackQueryHandler(edit_info_cb, pattern=f'^{CB_EDIT_INFO}$'),
            ],
            ASK_HAS_ACCOUNT: [
                CallbackQueryHandler(
                    has_account_cb,
                    pattern=f'^{CB_HAS_ACCOUNT_YES}$|^{CB_HAS_ACCOUNT_NO}$|^{CB_RESUME_FLOW}$|^{CB_BACK_MENU}$',
                ),
                CallbackQueryHandler(edit_info_cb, pattern=f'^{CB_EDIT_INFO}$'),
            ],
            ASK_PSEUDO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, capture_pseudo),
                CallbackQueryHandler(open_menu_cb, pattern=f'^{CB_BACK_MENU}$'),
                CallbackQueryHandler(edit_info_cb, pattern=f'^{CB_EDIT_INFO}$'),
            ],
        },
        fallbacks=[
            CommandHandler('start', start),
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(edit_info_cb, pattern=f'^{CB_EDIT_INFO}$'),
            CallbackQueryHandler(open_menu_cb, pattern=f'^{CB_OPEN_MENU}$'),
            CallbackQueryHandler(open_menu_cb, pattern=f'^{CB_BACK_MENU}$'),
        ],
        name='main_conversation',
        persistent=True,
        allow_reentry=True,
    )

    conv.block = False
    app.add_handler(conv)

    # Helpdesk handlers
    app.add_handler(CallbackQueryHandler(reply_to_user_cb, pattern=f'^{CB_REPLY_PREFIX}\\d+$'))
    app.add_handler(CallbackQueryHandler(end_reply_cb, pattern=f'^{CB_END_REPLY}$'))
    app.add_handler(MessageHandler((filters.ALL & ~filters.COMMAND) & filters.Chat(ADMIN_CHAT_ID), admin_outbound_handler), group=0)  # admin outbound (only admin chat)
    # Mirror any non-command user message to admin
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_user_inbox), group=1)

    # Global handlers so buttons work even outside conversation
    app.add_handler(CommandHandler('menu', menu))
    app.add_handler(CommandHandler('info', info))
    app.add_handler(CommandHandler('cancel', cancel))
    app.add_handler(CallbackQueryHandler(start_flow_from_menu, pattern=f'^{CB_START_FLOW}$'))
    app.add_handler(CallbackQueryHandler(open_menu_cb, pattern=f'^{CB_BACK_MENU}$'))
    app.add_handler(CallbackQueryHandler(open_menu_cb, pattern=f'^{CB_OPEN_MENU}$'))

    return app

def main() -> None:
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
    )
    start_keepalive_if_needed()
    app = build_application()
    logging.info('Bot starting…')
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
