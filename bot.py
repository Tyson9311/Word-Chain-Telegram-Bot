import json
import asyncio
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters,CallbackContext
import random
from telegram.helpers import escape_markdown
from telegram import BotCommand

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

async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("join", "Join the game"),
        BotCommand("score", "Check your score"),
        BotCommand("leaderboard", "View top players"),
        BotCommand("startclassic", "Start a classic word chain game"),
        BotCommand("help", "Get help & bot instructions"),
        BotCommand("rules", "View game rules"),
        BotCommand("reset", "Reset scores (admin only)"),
    ]
    await application.bot.set_my_commands(commands)


class GameState:
    INCREMENT_SEQUENCE = [
        (5, 3, 35),   # Stage 0: 10 words, min_length 3, timeout 60
        (5, 4, 30),   # Stage 1: 10 words, min_length 4, timeout 50
        (5, 5, 25),   # Stage 2: 10 words, min_length 5, timeout 40
        (5, 6, 20),   # Stage 3: 10 words, min_length 6, timeout 30
        (None, 7, 15)  # Stage 4: until game ends, min_length 7, timeout 20
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

    async def start_game(self):
        min_length, timeout = self.get_round_params()
        valid_start_words = [w for w in valid_words if len(w) >= min_length]
        self.current_word = random.choice(valid_start_words).lower()
        self.used_words.add(self.current_word)
        current_stage = self.increment_stage + 1
        
        escaped_word = escape_markdown(self.current_word.upper(), version=2)
        last_char = escape_markdown(self.current_word[-1].upper(), version=2)
        used_words_list = [escape_markdown(w, version=2) for w in list(self.used_words)[-3:]]

        await self.bot.send_message(
            self.chat_id,
            f"✨🔥 *WORD CHAIN BATTLE COMMENCES\\!* 🔥✨\n\n\n"
            f"🗝️ *Starting Word:* `{escaped_word}`\n\n"
            f"📜 *Round {current_stage} Rules:*\n\n"
            f"   ⚡️ *Min Length:* `{min_length}` letters\n"
            f"   ⏳ *Timeout:* `{timeout}s`\n"
            f"   🔄 *Chain Rule:* `{last_char}` ➔ ❓\n"
            f"   Remember used words: `{', '.join(used_words_list)}`\n\n"
            "🔹━━━━━━━━━━━━━━━━━━━━🔹\n",
            parse_mode="MarkdownV2"
        )
        await self.next_turn()

    async def announce_new_stage(self):
        min_length, timeout = self.get_round_params()
        current_stage = self.increment_stage + 1

        await self.bot.send_message(
            self.chat_id,
            f"🚀🚀 *ADVANCING TO STAGE {current_stage}* 🚀🚀\n\n"
            f"⚡ *New Parameters:*\n"
            f"📏 *Min Length:* `{min_length}` letters\n"
            f"⌛ *Timeout:* `{timeout}` seconds\n\n"
            f"💡 _The difficulty increases\\!_",
            parse_mode="MarkdownV2"
        )

    async def next_turn(self):
        if len(self.players) == 1:
            await self.end_game(self.players[0])
            return

        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

        min_length, timeout = self.get_round_params()
        player = self.players[self.current_player_index]
        current_stage = self.increment_stage + 1
        
        # Escape all dynamic content
        escaped_name = escape_markdown(format_name(player), version=2)
        required_letter = escape_markdown(self.current_word[-1].upper(), version=2) if self.current_word else "ANY"

        await self.bot.send_message(
            self.chat_id,
            f"🌀 *{escaped_name}'S TURN\\!* 🌀\n\n"
            f"⚡ Stage {current_stage}:\n"
            f"⌛ Timeout: {timeout}s\n"
            f"📏 Min Length: {min_length} letters\n"
            f"🔗 Must Start With: '{required_letter}'\n\n",
            parse_mode="MarkdownV2"
        )

        self.timer_task = asyncio.create_task(self.handle_timeout(timeout, player.id))

    async def process_word(self, user, word):
        min_length, _ = self.get_round_params()
        word_lower = word.strip().lower()

        # Validation checks
        if len(word_lower) < min_length:
            return False
        if word_lower not in valid_words:
            return False
        if word_lower in self.used_words:
            return False
        if self.current_word and not word_lower.startswith(self.current_word[-1]):
            return False

        # Update game state
        self.used_words.add(word_lower)
        self.current_word = word_lower
        self.words_played_in_stage += 1
        self.current_player_index = (self.current_player_index + 1) % len(self.players)

        # Check stage progression
        current_stage = self.INCREMENT_SEQUENCE[self.increment_stage]
        required_words, _, _ = current_stage
        if required_words is not None and self.words_played_in_stage >= required_words:
            self.increment_stage += 1
            self.words_played_in_stage = 0
            await self.announce_new_stage()

        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

        await self.next_turn()
        return True

    def get_round_params(self):
        if self.increment_stage >= len(self.INCREMENT_SEQUENCE):
            return self.INCREMENT_SEQUENCE[-1][1], self.INCREMENT_SEQUENCE[-1][2]
        return self.INCREMENT_SEQUENCE[self.increment_stage][1], self.INCREMENT_SEQUENCE[self.increment_stage][2]

    async def handle_timeout(self, timeout, user_id):
        await asyncio.sleep(timeout)
        async with game_lock:
            if self.state != 'playing' or self.current_player_index >= len(self.players):
                return
            current_player = self.players[self.current_player_index]
            if current_player.id == user_id:
                await self.eliminate_player(current_player)

    async def handle_round_timeout(self, round_duration):
        if round_duration is not None:
            await asyncio.sleep(round_duration * 60)  # Convert minutes to seconds
            async with game_lock:
                if self.state == 'playing':
                    await self.end_round()

    async def end_round(self):
        self.current_round += 1
        if self.current_round > 5:
            await self.end_game(self.players[0])  # End game if all rounds are completed
        else:
            await self.start_game()  # Start the next round

    async def eliminate_player(self, player):
        self.players.remove(player)
        escaped_name = escape_markdown(format_name(player), version=2)
        await self.bot.send_message(
            self.chat_id,
            f"💥 *TIME'S UP\\!* 💥\n"
            f"😢 *{escaped_name}* has been eliminated\\!\n"
            f"🚫 Remaining players: *{len(self.players)}*",
            parse_mode="MarkdownV2"
        )
        
        if len(self.players) > 1:
            self.current_player_index %= len(self.players)
            await self.next_turn()
        else:
            # Clean up when only 1 player remains
            winner = self.players[0]
            await self.end_game(winner)
            
            # Remove from active games
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
            f"🎉🎊 *VICTORY ROYALE\\!* 🎊🎉\n\n"
            f"👑 *{escaped_name}* is the ON9 MASTER\\!\n"
            f"➕ *\\+10 Trophies* 🏆\n\n"
            "🏅 \\_New total\\:_ *{}*".format(scores.get(str(winner.id), 0) + 10),
            parse_mode="MarkdownV2"
        )

        async with game_lock:
            del active_games[self.chat_id]
