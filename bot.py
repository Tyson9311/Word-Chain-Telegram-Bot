import json
import os
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackContext
)
from telegram.helpers import escape_markdown

# =========================
# 🔹 BOT CONFIGURATION
# =========================
BOT_OWNER_ID = 7589421463 # Replace with your Telegram ID
SUDO_FILE = "sudo.json"

# Load sudo users
if os.path.exists(SUDO_FILE):
    with open(SUDO_FILE, "r") as f:
        SUDO_USERS = json.load(f)
else:
    SUDO_USERS = [8170921465, 8037102614, 7565878376]
    with open(SUDO_FILE, "w") as f:
        json.dump(SUDO_USERS, f)

# Load dictionary
with open("Dictionary.txt", "r", encoding="utf-8") as f:
    valid_words = set(word.strip().lower() for word in f if word.strip())

# Score management
score_lock = asyncio.Lock()
try:
    with open("score.json", "r") as f:
        scores = json.load(f)
except FileNotFoundError:
    scores = {}

active_games = {}
game_lock = asyncio.Lock()

# Virtual player object
class VirtualPlayer:
    id = -1
    first_name = "🤖 Virtual Player"

VIRTUAL_PLAYER = VirtualPlayer()

# =========================
# 🔹 GAME STATE CLASS
# =========================
class GameState:
    INCREMENT_SEQUENCE = [
        (5, 3, 35),   # 5 words -> min_len 3 -> timeout 35s
        (5, 4, 30),
        (5, 5, 25),
        (5, 6, 20),
        (None, 7, 15)  # Unlimited stage
    ]

    def __init__(self, chat_id, bot, mode="classic"):
        self.chat_id = chat_id
        self.bot = bot
        self.players = []
        self.used_words = set()
        self.increment_stage = 0
        self.words_played_in_stage = 0
        self.current_player_index = 0
        self.current_word = None
        self.timer_task = None
        self.state = "joining"
        self.join_task = None
        self.mode = mode  # classic, required, choose_first
        self.required_letter = None
        self.first_letter = None
        self.extended_users = set()
        self.total_extend = 0

    def get_round_params(self):
        if self.increment_stage >= len(self.INCREMENT_SEQUENCE):
            return self.INCREMENT_SEQUENCE[-1][1], self.INCREMENT_SEQUENCE[-1][2]
        return self.INCREMENT_SEQUENCE[self.increment_stage][1], self.INCREMENT_SEQUENCE[self.increment_stage][2]

    async def start_game(self):
        min_length, timeout = self.get_round_params()

        # Mode setup
        if self.mode == "classic" or self.mode == "required":
            valid_start_words = [w for w in valid_words if len(w) >= min_length]
            self.current_word = random.choice(valid_start_words).lower()
            self.used_words.add(self.current_word)

        if self.mode == "choose_first":
            self.first_letter = random.choice("abcdefghijklmnopqrstuvwxyz").lower()

        # Send starting message
        start_msg = "🎮 *WORD CHAIN GAME STARTED!*\n\n"
        if self.mode == "classic":
            start_msg += f"🔹 *Starting word:* `{self.current_word.upper()}`\n"
        elif self.mode == "required":
            start_msg += (
                f"✨ *Turn-wise Required Letter Mode*\n"
                f"🔹 *Starting word:* `{self.current_word.upper()}`\n"
                f"🔹 Each turn will have a new required letter!\n"
            )
        elif self.mode == "choose_first":
            start_msg += (
                f"✨ *Choose First Letter Mode*\n"
                f"🔹 Starting letter: `{self.first_letter.upper()}`\n"
                f"🔹 All words must start with this letter!\n"
            )

        await self.bot.send_message(
            self.chat_id, start_msg, parse_mode="MarkdownV2"
        )

        await self.next_turn()

