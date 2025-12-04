#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import telebot
from telebot import types
from flask import Flask, request, render_template_string
import json
import random

# --- إعدادات البوت ---
# غير هذا الرقم إلى الآيدي الخاص بك في تيليجرام لتتمكن من شحن الأرصدة
ADMIN_ID = 5665438577  
TOKEN = os.environ.get("BOT_TOKEN", "default_token")
SITE_URL = os.environ.get("SITE_URL", "https://example.com")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- قواعد البيانات (في الذاكرة حالياً) ---
# ملاحظة: هذه البيانات ستمسح عند إعادة تشغيل السيرفر.

# قائمة المنتجات
marketplace_items = []

# بيانات المستخدمين (الرصيد)
# الشكل: { user_id: balance }
users_wallets = {}

# العمليات المعلقة (المبالغ المحجوزة)
transactions = {}

# --- دوال مساعدة ---
def get_balance(user_id):
    return users_wallets.get(str(user_id), 0.0)

def add_balance(user_id, amount):
    uid = str(user_id)
    if uid not in users_wallets:
        users_wallets[uid] = 0.0
    users_wallets[uid] += float(amount)

# --- كود صفحة الويب (HTML + JavaScript) ---
HTML_PAGE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>سوق البوت</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #6c5ce7;
            --primary-dark: #5849be;
            --bg-color: var(--tg-theme-bg-color, #1a1a1a);
            --text-color: var(--tg-theme-text-color, #ffffff);
            --card-bg: var(--tg-theme-secondary-bg-color, #2d2d2d);
            --hint-color: var(--tg-theme-hint-color, #a8a8a8);
        }

        body {
            font-family: 'Tajawal', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 16px;
            box-sizing: border-box;
            transition: all 0.3s ease;
        }

        .card {
            background: var(--card-bg);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            animation: fadeIn 0.5s ease-in-out;
        }

        .user-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .user-info h3 { margin: 0; font-size: 1.1rem; }
        .user-info p { margin: 4px 0 0; font-size: 0.85rem; color: var(--hint-color); }
        .avatar {
            width: 50px; height: 50px;
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 24px; color: white;
            font-weight: bold;
        }

        h3.section-title { font-size: 1rem; margin-bottom: 15px; color: var(--primary); }
        
        input {
            width: 100%;
            padding: 14px;
            margin-bottom: 12px;
            background-color: var(--bg-color);
            border: 1px solid transparent;
            border-radius: 12px;
            color: var(--text-color);
            font-family: inherit;
            box-sizing: border-box;
            transition: 0.3s;
        }
        input:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.2);
        }

        button {
            background: linear-gradient(90deg, var(--primary), var(--primary-dark));
            color: white;
            border: none;
            padding: 14px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 1rem;
            cursor: pointer;
            width: 100%;
            transition: transform 0.1s;
            box-shadow: 0 4px 15px rgba(108, 92, 231, 0.4);
        }
        button:active { transform: scale(0.98); }

        .item-card {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .item-card:last-child { border-bottom: none; }
        
        .item-details b { display: block; font-size: 1.1rem; margin-bottom: 4px; }
        .item-details small { color: var(--hint-color); font-size: 0.8rem; }
        
        .item-right {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 8px;
        }
        
        .price-tag {
            background-color: rgba(108, 92, 231, 0.15);
            color: #a29bfe;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9rem;
        }
        
        .buy-btn {
            background: linear-gradient(90deg, #00b894, #00cec9);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: bold;
            font-size: 0.85rem;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            box-shadow: 0 2px 8px rgba(0, 184, 148, 0.3);
            transition: transform 0.1s;
        }
        .buy-btn:active { transform: scale(0.95); }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>

    <div class="card user-header">
        <div class="user-info">
            <h3>مرحباً، <span id="name">...</span> 👋</h3>
            <p>ID: <span id="id">...</span></p>
        </div>
        <div class="avatar">👤</div>
    </div>

    <div class="card">
        <h3 class="section-title">➕ عرض سلعة جديدة</h3>
        <input type="text" id="itemInput" placeholder="اسم السلعة (مثلاً: حساب ببجي)">
        <input type="number" id="priceInput" placeholder="السعر (ريال)">
        <button onclick="sellItem()">نشر الإعلان 🚀</button>
    </div>

    <h3 style="margin: 20px 5px 10px;">🛒 المعروضات في السوق</h3>
    <div id="market" class="card" style="padding: 0;">
        {% if items|length == 0 %}
            <p style="text-align: center; padding: 20px; color: gray;">لا توجد سلع معروضة حالياً</p>
        {% else %}
            {% for item in items %}
            <div class="item-card">
                <div class="item-details">
                    <b>{{ item.item_name }}</b>
                    <small>البائع: {{ item.seller_name }}</small>
                </div>
                <div class="item-right">
                    <div class="price-tag">{{ item.price }} ريال</div>
                    <a href="tg://user?id={{ item.seller_id }}" class="buy-btn">
                        شراء 🛒
                    </a>
                </div>
            </div>
            {% endfor %}
        {% endif %}
    </div>

    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();

        tg.MainButton.textColor = '#FFFFFF';
        tg.MainButton.color = '#6c5ce7';

        let user = tg.initDataUnsafe.user;
        if (user) {
            document.getElementById("name").innerText = user.first_name;
            document.getElementById("id").innerText = user.id;
        }

        function sellItem() {
            let itemName = document.getElementById("itemInput").value;
            let price = document.getElementById("priceInput").value;

            if(!itemName || !price) {
                tg.showAlert("يرجى كتابة اسم السلعة والسعر");
                return;
            }

            let btn = document.querySelector("button");
            let oldText = btn.innerText;
            btn.innerText = "جاري النشر...";
            btn.disabled = true;

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
                    tg.showPopup({
                        title: "تم بنجاح! ✅",
                        message: "تمت إضافة السلعة إلى السوق",
                        buttons: [{type: "ok", text: "حسناً"}]
                    }, function() {
                        location.reload();
                    });
                }
            }).catch(err => {
                btn.innerText = oldText;
                btn.disabled = false;
                tg.showAlert("حدث خطأ في الاتصال");
            });
        }
    </script>
