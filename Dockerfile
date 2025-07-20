# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependency
RUN pip install --no-cache-dir python-telegram-bot

# Copy your bot code into the image
COPY . .

# Run the bot
CMD ["python", "bot.py"]
