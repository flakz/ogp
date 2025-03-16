# 🤖 Silent Protocol Monitor Bot

A Telegram bot for monitoring participation status in the Silent Protocol ceremony.

![Bot Preview](https://via.placeholder.com/800x400.png?text=Bot+Interface+Preview)

## Features ✨

- **Secure Token Management**  
  🔐 Add/remove multiple authentication tokens with end masking  
- **Real-time Monitoring**  
  ⏰ 5-minute interval checks | 📈 Position tracking | 🔔 Change alerts  
- **Interactive Interface**  
  📱 Menu navigation | 📝 Markdown formatting | 👥 Multi-user support  
- **Reliable Infrastructure**  
  🔄 3x Retry logic | 🏥 Health endpoint | 🛡️ Error recovery

## Deployment 🚀

### Render.com Setup
1. Create new **Web Service**
2. Configure settings:
   ```bash
   # Environment Variables
   TELEGRAM_BOT_TOKEN="your_bot_token_here"
   PORT="10000"

   # Build Command
   pip install -r requirements.txt

   # Start Command
   python3 bot.py
Enable uptime monitoring at:
https://your-service.onrender.com/health

Installation 📦
bash
Copy
git clone https://github.com/yourusername/silent-protocol-bot.git
cd silent-protocol-bot
pip install -r requirements.txt
Configuration ⚙️
Create .env file:

ini
Copy
TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_HERE"
PORT=10000
Usage 📋
Basic Commands:

Copy
/start - Initialize bot interface
cancel - Abort current operation
Main Menu Options:

🗝️ Tokens - Manage authentication credentials

📍 Position - Check current queue status

🔍 Monitoring - Control automatic updates

ℹ️ About - Project information

Monitoring Details 🔍
Update Example:

markdown
Copy
🔄 Status Update:
• *...t6k8xo*:
  Status: `Active` 
  Position: `1603`
Status Indicators:

Emoji	Status	Description
🟢	Active	Normal operation
🟡	Temporary Issue	Connection problems
🔴	Service Down	API unreachable
⚪	Unknown	Status unavailable
Contributing 🤝
Fork the repository

Create feature branch:

bash
Copy
git checkout -b feature/awesome-feature
Commit changes:

bash
Copy
git commit -m "Add awesome feature"
Push to branch:

bash
Copy
git push origin feature/awesome-feature
Open a Pull Request

License 📄
This project is proprietary software. Contact maintainer for usage permissions.

Acknowledgments 🙏
Silent Protocol Team for API access

Telegram for Bot API infrastructure

Render.com for hosting support

aiohttp for async networking