async def next_turn(self):
        """Handle the next player's turn."""
        if len(self.players) == 1:
            await self.end_game(self.players[0])
            return

        # Cancel old timer
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

        min_length, timeout = self.get_round_params()
        player = self.players[self.current_player_index]

        # Select required letter for this turn if mode = required
        if self.mode == "required":
            self.required_letter = random.choice("abcdefghijklmnopqrstuvwxyz")

        # Prepare turn message
        escaped_name = escape_markdown(format_name(player), version=2)
        msg = f"🌀 *{escaped_name}'s Turn!* 🌀\n\n"
        msg += f"⌛ Timeout: {timeout}s\n"
        msg += f"📏 Min Length: {min_length} letters\n"

        if self.mode == "classic":
            required_letter = self.current_word[-1].upper() if self.current_word else "ANY"
            msg += f"🔗 Must Start With: `{escape_markdown(required_letter, version=2)}`\n"
        elif self.mode == "required":
            msg += f"🎯 Word must contain: `{self.required_letter.upper()}`\n"
        elif self.mode == "choose_first":
            msg += f"🔗 Must Start With: `{self.first_letter.upper()}`\n"

        await self.bot.send_message(self.chat_id, msg, parse_mode="MarkdownV2")

        # Virtual player turn
        if player.id == -1:  # Virtual player
            await asyncio.sleep(2)
            word = self.get_virtual_word(min_length)
            if not word:
                await self.eliminate_player(player)
                return
            await self.bot.send_message(self.chat_id, f"🤖 Virtual Player: `{word}`", parse_mode="MarkdownV2")
            await self.process_word(player, word)
            return

        # Start timeout task for real player
        self.timer_task = asyncio.create_task(self.handle_timeout(timeout, player.id))

    def get_virtual_word(self, min_length):
        """Get a random valid word for virtual player according to current mode."""
        words = list(valid_words - self.used_words)
        random.shuffle(words)

        for word in words:
            if len(word) < min_length:
                continue
            if self.mode == "classic" and self.current_word:
                if not word.startswith(self.current_word[-1]):
                    continue
            if self.mode == "required":
                if self.required_letter not in word:
                    continue
            if self.mode == "choose_first":
                if not word.startswith(self.first_letter):
                    continue
            return word
        return None

    async def process_word(self, user, word):
        """Validate and process the word played by user or virtual player."""
        min_length, _ = self.get_round_params()
        word_lower = word.strip().lower()

        # Validation
        if len(word_lower) < min_length:
            return False
        if word_lower not in valid_words:
            return False
        if word_lower in self.used_words:
            return False
        if self.mode == "classic" and self.current_word:
            if not word_lower.startswith(self.current_word[-1]):
                return False
        if self.mode == "required":
            if self.required_letter not in word_lower:
                return False
        if self.mode == "choose_first":
            if not word_lower.startswith(self.first_letter):
                return False

        # Update state
        self.used_words.add(word_lower)
        self.current_word = word_lower
        self.words_played_in_stage += 1
        self.current_player_index = (self.current_player_index + 1) % len(self.players)

        # Stage progression
        current_stage = self.INCREMENT_SEQUENCE[self.increment_stage]
        required_words, _, _ = current_stage
        if required_words is not None and self.words_played_in_stage >= required_words:
            self.increment_stage += 1
            self.words_played_in_stage = 0
            await self.announce_new_stage()

        # Cancel old timer and move to next turn
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

        await self.next_turn()
        return True

    async def handle_timeout(self, timeout, user_id):
        await asyncio.sleep(timeout)
        async with game_lock:
            if self.state != 'playing' or self.current_player_index >= len(self.players):
                return
            current_player = self.players[self.current_player_index]
            if current_player.id == user_id:
                await self.eliminate_player(current_player)

    async def announce_new_stage(self):
        min_length, timeout = self.get_round_params()
        current_stage = self.increment_stage + 1
        await self.bot.send_message(
            self.chat_id,
            f"🚀🚀 *ADVANCING TO STAGE {current_stage}* 🚀🚀\n\n"
            f"📏 Min Length: `{min_length}` letters\n"
            f"⌛ Timeout: `{timeout}` seconds\n",
            parse_mode="MarkdownV2"
        )

    async def eliminate_player(self, player):
        self.players.remove(player)
        escaped_name = escape_markdown(format_name(player), version=2)
        await self.bot.send_message(
            self.chat_id,
            f"💥 *TIME'S UP!* 💥\n"
            f"😢 *{escaped_name}* has been eliminated!\n"
            f"🚫 Remaining players: *{len(self.players)}*",
            parse_mode="MarkdownV2"
        )

        if len(self.players) > 1:
            self.current_player_index %= len(self.players)
            await self.next_turn()
        else:
            winner = self.players[0]
            await self.end_game(winner)
            async with game_lock:
                if self.chat_id in active_games:
                    del active_games[self.chat_id]

    async def end_game(self, winner):
        self.state = 'ended'
        async with score_lock:
            scores[str(winner.id)] = scores.get(str(winner.id), 0) + 10
            with open('score.json', 'w') as f:
                json.dump(scores, f)

        escaped_name = escape_markdown(format_name(winner), version=2)
        await self.bot.send_message(
            self.chat_id,
            f"🎉🎊 *VICTORY!* 🎊🎉\n\n"
            f"👑 *{escaped_name}* wins the game!\n"
            f"➕ +10 Points 🏆\n\n"
            f"🏅 New total: *{scores.get(str(winner.id), 0)}*",
            parse_mode="MarkdownV2"
        )

        async with game_lock:
            if self.chat_id in active_games:
                del active_games[self.chat_id]
