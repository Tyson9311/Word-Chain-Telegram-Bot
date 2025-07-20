import json
import asyncio
import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackContext, filters
from telegram.helpers import escape_markdown

# ✅ Bot Owner & Sudo Users
BOT_OWNER_ID = 7312499241  # Replace with your Telegram ID
SUDO_USERS = [8170921465, 8037102614, 7565878376]  # Add more user IDs as sudo users

with open('words.json', 'r') as f:
    valid_words = set(json.load(f))

score_lock = asyncio.Lock()
try:
    with open('score.json', 'r') as f:
        scores = json.load(f)
except FileNotFoundError:
    scores = {}

active_games = {}
game_lock = asyncio.Lock()


class GameState:
    INCREMENT_SEQUENCE = [
        (5, 3, 35),
        (5, 4, 30),
        (5, 5, 25),
        (5, 6, 20),
        (None, 7, 15)
    ]

    def __init__(self, chat_id, bot):
        self.chat_id = chat_id
        self.bot = bot
        self.players = []
        self.used_words = set()
        self.increment_stage = 0
        self.words_played_in_stage = 0
        self.current_player_index = 0
        self.current_word = None
        self.timer_task = None
        self.state = 'joining'
        self.join_task = None

    def get_round_params(self):
        stage = min(self.increment_stage, len(self.INCREMENT_SEQUENCE) - 1)
        return self.INCREMENT_SEQUENCE[stage][1], self.INCREMENT_SEQUENCE[stage][2]

    async def start_game(self):
        min_length, timeout = self.get_round_params()
        self.current_word = random.choice([w for w in valid_words if len(w) >= min_length])
        self.used_words.add(self.current_word)
        await self.bot.send_message(
            self.chat_id,
            f"🎮 Game started with word: *{escape_markdown(self.current_word.upper(), version=2)}*",
            parse_mode="MarkdownV2"
        )
        await self.next_turn()

    async def next_turn(self):
        if len(self.players) == 1:
            await self.end_game(self.players[0])
            return
        self.current_player_index %= len(self.players)
        player = self.players[self.current_player_index]
        min_length, timeout = self.get_round_params()
        await self.bot.send_message(
            self.chat_id,
            f"🌀 *{escape_markdown(format_name(player), version=2)}'s turn!*\n"
            f"🔗 Must start with: `{escape_markdown(self.current_word[-1], version=2)}`",
            parse_mode="MarkdownV2"
        )
        self.timer_task = asyncio.create_task(self.handle_timeout(timeout, player.id))

    async def process_word(self, user, word):
        word = word.lower().strip()
        min_length, _ = self.get_round_params()
        if (
            len(word) < min_length
            or word in self.used_words
            or word not in valid_words
            or not word.startswith(self.current_word[-1])
        ):
            return False
        self.used_words.add(word)
        self.current_word = word
        self.words_played_in_stage += 1
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.timer_task.cancel()
        await self.next_turn()
        return True

    async def handle_timeout(self, timeout, user_id):
        await asyncio.sleep(timeout)
        if self.players[self.current_player_index].id == user_id:
            await self.eliminate_player(self.players[self.current_player_index])

    async def eliminate_player(self, player):
        self.players.remove(player)
        await self.bot.send_message(
            self.chat_id,
            f"⏰ *{escape_markdown(format_name(player), version=2)}* eliminated due to timeout.",
            parse_mode="MarkdownV2"
        )
        if len(self.players) > 1:
            await self.next_turn()
        else:
            await self.end_game(self.players[0])
            async with game_lock:
                del active_games[self.chat_id]

    async def end_game(self, winner):
        self.state = 'ended'
        async with score_lock:
            scores[str(winner.id)] = scores.get(str(winner.id), 0) + 10
            with open('score.json', 'w') as f:
                json.dump(scores, f)
        await self.bot.send_message(
            self.chat_id,
            f"🏆 *{escape_markdown(format_name(winner), version=2)} wins!* +10 points",
            parse_mode="MarkdownV2"
        )
        async with game_lock:
            del active_games[self.chat_id]


def format_name(user):
    return user.full_name or user.username


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /startclassic to begin.")


async def startclassic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        if chat_id in active_games:
            await update.message.reply_text("A game is already running.")
            return
        game = GameState(chat_id, context.bot)
        game.players.append(update.effective_user)
        active_games[chat_id] = game
        await update.message.reply_text("Game starting in 5 seconds...")
    await asyncio.sleep(5)
    async with game_lock:
        if chat_id in active_games:
            game.state = 'playing'
            await game.start_game()


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    async with game_lock:
        game = active_games.get(chat_id)
        if game and game.state == 'joining' and user not in game.players:
            game.players.append(user)
            await update.message.reply_text(f"{format_name(user)} joined!")
        else:
            await update.message.reply_text("Cannot join now.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    word = update.message.text
    user = update.effective_user
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'playing':
            return
        if game.players[game.current_player_index].id != user.id:
            await update.message.reply_text("❌ Not your turn.")
            return
        if await game.process_word(user, word):
            await update.message.reply_text(f"✅ Word accepted.")
        else:
            await update.message.reply_text("❌ Invalid word.")


async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    async with score_lock:
        user_score = scores.get(user_id, 0)
    await update.message.reply_text(f"🏅 Your Score: {user_score}")


async def endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Check permissions
    allowed = False
    if user.id == BOT_OWNER_ID or user.id in SUDO_USERS:
        allowed = True
    else:
        try:
            member = await context.bot.get_chat_member(chat_id, user.id)
            if member.status == "creator":
                allowed = True
        except:
            pass

    if not allowed:
        await update.message.reply_text("🚫 Only the bot owner, sudo users, or group owner can end the game.")
        return

    async with game_lock:
        if chat_id in active_games:
            del active_games[chat_id]
            await update.message.reply_text("🛑 Game ended by authorized user.")
        else:
            await update.message.reply_text("⚠️ No active game.")


def main():
    application = Application.builder().token("7876214372:AAGXZrGFN3vV4iXaYk5k-BLhUpQkE-rr-H4").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("startclassic", startclassic))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("score", score))
    application.add_handler(CommandHandler("endgame", endgame))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()


if __name__ == "__main__":
    main()
