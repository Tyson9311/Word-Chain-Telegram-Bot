import json
import asyncio
import random
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.helpers import escape_markdown

BOT_OWNER_ID = 7312499241
SUDO_USERS = [8170921465, 8037102614, 7565878376]

with open("words.json", "r") as f:
    valid_words = set(json.load(f))

try:
    with open("score.json", "r") as f:
        scores = json.load(f)
except FileNotFoundError:
    scores = {}

active_games = {}
game_lock = asyncio.Lock()
score_lock = asyncio.Lock()


def format_name(user):
    return escape_markdown(user.first_name or user.username or "Player", version=2)


class GameState:
    INCREMENT_SEQUENCE = [
        (5, 3, 60),
        (5, 4, 40),
        (5, 5, 30),
        (5, 6, 25),
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

    def get_round_params(self):
        stage = self.increment_stage
        if stage >= len(self.INCREMENT_SEQUENCE):
            stage = len(self.INCREMENT_SEQUENCE) - 1
        return self.INCREMENT_SEQUENCE[stage][1], self.INCREMENT_SEQUENCE[stage][2]

    async def start_game(self):
        self.state = 'playing'
        min_len, _ = self.get_round_params()
        valid_start = [w for w in valid_words if len(w) >= min_len]
        self.current_word = random.choice(valid_start).lower()
        self.used_words.add(self.current_word)

        await self.bot.send_message(
            self.chat_id,
            f"🎮 *Game Started!* First word is: `{escape_markdown(self.current_word.upper(), 2)}`",
            parse_mode="MarkdownV2"
        )
        await self.next_turn()

    async def next_turn(self):
        if len(self.players) == 1:
            await self.end_game(self.players[0])
            return

        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

        user = self.players[self.current_player_index]
        min_len, timeout = self.get_round_params()
        required_letter = self.current_word[-1]

        await self.bot.send_message(
            self.chat_id,
            f"🔔 *{format_name(user)}*, it's your turn!\n"
            f"🔤 Start with: `{required_letter}` | 📏 Min: `{min_len}` letters | ⏱️ Time: `{timeout}`s",
            parse_mode="MarkdownV2"
        )
        self.timer_task = asyncio.create_task(self.handle_timeout(timeout, user.id))

    async def handle_timeout(self, timeout, user_id):
        await asyncio.sleep(timeout)
        if self.players[self.current_player_index].id == user_id:
            await self.eliminate_player(self.players[self.current_player_index])

    async def eliminate_player(self, player):
        self.players.remove(player)
        await self.bot.send_message(
            self.chat_id,
            f"⛔ *{format_name(player)}* eliminated due to timeout!",
            parse_mode="MarkdownV2"
        )
        if len(self.players) == 1:
            await self.end_game(self.players[0])
        else:
            self.current_player_index %= len(self.players)
            await self.next_turn()

    async def process_word(self, user, word):
        word = word.strip().lower()
        min_len, _ = self.get_round_params()

        if (
            len(word) < min_len
            or word not in valid_words
            or word in self.used_words
            or not word.startswith(self.current_word[-1])
        ):
            return False

        self.used_words.add(word)
        self.current_word = word
        self.words_played_in_stage += 1
        self.current_player_index = (self.current_player_index + 1) % len(self.players)

        limit, _, _ = self.INCREMENT_SEQUENCE[self.increment_stage]
        if limit and self.words_played_in_stage >= limit:
            self.increment_stage += 1
            self.words_played_in_stage = 0
            await self.bot.send_message(
                self.chat_id,
                f"📈 *Level Up!* Stage {self.increment_stage + 1} begins now!",
                parse_mode="MarkdownV2"
            )

        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

        await self.next_turn()
        return True

    async def end_game(self, winner):
        async with score_lock:
            scores[str(winner.id)] = scores.get(str(winner.id), 0) + 10
            with open('score.json', 'w') as f:
                json.dump(scores, f)

        await self.bot.send_message(
            self.chat_id,
            f"🎉 *{format_name(winner)}* wins the game!\n🏆 +10 trophies!",
            parse_mode="MarkdownV2"
        )

        async with game_lock:
            if self.chat_id in active_games:
                del active_games[self.chat_id]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *Word Chain Battle!* 🔠\n\n"
        "🧠 Type `/startclassic` in group to begin.\n"
        "📜 Use `/help` to view all commands.",
        parse_mode="MarkdownV2"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 *Word Chain Help:*\n\n"
        "🎮 `/startclassic` - Start a new game\n"
        "🔗 `/join` - Join the game\n"
        "🏆 `/leaderboard` - View top 25 players\n"
        "📊 `/score` - View your trophies\n"
        "🛑 `/endgame` - Stop current game (owner only)",
        parse_mode="MarkdownV2"
    )