# =========================
# 🔹 Helper Functions
# =========================

def format_name(user):
    return escape_markdown(user.first_name or "Player", version=2)

def is_owner(user_id):
    return user_id == BOT_OWNER_ID

def is_sudo(user_id):
    return user_id in SUDO_USERS

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ["administrator", "creator"]
    except:
        return False

async def startclassic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        if chat_id in active_games:
            await update.message.reply_text("⚠️ A game is already in progress!")
            return
        game = GameState(chat_id, context.bot, mode="classic")
        active_games[chat_id] = game
        game.join_task = asyncio.create_task(start_joining(chat_id, context.bot))
        await update.message.reply_text(
            "🎮 *Classic Mode Game Started!*\n"
            "⏳ Use /join to enter the game within 30 seconds.",
            parse_mode="MarkdownV2"
        )

async def startrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        if chat_id in active_games:
            await update.message.reply_text("⚠️ A game is already in progress!")
            return
        game = GameState(chat_id, context.bot, mode="required")
        active_games[chat_id] = game
        game.join_task = asyncio.create_task(start_joining(chat_id, context.bot))
        await update.message.reply_text(
            "🎮 *Turn-wise Required Letter Mode Started!*\n"
            "⏳ Use /join to enter within 30 seconds.",
            parse_mode="MarkdownV2"
        )

async def startcfl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        if chat_id in active_games:
            await update.message.reply_text("⚠️ A game is already in progress!")
            return
        game = GameState(chat_id, context.bot, mode="choose_first")
        active_games[chat_id] = game
        game.join_task = asyncio.create_task(start_joining(chat_id, context.bot))
        await update.message.reply_text(
            "🎮 *Choose First Letter Mode Started!*\n"
            "⏳ Use /join to enter within 30 seconds.",
            parse_mode="MarkdownV2"
        )

async def start_joining(chat_id, bot):
    # 30 sec + extend logic
    duration = 30
    await asyncio.sleep(duration)
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != "joining":
            return
        if len(game.players) >= 2:
            game.state = "playing"
            await game.start_game()
        else:
            await bot.send_message(chat_id, "❌ Not enough players. Game cancelled.")
            del active_games[chat_id]

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != "joining":
            await update.message.reply_text("🚫 No active game to join.")
            return
        if user in game.players:
            await update.message.reply_text("✅ You have already joined!")
            return
        game.players.append(user)
        await update.message.reply_text(
            f"🎉 *WELCOME {format_name(user)}!* 🎉\n"
            f"📊 Current players: *{len(game.players)}*",
            parse_mode="MarkdownV2"
        )

async def vpjoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != "joining":
            await update.message.reply_text("🚫 No game to add virtual player.")
            return
        if VIRTUAL_PLAYER in game.players:
            await update.message.reply_text("🤖 Virtual player already joined!")
            return
        game.players.append(VIRTUAL_PLAYER)
        await update.message.reply_text("🤖 Virtual Player joined the game!")

async def vpflee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != "joining":
            await update.message.reply_text("🚫 No game to remove virtual player.")
            return
        if VIRTUAL_PLAYER in game.players:
            game.players.remove(VIRTUAL_PLAYER)
            await update.message.reply_text("🤖 Virtual Player has left the game!")

async def extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != "joining":
            await update.message.reply_text("🚫 No active game to extend.")
            return
        # Check limit
        if game.total_extend >= 180:
            await update.message.reply_text("⚠️ Maximum extension limit reached (180s).")
            return
        # Normal user can extend only once
        if not (is_owner(user.id) or is_sudo(user.id) or await is_admin(update, context)):
            if user.id in game.extended_users:
                await update.message.reply_text("❌ You can extend only once per game!")
                return
            game.extended_users.add(user.id)

        game.total_extend += 30
        await update.message.reply_text(
            f"✅ Join time extended by 30s! Total: {game.total_extend}s",
            parse_mode="MarkdownV2"
        )