def format_name(user):
    return escape_markdown(user.first_name, version=2)

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'joining':
            await update.message.reply_text("🚫 No active game to join.")
            return
        if user in game.players:
            await update.message.reply_text("✅ You've already joined!")
            return
        game.players.append(user)
        await update.message.reply_text(
            f"🎉 *WELCOME {format_name(user)}!* 🎉\n"
            "📊 Current players: *{}* 👥".format(len(game.players)),
            parse_mode='MarkdownV2'
        )

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Create "Add to Group" button with bot's username
    bot_username = context.bot.username
    add_url = f"https://t.me/{bot_username}?startgroup=start"
    
    keyboard = [[InlineKeyboardButton("➕ Add to Group", url=add_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 *Hi there\!* \n\n"
        f"🎮 I host *Word Chain* games in Telegram groups\!\n"
        f"➕ *Add me to a group to start playing\!* 🚀",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2"
    )

async def startclassic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with game_lock:
        if chat_id in active_games:
            # Game already exists - notify user
            await update.message.reply_text(
                "⚠️ A game is already in progress! Please wait for it to finish."
            )
            return
            
        # Create new game if none exists
        game = GameState(chat_id, context.bot)
        active_games[chat_id] = game
        game.join_task = asyncio.create_task(start_joining(chat_id, context.bot))
        
        # Send game start message
        await update.message.reply_text(
            "🎮 *A new Word Chain game has started\!*\n\n"
            "⏳ *Join now with* `/join` *within 30 seconds\!*",
            parse_mode="MarkdownV2"
        )

async def start_joining(chat_id, bot):
    await asyncio.sleep(60)
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'joining':
            return
        if len(game.players) >= 2:
            game.state = 'playing'
            await game.start_game()
        else:
            await bot.send_message(
                chat_id, 
                "❌ *Not enough players\!* \n"
                "📢 *Game cancelled\.* Try again later\!"
                , parse_mode="MarkdownV2"
            )
            del active_games[chat_id]

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'joining':
            await update.message.reply_text("🚫 No active game to join\\.")
            return
        if user in game.players:
            await update.message.reply_text("✅ You've already joined\\!")
            return
        game.players.append(user)
        await update.message.reply_text(
            f"🎉 *WELCOME {format_name(user)}\\!* 🎉\n"
            "📊 Current players: *{}* 👥".format(len(game.players)),
            parse_mode="MarkdownV2"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    word = update.message.text.strip().lower()
    
    async with game_lock:
        game = active_games.get(chat_id)
        if not game or game.state != 'playing':
            return

        current_player = game.players[game.current_player_index]
        if user.id != current_player.id:
            await update.message.reply_text(
                "⚠️ It\'s not your turn\!", 
                reply_to_message_id=update.message.message_id, 
                parse_mode="MarkdownV2"
            )
            return

        success = await game.process_word(user, word)
        if success:
            await update.message.reply_text(
                f"✅ Accepted\! Next word must start with *{game.current_word[-1].upper()}*",
                parse_mode="MarkdownV2"
            )

        else:
            await update.message.reply_text(
                "❌ *Invalid word\\!* \n\n"
                "⚠️ Your word must meet these conditions:\n"
                f"🔹 *At least* `{game.get_round_params()[0]}` *letters*\n"
                f"🔹 *Must start with:* `{escape_markdown(game.current_word[-1], version=2)}`\n"
                "🔹 *Must be valid \\& unused* ❌",
                parse_mode="MarkdownV2"
            )

async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    async with score_lock:
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        score = scores.get(user_id, 0)
        
        try:
            user_rank = [uid for uid, _ in sorted_scores].index(user_id) + 1
        except ValueError:
            user_rank = "Unranked"

    await update.message.reply_text(
        "🌟 *{}'S TROPHY CASE* 🌟\n\n"
        "🏆 × *{}* \\| 📊 Rank: \\#{}\n\n"
        "✨ _Keep playing to unlock more achievements\\!_ ✨\n"
        "💡 _Top 3 players get special rewards at month end\\!_".format(
            escape_markdown(user.first_name or user.username, version=2),
            score, 
            user_rank
        ),
        parse_mode="MarkdownV2"
    )

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


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with score_lock:
        top = sorted(scores.items(), key=lambda x: -x[1])[:10]

    lb_header = "🏆✨ *TOP CHAMPIONS* ✨🏆\n\n"
    
    lb_body = ""
    for i, (user_id, score) in enumerate(top, 1):
        user = await context.bot.get_chat(int(user_id))
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        username = escape_markdown(f"{user.first_name or ''} @{user.username}" if user.username else user.first_name, version=2)
        
        lb_body += f"{medal} *{username}* — 🎖 *{score}*\n"

    lb_footer = (
        "\n🔥 *Keep playing to climb the ranks\\!* \n"
        "🌟 *Top 3 players win exclusive rewards\\!*"
    )

    await update.message.reply_text(
        lb_header + lb_body + lb_footer,
        parse_mode="MarkdownV2"
    )


async def reset_scores():
    async with score_lock:
        global scores
        scores = {}
        with open('score.json', 'w') as f:
            json.dump(scores, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Welcome to WordChainBot\\!** 🔠✨\n\n"
        "Let the word battle begin\\! 🔥 Type `/startclassic` in a group to get started\\!",
        parse_mode="MarkdownV2"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Word Chain Bot Help*\n\n"
        "🎮 *How to Play:*\n"
        "➜ Use `/join` to enter an active game.\n"
        "➜ The bot gives a word; reply with a valid word starting with the last letter.\n"
        "➜ Survive the rounds to win trophies! 🏆\n\n"
        "📜 *Commands:*\n"
        "➤ `/start` - Start the bot\n"
        "➤ `/startclassic` - Start a new Word Chain game\n"
        "➤ `/join` - Join the game\n"
        "➤ `/score` - Check your score\n"
        "➤ `/leaderboard` - View top players\n"
        "➤ `/help` - Get help & instructions\n\n"
        "💡 *Need support?* Message @suu_111 for any issues!"
    )
    
    await update.message.reply_text(help_text, parse_mode="MarkdownV2")

async def rules(update: Update, context: CallbackContext):
    rules_text = (
        "📜 **Word Chain Game Rules:**\n"
        "- Players take turns to enter words.\n"
        "- The word must start with the last letter of the previous word.\n"
        "- Words must meet the required length (increases as the game progresses).\n"
        "- No repeating words within the same game.\n"
        "- If you fail to submit in time, you're eliminated!\n"
        "🏆 The last player standing wins the round!\n"
    )
    await update.message.reply_text(rules_text, parse_mode="Markdown")

import json
import os

async def reset(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.message.chat_id

    # Check if the user is an admin
    chat_member = await context.bot.get_chat_member(chat_id, user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Only admins can reset scores!")
        return

    # Reset scores by clearing the score file
    score_file = "score.json"
    if os.path.exists(score_file):
        with open(score_file, "w") as f:
            json.dump({}, f)  # Empty dictionary resets scores

    await update.message.reply_text("✅ Scores have been reset!")


def main():
    application = Application.builder().token("8473680350:AAHQxPgea_Y7Lj5LnVP2WFzxv6gL9omBwsw").build()
    
    # Add PRIVATE message handler first
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE, handle_private_message))
    
    # Then add game command handlers
    application.add_handler(CommandHandler("startclassic", startclassic))
    application.add_handler(CommandHandler("join", join))
    
    # Add game message handler BEFORE general text handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_message
    ))
    
    # Other handlers
    application.add_handler(CommandHandler("score", show_score))
    application.add_handler(CommandHandler("endgame", endgame))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("reset", reset))

    application.run_polling()
    

if __name__ == "__main__":
    main()