</body>
</html>
"""

# --- أوامر البوت ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك في السوق الآمن! 🛡️\nاستخدم /web للدخول.\nاستخدم /my_id لمعرفة الآيدي الخاص بك.")

@bot.message_handler(commands=['my_id'])
def my_id(message):
    bot.reply_to(message, f"الآيدي الخاص بك: `{message.from_user.id}`", parse_mode="Markdown")

# أمر خاص بالآدمن لشحن رصيد المستخدمين
# طريقة الاستخدام: /add ID AMOUNT
# مثال: /add 123456789 50
@bot.message_handler(commands=['add'])
def add_funds(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمشرف فقط.")
    
    try:
        parts = message.text.split()
        target_id = parts[1]
        amount = float(parts[2])
        add_balance(target_id, amount)
        bot.reply_to(message, f"✅ تم إضافة {amount} ريال للمستخدم {target_id}")
        bot.send_message(target_id, f"🎉 تم شحن رصيدك بمبلغ {amount} ريال!")
    except:
        bot.reply_to(message, "خطأ! الاستخدام: /add ID AMOUNT")

@bot.message_handler(commands=['web'])
def open_web_app(message):
    markup = types.InlineKeyboardMarkup()
    web_app_button = types.InlineKeyboardButton(text="فتح السوق 🏪", web_app=types.WebAppInfo(url=SITE_URL))
    markup.add(web_app_button)
    bot.send_message(message.chat.id, "تفضل بدخول السوق:", reply_markup=markup)

# زر تأكيد الاستلام (يحرر المال للبائع)
@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_'))
def confirm_transaction(call):
    trans_id = call.data.split('_')[1]
    
    if trans_id not in transactions:
        return bot.answer_callback_query(call.id, "هذه العملية غير موجودة")
    
    trans = transactions[trans_id]
    
    # التأكد أن الذي يضغط هو المشتري فقط
    if str(call.from_user.id) != str(trans['buyer_id']):
        return bot.answer_callback_query(call.id, "فقط المشتري يمكنه تأكيد الاستلام!", show_alert=True)

    # تحرير المال للبائع
    seller_id = trans['seller_id']
    amount = trans['amount']
    
    # إضافة الرصيد للبائع
    add_balance(seller_id, amount)
    
    # حذف العملية من الانتظار
    del transactions[trans_id]
    
    bot.edit_message_text(f"✅ تم تأكيد استلام السلعة: {trans['item_name']}\nتم تحويل {amount} ريال للبائع.", call.message.chat.id, call.message.message_id)
    bot.send_message(seller_id, f"🤑 مبروك! قام المشتري بتأكيد الاستلام.\nتم إضافة {amount} ريال لرصيدك.")

# --- مسارات الموقع (Flask) ---

@app.route('/')
def index():
    return render_template_string(HTML_PAGE, items=marketplace_items, balance=0, current_user_id=0)

@app.route('/sell', methods=['POST'])
def sell_item():
    data = request.json
    marketplace_items.append(data)
    return {'status': 'success'}

@app.route('/buy', methods=['POST'])
def buy_item():
    data = request.json
    buyer_id = str(data.get('buyer_id'))
    item_index = int(data.get('item_index'))
    
    if item_index >= len(marketplace_items):
        return {'status': 'error', 'message': 'السلعة غير موجودة'}
    
    item = marketplace_items[item_index]
    price = float(item['price'])
    
    # 1. التحقق من الرصيد
    buyer_balance = get_balance(buyer_id)
    if buyer_balance < price:
        return {'status': 'error', 'message': 'الرصيد غير كافي'}
    
    # 2. خصم الرصيد (تجميده)
    users_wallets[buyer_id] -= price
    
    # 3. إنشاء عملية جديدة
    trans_id = str(random.randint(10000, 99999))
    transactions[trans_id] = {
        'buyer_id': buyer_id,
        'seller_id': item['seller_id'],
        'amount': price,
        'item_name': item['item_name']
    }
    
    # 4. إزالة السلعة من السوق
    del marketplace_items[item_index]
    
    # 5. إرسال الإشعارات
    
    # إشعار للبائع
    bot.send_message(item['seller_id'], 
                     f"🔔 **طلب شراء جديد!**\n"
                     f"شخص ما اشترى: {item['item_name']}\n"
                     f"المبلغ ({price} ريال) محفوظ لدى البوت ❄️.\n"
                     f"تواصل مع المشتري وسلمه السلعة.\n"
                     f"آيدي المشتري: `{buyer_id}`", parse_mode="Markdown")
                     
    # إشعار للمشتري مع زر التأكيد
    markup = types.InlineKeyboardMarkup()
    confirm_btn = types.InlineKeyboardButton("✅ استلمت السلعة (حرر المبلغ)", callback_data=f"confirm_{trans_id}")
    markup.add(confirm_btn)
    
    bot.send_message(buyer_id,
                     f"❄️ **تم خصم {price} ريال وحجزها.**\n"
                     f"السلعة: {item['item_name']}\n"
                     f"لا تضغط الزر أدناه إلا بعد أن تستلم السلعة من البائع وتتأكد منها!", 
                     reply_markup=markup, parse_mode="Markdown")

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