async def endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Permission check
    allowed = False
    if is_owner(user.id) or is_sudo(user.id):
        allowed = True
    else:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in ["administrator", "creator"]:
            allowed = True

    if not allowed:
        await update.message.reply_text("🚫 Only owner, sudo, or group admin/owner can end the game.")
        return

    async with game_lock:
        if chat_id in active_games:
            del active_games[chat_id]
            await update.message.reply_text("🛑 Game ended by authorized user.")
        else:
            await update.message.reply_text("⚠️ No active game.")

async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("🚫 Only owner can add words.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addword <word>")
        return

    word = context.args[0].lower().strip()
    if word in valid_words:
        await update.message.reply_text("⚠️ Word already exists.")
        return

    valid_words.add(word)
    with open("Dictionary.txt", "a", encoding="utf-8") as f:
        f.write("\n" + word)

    await update.message.reply_text(f"✅ Word '{word}' added to dictionary.")

async def addsudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("🚫 Only owner can add sudo users.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addsudo <user_id>")
        return

    try:
        new_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    if new_id in SUDO_USERS:
        await update.message.reply_text("⚠️ User already a sudo.")
        return

    SUDO_USERS.append(new_id)
    with open(SUDO_FILE, "w") as f:
        json.dump(SUDO_USERS, f)

    await update.message.reply_text(f"✅ User {new_id} added as sudo.")

async def rmsudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("🚫 Only owner can remove sudo users.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /rmsudo <user_id>")
        return

    try:
        rm_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    if rm_id not in SUDO_USERS:
        await update.message.reply_text("⚠️ User is not in sudo list.")
        return

    SUDO_USERS.remove(rm_id)
    with open(SUDO_FILE, "w") as f:
        json.dump(SUDO_USERS, f)

    await update.message.reply_text(f"✅ User {rm_id} removed from sudo.")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with score_lock:
        top = sorted(scores.items(), key=lambda x: -x[1])[:25]

    if not top:
        await update.message.reply_text("📭 No scores yet.")
        return

    lb_header = "🏆✨ *TOP 25 CHAMPIONS* ✨🏆\n\n"
    lb_body = ""

    for i, (user_id, score) in enumerate(top, 1):
        try:
            user_obj = await context.bot.get_chat(int(user_id))
            username = user_obj.first_name or "Player"
        except:
            username = "Unknown"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        lb_body += f"{medal} *{escape_markdown(username, version=2)}* — 🎖 *{score}*\n"

    # Show current user rank
    user_id = str(update.effective_user.id)
    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    if user_id in dict(sorted_scores):
        rank = [uid for uid, _ in sorted_scores].index(user_id) + 1
        lb_footer = f"\n⭐ Your Rank: #{rank} (Score: {scores.get(user_id,0)})"
        if rank > 25:
            lb_footer += "\n🔹 Keep playing to enter the Top 25!"
    else:
        lb_footer = "\n⭐ You are unranked. Start playing to enter the leaderboard!"

    await update.message.reply_text(lb_header + lb_body + lb_footer, parse_mode="MarkdownV2")

# =========================
# 🔹 Main Function
# =========================
def main():
    application = Application.builder().token("8473680350:AAHQxPgea_Y7Lj5LnVP2WFzxv6gL9omBwsw").build()

    # Core commands
    application.add_handler(CommandHandler("startclassic", startclassic))
    application.add_handler(CommandHandler("startrl", startrl))
    application.add_handler(CommandHandler("startcfl", startcfl))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("vpjoin", vpjoin))
    application.add_handler(CommandHandler("vpflee", vpflee))
    application.add_handler(CommandHandler("extend", extend))
    application.add_handler(CommandHandler("endgame", endgame))
    application.add_handler(CommandHandler("leaderboard", leaderboard))

    # Owner-only commands
    application.add_handler(CommandHandler("addword", addword))
    application.add_handler(CommandHandler("addsudo", addsudo))
    application.add_handler(CommandHandler("rmsudo", rmsudo))

    # Game message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_message
    ))

    application.run_polling()

if __name__ == "__main__":
    main()
