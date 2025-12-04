#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import telebot
from telebot import types
from flask import Flask, request, render_template_string

# --- إعدادات البوت ---
TOKEN = os.environ.get("TOKEN", "default_token")
SITE_URL = os.environ.get("SITE_URL", "https://example.com")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# قائمة بسيطة لتخزين المنتجات في الذاكرة (للتجربة)
marketplace_items = []

# --- كود صفحة الويب (HTML + JavaScript) ---
HTML_PAGE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>سوق البوت</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: sans-serif; background-color: var(--tg-theme-bg-color); color: var(--tg-theme-text-color); padding: 20px; }
        .card { background: var(--tg-theme-secondary-bg-color); padding: 15px; margin-bottom: 10px; border-radius: 8px; }
        button { background-color: var(--tg-theme-button-color); color: var(--tg-theme-button-text-color); border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; width: 100%; margin-top: 10px;}
        input { width: 90%; padding: 10px; margin: 5px 0; border-radius: 5px; border: 1px solid #ccc; }
        h2 { color: var(--tg-theme-link-color); }
    </style>
</head>
<body>

    <div id="user-info" class="card">
        <h3>معلوماتك:</h3>
        <p>الاسم: <span id="name">جاري التحميل...</span></p>
        <p>الآيدي: <span id="id">...</span></p>
    </div>

    <div class="card">
        <h3>عرض سلعة للبيع</h3>
        <input type="text" id="itemInput" placeholder="اسم السلعة">
        <input type="number" id="priceInput" placeholder="السعر">
        <button onclick="sellItem()">نشر في السوق</button>
    </div>

    <h2>المعروضات الحالية:</h2>
    <div id="market">
        {% for item in items %}
        <div class="card">
            <b>{{ item.item_name }}</b> - {{ item.price }} ريال<br>
            <small>بائع: {{ item.seller_name }} (ID: {{ item.seller_id }})</small>
        </div>
        {% endfor %}
    </div>

    <script>
        // تهيئة تطبيق تيليجرام
        let tg = window.Telegram.WebApp;
        tg.expand(); // توسيع الشاشة

        // قراءة بيانات المستخدم
        let user = tg.initDataUnsafe.user;
        
        if (user) {
            document.getElementById("name").innerText = user.first_name;
            document.getElementById("id").innerText = user.id;
        } else {
            document.getElementById("name").innerText = "زائر خارجي";
        }

        function sellItem() {
            let itemName = document.getElementById("itemInput").value;
            let price = document.getElementById("priceInput").value;

            if(!itemName || !price) {
                alert("يرجى ملء جميع الحقول");
                return;
            }

            // إرسال البيانات للسيرفر
            fetch('/sell', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    seller_name: user ? user.first_name : "مجهول",
                    seller_id: user ? user.id : 0,
                    item_name: itemName,
                    price: price
                })
            }).then(response => {
                if(response.ok) {
                    tg.showPopup({title: "تم!", message: "تم نشر سلعتك بنجاح"});
                    setTimeout(() => location.reload(), 1000); // تحديث الصفحة
                }
            });
        }
    </script>
</body>
</html>
"""

# --- أوامر البوت ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك! استخدم الأمر /web لفتح السوق.")

@bot.message_handler(commands=['web'])
def open_web_app(message):
    markup = types.InlineKeyboardMarkup()
    # زر لفتح تطبيق الويب
    web_app_button = types.InlineKeyboardButton(
        text="فتح السوق والبيع 🏪", 
        web_app=types.WebAppInfo(url=SITE_URL)
    )
    markup.add(web_app_button)
    bot.send_message(message.chat.id, "اضغط أدناه للدخول إلى السوق:", reply_markup=markup)

# --- مسارات الموقع (Flask) ---

# الصفحة الرئيسية للسوق
@app.route('/')
def index():
    # كود HTML للصفحة (موجود في الأسفل لتسهيل القراءة)
    return render_template_string(HTML_PAGE, items=marketplace_items)

# استقبال طلب بيع جديد من الموقع
@app.route('/sell', methods=['POST'])
def sell_item():
    data = request.json
    # إضافة المنتج للقائمة
    marketplace_items.append({
        'seller_name': data.get('seller_name'),
        'seller_id': data.get('seller_id'),
        'item_name': data.get('item_name'),
        'price': data.get('price')
    })
    return {'status': 'success'}

# لاستقبال تحديثات تيليجرام (Webhook)
@app.route('/webhook', methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/set_webhook")
def set_webhook():
    webhook_url = SITE_URL + "/webhook"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    return f"Webhook set to {webhook_url}", 200

if __name__ == "__main__":
    # هذا السطر يجعل البوت يعمل على المنفذ الصحيح في ريندر أو 10000 في جهازك
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