async def startclassic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        if chat_id in active_games:
            await update.message.reply_text("⚠️ A game is already running.")
            return

        game = GameState(chat_id, context.bot)
        active_games[chat_id] = game
        game.state = 'joining'

        await update.message.reply_text(
            "🎮 *New Word Chain game started!*\n"
            "⏳ Players have *60 seconds* to `/join`.",
            parse_mode="MarkdownV2"
        )

        await asyncio.sleep(60)
        if len(game.players) < 2:
            del active_games[chat_id]
            await context.bot.send_message(chat_id, "❌ Not enough players. Game cancelled.")
        else:
            game.state = 'playing'
            await game.start_game()


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'joining':
            await update.message.reply_text("🚫 You can't join now.")
            return
        if user in game.players:
            await update.message.reply_text("✅ Already joined.")
            return
        game.players.append(user)
        await update.message.reply_text(
            f"🎉 {format_name(user)} joined the game! Total: {len(game.players)}",
            parse_mode="MarkdownV2"
        )


async def endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    chat_admin = await context.bot.get_chat_member(chat_id, user_id)
    if user_id != BOT_OWNER_ID and user_id not in SUDO_USERS and chat_admin.status != "creator":
        await update.message.reply_text("❌ Only owner or sudo users can stop the game.")
        return

    async with game_lock:
        if chat_id not in active_games:
            await update.message.reply_text("❌ No game to stop.")
            return
        del active_games[chat_id]

    await update.message.reply_text("🛑 Game has been ended by admin.")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with score_lock:
        top_players = sorted(scores.items(), key=lambda x: -x[1])[:25]

    text = "🏆 *Top 25 Global Players:*\n\n"
    for i, (uid, score) in enumerate(top_players, 1):
        try:
            user = await context.bot.get_chat(int(uid))
            name = escape_markdown(user.first_name or user.username or f"User {uid}", version=2)
        except:
            name = f"User {uid}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        text += f"{medal} *{name}* — 🏆 {score} trophies\n"

    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    async with score_lock:
        score = scores.get(uid, 0)
    await update.message.reply_text(
        f"📊 *{format_name(user)}'s Score:* {score} trophies",
        parse_mode="MarkdownV2"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if not update.message or not update.message.text:
        return
    word = update.message.text.strip().lower()
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'playing':
            return
        current_player = game.players[game.current_player_index]
        if user.id != current_player.id:
            return
        success = await game.process_word(user, word)
        if success:
            await update.message.reply_text(
                f"✅ `{word.upper()}` accepted! Next letter: `{game.current_word[-1].upper()}`",
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text(
                f"❌ Invalid word. It must be:\n"
                f"- Valid & unused\n"
                f"- Min {game.get_round_params()[0]} letters\n"
                f"- Start with `{game.current_word[-1]}`",
                parse_mode="MarkdownV2"
            )


def main():
    application = Application.builder().token("YOUR_BOT_TOKEN_HERE").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("startclassic", startclassic))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("score", show_score))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("endgame", endgame))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, handle_message))

    application.run_polling()


if __name__ == "__main__":
    main()
