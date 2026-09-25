if __name__ == "__main__":
    print("Clearing any old webhooks...")
    bot.remove_webhook()
    print("Policy Pulse Bot is running and polling for messages...")
    bot.infinity_polling()
