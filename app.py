#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import telebot
from telebot import types
from flask import Flask, request, render_template_string, redirect, session
import json
import random
import hashlib
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

# رموز التحقق للمستخدمين
# الشكل: { user_id: {code, name, created_at} }
verification_codes = {}

# --- دوال مساعدة ---
def get_balance(user_id):
    return users_wallets.get(str(user_id), 0.0)

def add_balance(user_id, amount):
    uid = str(user_id)
    if uid not in users_wallets:
        users_wallets[uid] = 0.0
    users_wallets[uid] += float(amount)

# دالة لتوليد كود تحقق عشوائي
def generate_verification_code(user_id, user_name):
    # توليد كود من 6 أرقام
    code = str(random.randint(100000, 999999))
    
    # حفظ الكود (صالح لمدة 10 دقائق)
    verification_codes[str(user_id)] = {
        'code': code,
        'name': user_name,
        'created_at': time.time()
    }
    
    return code

# دالة للتحقق من صحة الكود
def verify_code(user_id, code):
    user_id = str(user_id)
    
    if user_id not in verification_codes:
        return None
    
    code_data = verification_codes[user_id]
    
    # التحقق من صلاحية الكود (10 دقائق)
    if time.time() - code_data['created_at'] > 600:  # 10 * 60 ثانية
        del verification_codes[user_id]
        return None
    
    # التحقق من تطابق الكود
    if code_data['code'] != code:
        return None
    
    return code_data

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
        
        .logout-btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #e74c3c, #c0392b);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 15px;
            font-family: 'Tajawal', sans-serif;
            transition: all 0.3s;
        }
        .logout-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(231, 76, 60, 0.4);
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
        .login-input {
            width: 100%;
            padding: 15px;
            margin: 10px 0;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            font-size: 16px;
            box-sizing: border-box;
            font-family: 'Tajawal', sans-serif;
        }
        .login-input:focus {
            outline: none;
            border-color: #6c5ce7;
        }
        .login-btn {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
            font-family: 'Tajawal', sans-serif;
        }
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(108, 92, 231, 0.4);
        }
        .help-text {
            color: #636e72;
            font-size: 14px;
            margin-top: 15px;
        }
        .help-text a {
            color: #6c5ce7;
            text-decoration: none;
        }
        .error-message {
            color: #e74c3c;
            background: #ffe5e5;
            padding: 10px;
            border-radius: 8px;
            margin: 10px 0;
            display: none;
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
            <p class="modal-text">أدخل معرف تيليجرام الخاص بك والكود الذي ستحصل عليه من البوت</p>
            
            <div id="errorMessage" class="error-message"></div>
            
            <input type="text" id="telegramId" class="login-input" placeholder="معرف تيليجرام (Telegram ID)">
            <input type="text" id="verificationCode" class="login-input" placeholder="كود التحقق (من البوت)" maxlength="6">
            
            <button class="login-btn" onclick="submitLogin()">تسجيل الدخول</button>
            
            <p class="help-text">
                ليس لديك كود؟ <a href="#" onclick="showCodeHelp(); return false;">احصل على كود من البوت</a>
            </p>
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
            
            <button class="logout-btn" onclick="logout()">🚪 تسجيل الخروج</button>
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
        let userBalance = {{ balance }};
        let currentUserId = {{ current_user_id }};

        // التحقق من أننا داخل Telegram Web App
        const isTelegramWebApp = tg.initData !== '';
        
        // عرض بيانات المستخدم
        if(user && user.id) {
            // مستخدم Telegram Web App
            document.getElementById("userName").innerText = user.first_name + (user.last_name ? ' ' + user.last_name : '');
            document.getElementById("userId").innerText = user.id;
            currentUserId = user.id;
            
            // جلب الرصيد الحقيقي من السيرفر
            fetch('/get_balance?user_id=' + user.id)
                .then(r => r.json())
                .then(data => {
                    userBalance = data.balance;
                    document.getElementById("balance").innerText = userBalance;
                });
        } else if(currentUserId && currentUserId != 0) {
            // مستخدم مسجل دخول عبر الرابط المؤقت أو الجلسة
            document.getElementById("userName").innerText = "{{ user_name }}";
            document.getElementById("userId").innerText = currentUserId;
            document.getElementById("balance").innerText = userBalance;
            
            // فتح قسم الحساب تلقائياً
            const content = document.getElementById("accountContent");
            const arrow = document.getElementById("accountArrow");
            content.classList.add("open");
            arrow.classList.add("open");
        }
        
        // دالة لفتح/إغلاق قسم حسابي
        function toggleAccount() {
            // إذا كان المستخدم في متصفح عادي وغير مسجل دخول
            if(!isTelegramWebApp && (!currentUserId || currentUserId == 0)) {
                // توجيهه لصفحة تسجيل الدخول المدمجة
                showLoginModal();
                return;
            }
            
            // إذا كان مسجل دخول، افتح/أغلق القسم
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
            document.getElementById('errorMessage').style.display = 'none';
            document.getElementById('telegramId').value = '';
            document.getElementById('verificationCode').value = '';
        }
        
        // دالة لإرسال بيانات تسجيل الدخول
        async function submitLogin() {
            const userId = document.getElementById('telegramId').value.trim();
            const code = document.getElementById('verificationCode').value.trim();
            const errorDiv = document.getElementById('errorMessage');
            
            // التحقق من إدخال البيانات
            if(!userId || !code) {
                errorDiv.textContent = 'الرجاء إدخال الآيدي والكود';
                errorDiv.style.display = 'block';
                return;
            }
            
            try {
                const response = await fetch('/verify', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        user_id: userId,
                        code: code
                    })
                });
                
                const data = await response.json();
                
                if(data.success) {
                    // نجح تسجيل الدخول
                    closeLoginModal();
                    location.reload(); // إعادة تحميل الصفحة لعرض البيانات
                } else {
                    errorDiv.textContent = data.message;
                    errorDiv.style.display = 'block';
                }
            } catch(error) {
                errorDiv.textContent = 'حدث خطأ! حاول مرة أخرى';
                errorDiv.style.display = 'block';
            }
        }
        
        // دالة لعرض مساعدة الحصول على الكود
        function showCodeHelp() {
            alert('للحصول على كود التحقق:\\n\\n1️⃣ افتح البوت في تيليجرام\\n2️⃣ أرسل الأمر /code\\n3️⃣ انسخ الكود المكون من 6 أرقام\\n4️⃣ الصقه في الحقل أعلاه');
        }
        
        // دالة لتسجيل الخروج
        async function logout() {
            if(confirm('هل تريد تسجيل الخروج؟')) {
                try {
                    await fetch('/logout', {method: 'POST'});
                    location.reload();
                } catch(error) {
                    location.reload();
                }
            }
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
    # إنشاء لوحة أزرار تفاعلية
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # الأزرار
    btn_code = types.KeyboardButton("🔐 كود الدخول")
    btn_web = types.KeyboardButton("🏪 افتح السوق")
    btn_myid = types.KeyboardButton("🆔 معرفي")
    
    # إضافة الأزرار
    markup.add(btn_code, btn_web)
    markup.add(btn_myid)
    
    # رسالة الترحيب
    bot.send_message(
        message.chat.id,
        "🌟 **أهلاً بك في السوق الآمن!** 🛡️\n\n"
        "منصة آمنة للبيع والشراء مع نظام حماية الأموال ❄️\n\n"
        "📌 **اختر من الأزرار أدناه:**",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# معالج الرسائل النصية (الأزرار)
@bot.message_handler(func=lambda message: message.text in [
    "🔐 كود الدخول", "🏪 افتح السوق", "🆔 معرفي"
])
def handle_buttons(message):
    if message.text == "🔐 كود الدخول":
        get_verification_code(message)
    
    elif message.text == "🏪 افتح السوق":
        open_web_app(message)
    
    elif message.text == "🆔 معرفي":
        my_id(message)

@bot.message_handler(commands=['my_id'])
def my_id(message):
    bot.reply_to(message, f"الآيدي الخاص بك: `{message.from_user.id}`", parse_mode="Markdown")

@bot.message_handler(commands=['code'])
def get_verification_code(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    if message.from_user.last_name:
        user_name += ' ' + message.from_user.last_name
    
    # توليد كود تحقق
    code = generate_verification_code(user_id, user_name)
    
    bot.send_message(message.chat.id,
                     f"🔐 **كود التحقق الخاص بك:**\n\n"
                     f"`{code}`\n\n"
                     f"⏱️ **صالح لمدة 10 دقائق**\n\n"
                     f"💡 **خطوات الدخول:**\n"
                     f"1️⃣ افتح الموقع في المتصفح\n"
                     f"2️⃣ اضغط على زر 'حسابي'\n"
                     f"3️⃣ أدخل الآيدي الخاص بك: `{user_id}`\n"
                     f"4️⃣ أدخل الكود أعلاه\n\n"
                     f"⚠️ لا تشارك هذا الكود مع أحد!",
                     parse_mode="Markdown")

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

# مسار تسجيل الخروج
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return {'success': True}

# مسار التحقق من الكود وتسجيل الدخول
@app.route('/verify', methods=['POST'])
def verify_login():
    data = request.get_json()
    user_id = data.get('user_id')
    code = data.get('code')
    
    if not user_id or not code:
        return {'success': False, 'message': 'الرجاء إدخال الآيدي والكود'}
    
    # التحقق من صحة الكود
    code_data = verify_code(user_id, code)
    
    if not code_data:
        return {'success': False, 'message': 'الكود غير صحيح أو منتهي الصلاحية'}
    
    # تسجيل دخول المستخدم
    session['user_id'] = user_id
    session['user_name'] = code_data['name']
    
    # حذف الكود بعد الاستخدام
    del verification_codes[str(user_id)]
    
    # جلب الرصيد
    balance = get_balance(user_id)
    
    return {
        'success': True,
        'message': 'تم تسجيل الدخول بنجاح',
        'user_name': code_data['name'],
        'balance': balance
    }

@app.route('/')
def index():
    # التحقق من وجود جلسة مسجلة
    user_id = session.get('user_id')
    user_name = session.get('user_name', session.get('first_name', 'ضيف'))
    
    # إذا كان المستخدم مسجل دخول، جلب رصيده
    balance = 0
    if user_id:
        balance = get_balance(user_id)
    
    return render_template_string(HTML_PAGE, 
                                   items=marketplace_items, 
                                   balance=balance, 
                                   current_user_id=user_id or 0,
                                   user_name=user_name)

@app.route('/get_balance')
def get_balance_api():
    # محاولة الحصول على user_id من الطلب أو من الجلسة
    user_id = request.args.get('user_id') or session.get('user_id')
    
    if not user_id:
        return {'balance': 0}
    
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
