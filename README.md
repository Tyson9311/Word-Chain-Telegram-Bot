# 🔠 Word Chain Battle Bot 🤖

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![Telegram Library](https://img.shields.io/badge/python--telegram--bot-20.0-cyan)](https://github.com/python-telegram-bot/python-telegram-bot)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An addictive multiplayer word chain game for Telegram groups. Battle friends through progressively challenging stages and climb the leaderboard! 🚀

---

## 🌟 Features

- **5 Difficulty Stages** (3 → 7+ letters, 35s → 15s timeouts)
- **Multiplayer Support** (2+ players)
- **Trophy System & Leaderboards**
- **Admin Controls** (Score reset)
- **Markdown-rich UI** with emoji feedback

---

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

1. Clone the repo:

   ```bash
   git clone https://github.com/your-username/word-chain-bot.git
   cd word-chain-bot
   ```

2. Install dependencies:

   ```bash
   pip install python-telegram-bot
   ```

3. Add your words list:

   ```bash
   echo '["apple", "banana", "cherry"]' > words.json  # Add your own words
   ```

### Configuration
Replace the bot token in **bot.py**:

```python
application = Application.builder().token("YOUR_BOT_TOKEN_HERE").build()
```

### Running the Bot

```bash
python bot.py
```

---

## 📂 Project Structure
```
├── bot.py            - Main bot logic
├── words.json        - Valid word database (add your own words)
├── score.json        - Auto-generated player scores
├── README.md         - Project documentation
└── LICENSE           - License file
```

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch:
   ```bash
   git checkout -b feature/your-feature
   ```
3. Commit your changes:
   ```bash
   git commit -m 'Add awesome feature'
   ```
4. Push to the branch:
   ```bash
   git push origin feature/your-feature
   ```
5. Open a Pull Request

If you find bugs or have enhancement ideas, please open an issue with detailed steps to reproduce.

---

## 📜 License
Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

## 📌 Roadmap
- Add multiplayer team battles
- Implement daily challenges
- Support multiple languages
- Add achievement system

---

## 📧 Contact
For support or suggestions, open a GitHub Issue or reach out on Telegram:

- Telegram: [@suu_111](https://t.me/suu_111)
- GitHub Issues: `https://github.com/your-username/word-chain-bot/issues`

---

> **Pro Tip:** Use `/startclassic` in your group after deployment to kick off the battle! 🔥
