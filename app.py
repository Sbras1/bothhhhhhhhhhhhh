#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import telebot
from telebot import types
from flask import Flask, request, render_template_string, redirect, session
import json
import random
import hashlib
import hmac
import time

# --- إعدادات البوت ---
# غير هذا الرقم إلى الآيدي الخاص بك في تيليجرام لتتمكن من شحن الأرصدة
ADMIN_ID = 5665438577  
TOKEN = os.environ.get("BOT_TOKEN", "default_token")
SITE_URL = os.environ.get("SITE_URL", "https://example.com")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-here-change-it")

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

# دالة للتحقق من أن البيانات قادمة فعلاً من تيليجرام (أمان)
def check_telegram_authorization(auth_data):
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    
    # حذف الهاش من البيانات قبل الترتيب
    data_check_string = []
    for key, value in sorted(auth_data.items()):
        if key != 'hash':
            data_check_string.append(f"{key}={value}")
    
    data_check_string = '\n'.join(data_check_string)
    
    # عملية التشفير السرية باستخدام توكن البوت
    secret_key = hashlib.sha256(TOKEN.encode()).digest()
    hash_result = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    # التحقق من تطابق الهاش + التحقق أن الطلب ليس قديماً (صلاحية 24 ساعة)
    if hash_result != check_hash:
        return False
    if time.time() - int(auth_data.get('auth_date', 0)) > 86400:
        return False
        
    return True

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
            --bg-color: var(--tg-theme-bg-color, #1a1a1a);
            --text-color: var(--tg-theme-text-color, #ffffff);
            --card-bg: var(--tg-theme-secondary-bg-color, #2d2d2d);
            --green: #00b894;
        }
        body { font-family: 'Tajawal', sans-serif; background: var(--bg-color); color: var(--text-color); margin: 0; padding: 16px; }
        .card { background: var(--card-bg); border-radius: 16px; padding: 20px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        input { width: 100%; padding: 14px; margin-bottom: 12px; background: var(--bg-color); border: 1px solid #444; border-radius: 12px; color: var(--text-color); box-sizing: border-box;}
        button { background: var(--primary); color: white; border: none; padding: 12px; border-radius: 12px; width: 100%; font-weight: bold; cursor: pointer; }
        .item-card { display: flex; justify-content: space-between; align-items: center; padding: 15px 0; border-bottom: 1px solid #444; }
        .buy-btn { background: var(--green); width: auto; padding: 8px 20px; font-size: 0.9rem; }
        
        /* زر حسابي */
        .account-btn {
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            color: white;
            padding: 18px;
            border-radius: 16px;
            margin-bottom: 16px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 15px rgba(108, 92, 231, 0.3);
            transition: all 0.3s;
        }
        .account-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(108, 92, 231, 0.4);
        }
        .account-btn-left {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 18px;
            font-weight: bold;
        }
        .account-icon {
            font-size: 28px;
        }
        .arrow {
            transition: transform 0.3s;
            font-size: 16px;
        }
        .arrow.open {
            transform: rotate(180deg);
        }
        
        /* محتوى حسابي */
        .account-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }
        .account-content.open {
            max-height: 500px;
        }
        .account-details {
            background: var(--card-bg);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
        }
        .account-row {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #444;
        }
        .account-row:last-child {
            border-bottom: none;
        }
        .account-label {
            color: #888;
            font-weight: 500;
        }
        .account-value {
            font-weight: bold;
            color: var(--text-color);
        }
        .balance-row {
            background: linear-gradient(135deg, #00b89420, #00cec920);
            padding: 15px !important;
            border-radius: 12px;
            margin: 10px 0;
        }
        .balance-row .account-value {
            color: #00b894;
            font-size: 22px;
        }
        .add-item-section {
            background: linear-gradient(135deg, #00b894, #00cec9);
            padding: 15px;
            border-radius: 12px;
            margin-top: 15px;
            cursor: pointer;
            text-align: center;
            font-weight: bold;
            transition: all 0.3s;
        }
        .add-item-section:hover {
            transform: scale(1.02);
            box-shadow: 0 4px 15px rgba(0, 184, 148, 0.3);
        }
        
        /* قسم إضافة سلعة */
        .sell-section {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }
        .sell-section.open {
            max-height: 400px;
        }
        
        /* نافذة تسجيل الدخول المنبثقة */
        .login-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .login-modal-content {
            background: white;
            padding: 40px;
            border-radius: 20px;
            max-width: 400px;
            width: 90%;
            text-align: center;
            position: relative;
            color: #2d3436;
        }
        .close-modal {
            position: absolute;
            top: 15px;
            left: 15px;
            font-size: 28px;
            cursor: pointer;
            color: #636e72;
        }
        .close-modal:hover {
            color: #2d3436;
        }
        .modal-logo {
            font-size: 50px;
            margin-bottom: 15px;
        }
        .modal-title {
            color: #6c5ce7;
            font-size: 24px;
            margin-bottom: 10px;
        }
        .modal-text {
            color: #636e72;
            margin-bottom: 25px;
            line-height: 1.6;
        }
        .telegram-login-wrapper {
            display: inline-block;
        }
    </style>
</head>
<body>
    <!-- نافذة تسجيل الدخول المنبثقة -->
    <div class="login-modal" id="loginModal">
        <div class="login-modal-content">
            <span class="close-modal" onclick="closeLoginModal()">✕</span>
            <div class="modal-logo">🏪</div>
            <h2 class="modal-title">تسجيل الدخول</h2>
            <p class="modal-text">سجل دخولك عبر تيليجرام للوصول إلى حسابك ومحفظتك</p>
            <div class="telegram-login-wrapper">
                <script async src="https://telegram.org/js/telegram-widget.js?22" 
                        data-telegram-login="tesdtdrbot" 
                        data-size="large" 
                        data-radius="12" 
                        data-auth-url="{SITE_URL}/login_check"
                        data-request-access="write">
                </script>
            </div>
        </div>
    </div>

    <!-- زر حسابي -->
    <div class="account-btn" onclick="toggleAccount()" id="accountBtn">
        <div class="account-btn-left">
            <span class="account-icon">👤</span>
            <span>حسابي</span>
        </div>
        <span class="arrow" id="accountArrow">▼</span>
    </div>
    
    <!-- محتوى حسابي -->
    <div class="account-content" id="accountContent">
        <div class="account-details">
            <div class="account-row">
                <span class="account-label">الاسم:</span>
                <span class="account-value" id="userName">جاري التحميل...</span>
            </div>
            <div class="account-row">
                <span class="account-label">معرف تيليجرام:</span>
                <span class="account-value" id="userId">-</span>
            </div>
            <div class="account-row balance-row">
                <span class="account-label">💰 رصيدك:</span>
                <span class="account-value"><span id="balance">0</span> ريال</span>
            </div>
            
            <div class="add-item-section" onclick="toggleSellSection()">
                ➕ أضف سلعة للبيع
            </div>
        </div>
    </div>
    
    <!-- قسم إضافة سلعة -->
    <div class="sell-section" id="sellSection">
        <div class="card">
            <h3>➕ بيع سلعة</h3>
            <input type="text" id="itemInput" placeholder="اسم السلعة">
            <input type="number" id="priceInput" placeholder="السعر">
            <button onclick="sellItem()">نشر في السوق</button>
        </div>
    </div>

    <h3>🛒 السوق</h3>
        <button onclick="sellItem()">نشر في السوق</button>
    </div>

    <h3>🛒 السوق</h3>
    <div id="market" class="card">
        {% for item in items %}
        <div class="item-card">
            <div>
                <b style="font-size:1.1rem">{{ item.item_name }}</b><br>
                <small style="color:gray">بائع: {{ item.seller_name }}</small>
                <div style="color: #a29bfe; font-weight:bold">{{ item.price }} ريال</div>
            </div>
            {% if item.seller_id|string != current_user_id|string %}
                <button class="buy-btn" onclick="buyItem('{{ loop.index0 }}', '{{ item.price }}')">شراء ❄️</button>
            {% else %}
                <small>سلعتك</small>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();
        let user = tg.initDataUnsafe.user;
        let userBalance = 0;

        // التحقق من أننا داخل Telegram Web App
        const isTelegramWebApp = tg.initData !== '';
        
        // عرض بيانات المستخدم
        if(user && user.id) {
            document.getElementById("userName").innerText = user.first_name + (user.last_name ? ' ' + user.last_name : '');
            document.getElementById("userId").innerText = user.id;
            
            // جلب الرصيد الحقيقي من السيرفر
            fetch('/get_balance?user_id=' + user.id)
                .then(r => r.json())
                .then(data => {
                    userBalance = data.balance;
                    document.getElementById("balance").innerText = userBalance;
                });
        }
        
        // دالة لفتح/إغلاق قسم حسابي
        function toggleAccount() {
            // إذا كان المستخدم في متصفح عادي (ليس Telegram Web App)
            if(!isTelegramWebApp) {
                // توجيهه لصفحة تسجيل الدخول المدمجة
                showLoginModal();
                return;
            }
            
            // إذا كان في Telegram، افتح/أغلق القسم
            const content = document.getElementById("accountContent");
            const arrow = document.getElementById("accountArrow");
            content.classList.toggle("open");
            arrow.classList.toggle("open");
        }
        
        // دالة لعرض نافذة تسجيل الدخول
        function showLoginModal() {
            const modal = document.getElementById('loginModal');
            modal.style.display = 'flex';
        }
        
        // دالة لإغلاق النافذة
        function closeLoginModal() {
            const modal = document.getElementById('loginModal');
            modal.style.display = 'none';
        }
        
        // دالة لفتح/إغلاق قسم إضافة سلعة
        function toggleSellSection() {
            const section = document.getElementById("sellSection");
            section.classList.toggle("open");
        }

        function sellItem() {
            let name = document.getElementById("itemInput").value;
            let price = document.getElementById("priceInput").value;
            if(!name || !price) return tg.showAlert("أدخل البيانات");

            fetch('/sell', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    seller_name: user.first_name,
                    seller_id: user.id,
                    item_name: name,
                    price: price
                })
            }).then(() => location.reload());
        }

        function buyItem(itemIndex, price) {
            if(userBalance < price) {
                tg.showAlert("❌ رصيدك غير كافي! اشحن محفظتك أولاً.");
                return;
            }

            tg.showConfirm("سيتم خصم المبلغ وحجزه حتى تستلم السلعة.\\nهل أنت متأكد؟", function(ok) {
                if(ok) {
                    fetch('/buy', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            buyer_id: user.id,
                            buyer_name: user.first_name,
                            item_index: itemIndex
                        })
                    }).then(r => r.json()).then(data => {
                        if(data.status == 'success') {
                            tg.close();
                        } else {
                            tg.showAlert(data.message);
                        }
                    });
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
    bot.reply_to(message, "أهلاً بك في السوق الآمن! 🛡️\n\n"
                          "📱 /web - للدخول للسوق\n"
                          "🆔 /my_id - لمعرفة الآيدي الخاص بك")

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
    bot.send_message(message.chat.id, 
                     f"🏪 **مرحباً بك في السوق!**\n\n"
                     f"افتح الرابط التالي في متصفحك لتصفح المنتجات:\n\n"
                     f"🔗 {SITE_URL}\n\n"
                     f"💡 **نصيحة:** انسخ الرابط وافتحه في متصفح خارجي (Chrome/Safari) "
                     f"للحصول على أفضل تجربة!",
                     parse_mode="Markdown")

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

# مسار استقبال بيانات الدخول من Telegram Widget
@app.route('/login_check')
def login_check():
    auth_data = request.args.to_dict()
    
    if check_telegram_authorization(auth_data):
        # تم التحقق بنجاح!
        user_id = auth_data['id']
        first_name = auth_data['first_name']
        photo_url = auth_data.get('photo_url', '') # الصورة الشخصية
        
        # تخزين الجلسة
        session['user_id'] = user_id
        session['first_name'] = first_name
        
        # جلب الرصيد
        balance = users_wallets.get(str(user_id), 0)
        
        return f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>تم تسجيل الدخول</title>
            <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap" rel="stylesheet">
            <style>
                body {{ font-family: 'Tajawal', sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }}
                .success-box {{ background: white; padding: 40px; border-radius: 20px; max-width: 500px; margin: 0 auto; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
                img {{ border-radius: 50%; margin: 20px 0; border: 4px solid #667eea; }}
                h1 {{ color: #00b894; }}
                .balance {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 15px; border-radius: 10px; margin: 20px 0; }}
                a {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; border-radius: 10px; text-decoration: none; margin-top: 20px; }}
                a:hover {{ background: #764ba2; }}
            </style>
        </head>
        <body>
            <div class="success-box">
                <h1>أهلاً بك يا {first_name}! ✅</h1>
                {f'<img src="{photo_url}" width="100">' if photo_url else ''}
                <h3>الآيدي الخاص بك: {user_id}</h3>
                <div class="balance">
                    💰 رصيدك الحالي: {balance} ريال
                </div>
                <p>تم تسجيل دخولك بنجاح وربط حسابك.</p>
                <a href="/">الذهاب للسوق 🏪</a>
            </div>
        </body>
        </html>
        """
    else:
        return """
        <center style="padding: 50px; font-family: Arial;">
            <h1>❌ فشل التحقق من البيانات!</h1>
            <p>البيانات غير صحيحة أو منتهية الصلاحية</p>
            <a href="/login">حاول مرة أخرى</a>
        </center>
        """

@app.route('/')
def index():
    return render_template_string(HTML_PAGE, items=marketplace_items, balance=0, current_user_id=0)

@app.route('/get_balance')
def get_balance_api():
    user_id = request.args.get('user_id')
    balance = get_balance(user_id)
    return {'balance': balance}

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
