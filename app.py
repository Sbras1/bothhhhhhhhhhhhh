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

# قائمة المشرفين (آيدي تيليجرام)
# يتم إرسال الطلبات لهم مباشرة في الخاص
# يمكن إضافة حتى 10 مشرفين
ADMINS_LIST = [
    5665438577,  # المشرف 1
    # أضف المزيد من المشرفين هنا (حتى 10)
    # 123456789,  # المشرف 2
    # 987654321,  # المشرف 3
]

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-here-change-it")

# --- قواعد البيانات (في الذاكرة حالياً) ---
# ملاحظة: هذه البيانات ستمسح عند إعادة تشغيل السيرفر.

# قائمة المنتجات/الخدمات
# الشكل: { item_name, price, seller_id, seller_name, hidden_data, image_url, category }
marketplace_items = []

# الطلبات النشطة (قيد التنفيذ بواسطة المشرفين)
# الشكل: { order_id: {buyer_info, item_info, admin_id, status, message_id} }
active_orders = {}

# قائمة المشرفين الديناميكية (يتم تحديثها عبر الأوامر)
# تبدأ بالقيمة الأساسية من ADMINS_LIST
admins_database = ADMINS_LIST.copy()

# بيانات المستخدمين (الرصيد)
# الشكل: { user_id: balance }
users_wallets = {}

# العمليات المعلقة (المبالغ المحجوزة)
transactions = {}

# رموز التحقق للمستخدمين
# الشكل: { user_id: {code, name, created_at} }
verification_codes = {}

# مفاتيح الشحن المولدة
# الشكل: { key_code: {amount, used, used_by, created_at} }
charge_keys = {}

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
        
        /* تصميم بطاقات المنتجات الجديد */
        .product-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
            margin-top: 16px;
        }
        @media (min-width: 600px) {
            .product-grid {
                grid-template-columns: repeat(3, 1fr);
            }
        }
        .product-card {
            background: var(--card-bg);
            border-radius: 16px;
            overflow: hidden;
            position: relative;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            transition: transform 0.3s, box-shadow 0.3s;
            display: flex;
            flex-direction: column;
        }
        .product-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.3);
        }
        .product-image {
            width: 100%;
            height: 140px;
            object-fit: cover;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 50px;
        }
        .product-image img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .product-badge {
            position: absolute;
            top: 8px;
            right: 8px;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 11px;
            font-weight: bold;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        }
        .product-info {
            padding: 12px;
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .product-category {
            color: #a29bfe;
            font-size: 11px;
            font-weight: 500;
            margin-bottom: 6px;
            display: inline-block;
            background: rgba(162, 155, 254, 0.2);
            padding: 3px 8px;
            border-radius: 10px;
            align-self: flex-start;
        }
        .product-name {
            font-size: 15px;
            font-weight: bold;
            margin-bottom: 6px;
            color: var(--text-color);
            line-height: 1.3;
        }
        .product-seller {
            color: #888;
            font-size: 11px;
            margin-bottom: 10px;
        }
        .product-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: auto;
            padding-top: 10px;
            border-top: 1px solid #444;
        }
        .product-price {
            font-size: 17px;
            font-weight: bold;
            color: #00b894;
        }
        .product-buy-btn {
            background: linear-gradient(135deg, #00b894, #00cec9);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 15px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 2px 6px rgba(0, 184, 148, 0.3);
            font-size: 13px;
        }
        .product-buy-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 4px 10px rgba(0, 184, 148, 0.5);
        }
        .my-product-badge {
            background: linear-gradient(135deg, #fdcb6e, #e17055);
            padding: 6px 12px;
            border-radius: 15px;
            font-size: 11px;
            font-weight: bold;
        }
        
        /* المنتجات المباعة */
        .sold-product {
            opacity: 0.7;
            position: relative;
        }
        .sold-product .product-image::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.4);
        }
        .sold-ribbon {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(-25deg);
            background: linear-gradient(135deg, #e74c3c, #c0392b);
            color: white;
            padding: 10px 40px;
            font-size: 20px;
            font-weight: bold;
            z-index: 10;
            box-shadow: 0 4px 15px rgba(231, 76, 60, 0.6);
            border: 3px solid white;
            letter-spacing: 2px;
        }
        .sold-info {
            color: #e74c3c;
            font-size: 11px;
            font-weight: bold;
            margin: 8px 0;
            padding: 6px 10px;
            background: rgba(231, 76, 60, 0.1);
            border-radius: 8px;
            border-left: 3px solid #e74c3c;
        }
        
        /* حاوية الفئات - الشبكة */
        .categories-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            padding: 5px;
            margin-bottom: 20px;
        }

        /* كرت الفئة */
        .cat-card {
            position: relative;
            border-radius: 12px;
            padding: 15px 5px;
            cursor: pointer;
            text-align: center;
            background: #2d2d2d;
            border: 1px solid rgba(255, 255, 255, 0.05);
            transition: transform 0.2s;
            height: 100px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }

        .cat-card:active {
            transform: scale(0.95);
        }

        /* الألوان الخلفية (تدرجات خفيفة) */
        .bg-all { background: linear-gradient(180deg, #2d2d2d 0%, #3a2d44 100%); border-bottom: 2px solid #6c5ce7; }
        .bg-netflix { background: linear-gradient(180deg, #2d2d2d 0%, #3a1a1a 100%); border-bottom: 2px solid #e50914; }
        .bg-shahid { background: linear-gradient(180deg, #2d2d2d 0%, #2a3a3a 100%); border-bottom: 2px solid #00b8a9; }
        .bg-disney { background: linear-gradient(180deg, #2d2d2d 0%, #1a2a44 100%); border-bottom: 2px solid #0063e5; }
        .bg-osn { background: linear-gradient(180deg, #2d2d2d 0%, #3a2a1a 100%); border-bottom: 2px solid #f39c12; }
        .bg-video { background: linear-gradient(180deg, #2d2d2d 0%, #2a1a3a 100%); border-bottom: 2px solid #9b59b6; }
        .bg-other { background: linear-gradient(180deg, #2d2d2d 0%, #442a2a 100%); border-bottom: 2px solid #e17055; }

        /* الأيقونة */
        .cat-icon {
            font-size: 28px;
            margin-bottom: 8px;
            width: 40px;
            height: 40px;
            object-fit: contain;
        }
        
        .cat-icon.emoji {
            font-size: 28px;
            width: auto;
            height: auto;
        }

        /* العنوان */
        .cat-title {
            color: #fff;
            font-size: 13px;
            font-weight: bold;
            white-space: nowrap;
        }
        
        .categories-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0 10px;
            margin-bottom: 10px;
        }
        
        .categories-header h3 {
            margin: 0;
        }
        
        .categories-header small {
            color: #6c5ce7;
            cursor: pointer;
        }
        
        /* زر حسابي */
        .account-btn {
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            color: white;
            padding: 10px 16px;
            border-radius: 12px;
            margin-bottom: 16px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 15px rgba(108, 92, 231, 0.3);
            transition: all 0.3s;
            max-width: 180px;
            margin-left: auto;
        }
        .account-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(108, 92, 231, 0.4);
        }
        .account-btn-left {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: bold;
        }
        .account-icon {
            font-size: 18px;
        }
        .arrow {
            transition: transform 0.3s;
            font-size: 12px;
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
        
        /* زر الطلبات */
        .orders-btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 15px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 12px;
            font-family: 'Tajawal', sans-serif;
            transition: all 0.3s;
        }
        .orders-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(108, 92, 231, 0.4);
        }
        
        /* قسم الطلبات */
        .orders-section {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
            background: var(--card-bg);
            border-radius: 16px;
            margin-bottom: 20px;
        }
        .orders-section.open {
            max-height: 800px;
            overflow-y: auto;
        }
        .orders-header {
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            padding: 15px 20px;
            border-radius: 16px 16px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: white;
        }
        .orders-header h3 {
            margin: 0;
            font-size: 18px;
        }
        .close-orders {
            font-size: 24px;
            cursor: pointer;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: rgba(255,255,255,0.2);
        }
        .orders-list {
            padding: 20px;
        }
        .order-item {
            background: rgba(108, 92, 231, 0.1);
            border: 2px solid rgba(108, 92, 231, 0.3);
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        .order-item:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(108, 92, 231, 0.2);
        }
        .order-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            font-weight: bold;
        }
        .order-id {
            color: #6c5ce7;
            font-size: 14px;
        }
        .order-status {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
        }
        .order-status.pending {
            background: #f39c12;
            color: white;
        }
        .order-status.completed {
            background: #27ae60;
            color: white;
        }
        .order-status.claimed {
            background: #3498db;
            color: white;
        }
        .order-info {
            font-size: 14px;
            line-height: 1.8;
        }
        .order-info strong {
            color: var(--text-color);
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
            
            <button class="orders-btn" onclick="toggleOrders()">📦 طلباتي</button>
            
            <button class="logout-btn" onclick="logout()">🚪 تسجيل الخروج</button>
        </div>
    </div>
    
    <!-- قسم الطلبات -->
    <div class="orders-section" id="ordersSection">
        <div class="orders-header">
            <h3>📦 طلباتي</h3>
            <span class="close-orders" onclick="toggleOrders()">✕</span>
        </div>
        <div class="orders-list" id="ordersList">
            <p style="text-align:center; color:#888;">جاري التحميل...</p>
        </div>
    </div>

    <div class="categories-header">
        <h3>💎 الأقسام</h3>
        <small onclick="filterCategory('all')">عرض الكل</small>
    </div>

    <div class="categories-grid">
        <div class="cat-card bg-netflix" onclick="filterCategory('نتفلكس')">
            <img class="cat-icon" src="https://cdn-icons-png.flaticon.com/512/732/732228.png" alt="نتفلكس">
            <div class="cat-title">نتفلكس</div>
        </div>
        
        <div class="cat-card bg-shahid" onclick="filterCategory('شاهد')">
            <img class="cat-icon" src="https://cdn-icons-png.flaticon.com/512/3845/3845874.png" alt="شاهد">
            <div class="cat-title">شاهد</div>
        </div>

        <div class="cat-card bg-disney" onclick="filterCategory('ديزني بلس')">
            <img class="cat-icon" src="https://cdn-icons-png.flaticon.com/512/5977/5977590.png" alt="ديزني بلس">
            <div class="cat-title">ديزني بلس</div>
        </div>
        
        <div class="cat-card bg-osn" onclick="filterCategory('اوسن بلس')">
            <img class="cat-icon" src="https://cdn-icons-png.flaticon.com/512/1946/1946488.png" alt="اوسن بلس">
            <div class="cat-title">اوسن بلس</div>
        </div>
        
        <div class="cat-card bg-video" onclick="filterCategory('فديو بريميم')">
            <img class="cat-icon" src="https://cdn-icons-png.flaticon.com/512/3074/3074767.png" alt="فديو بريميم">
            <div class="cat-title">فديو بريميم</div>
        </div>
        
        <div class="cat-card bg-other" onclick="filterCategory('اشتراكات أخرى')">
            <img class="cat-icon" src="https://cdn-icons-png.flaticon.com/512/2087/2087815.png" alt="اشتراكات أخرى">
            <div class="cat-title">اشتراكات أخرى</div>
        </div>
    </div>

    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
        <h3 style="margin: 0;">🛒 السوق</h3>
        <span id="categoryFilter" style="color: #6c5ce7; font-size: 14px; font-weight: bold;"></span>
    </div>
    <div id="market" class="product-grid">
        {% for item in items %}
        <div class="product-card {% if item.get('sold') %}sold-product{% endif %}">
            {% if item.get('sold') %}
            <div class="sold-ribbon">مباع ✓</div>
            {% endif %}
            <div class="product-image">
                {% if item.get('image_url') %}
                <img src="{{ item.image_url }}" alt="{{ item.item_name }}">
                {% else %}
                🎁
                {% endif %}
            </div>
            {% if item.get('category') %}
            <div class="product-badge">{{ item.category }}</div>
            {% endif %}
            <div class="product-info">
                {% if item.get('category') %}
                <span class="product-category">{{ item.category }}</span>
                {% endif %}
                <div class="product-name">{{ item.item_name }}</div>
                <div class="product-seller">🏪 {{ item.seller_name }}</div>
                {% if item.get('sold') and item.get('buyer_name') %}
                <div class="sold-info">🎉 تم شراءه بواسطة: {{ item.buyer_name }}</div>
                {% endif %}
                <div class="product-footer">
                    <div class="product-price">{{ item.price }} ريال</div>
                    {% if item.get('sold') %}
                        <button class="product-buy-btn" disabled style="opacity: 0.5; cursor: not-allowed;">مباع 🚫</button>
                    {% elif item.seller_id|string != current_user_id|string %}
                        <button class="product-buy-btn" onclick="buyItem('{{ loop.index0 }}', '{{ item.price }}', '{{ item.item_name }}')">شراء 🛒</button>
                    {% else %}
                        <div class="my-product-badge">منتجك ⭐</div>
                    {% endif %}
                </div>
            </div>
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
        
        // دالة لفتح/إغلاق قسم الطلبات
        async function toggleOrders() {
            const ordersSection = document.getElementById('ordersSection');
            const isOpen = ordersSection.classList.toggle('open');
            
            if(isOpen) {
                // جلب الطلبات من السيرفر
                await loadOrders();
            }
        }
        
        // دالة لجلب وعرض الطلبات
        async function loadOrders() {
            const ordersList = document.getElementById('ordersList');
            ordersList.innerHTML = '<p style="text-align:center; color:#888;">جاري التحميل...</p>';
            
            try {
                const response = await fetch(`/get_orders?user_id=${currentUserId}`);
                const data = await response.json();
                
                if(data.orders && data.orders.length > 0) {
                    ordersList.innerHTML = '';
                    data.orders.forEach(order => {
                        const statusText = order.status === 'pending' ? 'قيد الانتظار' : 
                                          order.status === 'claimed' ? 'قيد المعالجة' : 'مكتمل';
                        const statusClass = order.status;
                        
                        const orderHTML = `
                            <div class="order-item">
                                <div class="order-header">
                                    <span class="order-id">#${order.order_id}</span>
                                    <span class="order-status ${statusClass}">${statusText}</span>
                                </div>
                                <div class="order-info">
                                    <div>📦 <strong>المنتج:</strong> ${order.item_name}</div>
                                    <div>💰 <strong>السعر:</strong> ${order.price} ريال</div>
                                    ${order.game_id ? `<div>🎮 <strong>معرف اللعبة:</strong> ${order.game_id}</div>` : ''}
                                    ${order.game_name ? `<div>👤 <strong>اسم اللعبة:</strong> ${order.game_name}</div>` : ''}
                                    ${order.admin_name ? `<div>👨‍💼 <strong>المشرف:</strong> ${order.admin_name}</div>` : ''}
                                </div>
                            </div>
                        `;
                        ordersList.innerHTML += orderHTML;
                    });
                } else {
                    ordersList.innerHTML = '<p style="text-align:center; color:#888;">📭 لا توجد طلبات حتى الآن</p>';
                }
            } catch(error) {
                ordersList.innerHTML = '<p style="text-align:center; color:#e74c3c;">❌ حدث خطأ في تحميل الطلبات</p>';
            }
        }
        
        // تصفية المنتجات حسب الفئة
        let allItems = {{ items|tojson }};
        
        function filterCategory(category) {
            // تحديث نص الفئة
            const categoryFilterText = document.getElementById('categoryFilter');
            if(category === 'all') {
                categoryFilterText.textContent = '';
            } else {
                categoryFilterText.textContent = `- ${category}`;
            }
            
            // تصفية وعرض المنتجات
            const market = document.getElementById('market');
            market.innerHTML = '';
            
            let filteredItems = category === 'all' ? allItems : allItems.filter(item => item.category === category);
            
            // ترتيب المنتجات: المتاحة أولاً، ثم المباعة
            filteredItems.sort((a, b) => {
                if(a.sold && !b.sold) return 1;
                if(!a.sold && b.sold) return -1;
                return 0;
            });
            
            if(filteredItems.length === 0) {
                market.innerHTML = '<p style="text-align:center; color:#888; grid-column: 1/-1; padding: 40px;">📭 لا توجد منتجات في هذا القسم</p>';
                return;
            }
            
            filteredItems.forEach((item, index) => {
                const isMyProduct = item.seller_id == currentUserId;
                const isSold = item.sold === true;
                const productHTML = `
                    <div class="product-card ${isSold ? 'sold-product' : ''}">
                        ${isSold ? '<div class="sold-ribbon">مباع ✓</div>' : ''}
                        <div class="product-image">
                            ${item.image_url ? `<img src="${item.image_url}" alt="${item.item_name}">` : '🎁'}
                        </div>
                        ${item.category ? `<div class="product-badge">${item.category}</div>` : ''}
                        <div class="product-info">
                            ${item.category ? `<span class="product-category">${item.category}</span>` : ''}
                            <div class="product-name">${item.item_name}</div>
                            <div class="product-seller">🏪 ${item.seller_name}</div>
                            ${isSold && item.buyer_name ? `<div class="sold-info">🎉 تم شراءه بواسطة: ${item.buyer_name}</div>` : ''}
                            <div class="product-footer">
                                <div class="product-price">${item.price} ريال</div>
                                ${isSold ? 
                                    `<button class="product-buy-btn" disabled style="opacity: 0.5; cursor: not-allowed;">مباع 🚫</button>` :
                                    (!isMyProduct ? 
                                        `<button class="product-buy-btn" onclick="buyItem('${allItems.indexOf(item)}', '${item.price}', '${item.item_name}')">شراء 🛒</button>` : 
                                        `<div class="my-product-badge">منتجك ⭐</div>`)
                                }
                            </div>
                        </div>
                    </div>
                `;
                market.innerHTML += productHTML;
            });
        }

        function buyItem(itemIndex, price, itemName) {
            // التحقق من الرصيد أولاً
            if(userBalance < price) {
                alert("❌ رصيدك غير كافي! اشحن محفظتك أولاً.");
                return;
            }

            // تأكيد الشراء المباشر
            const confirmMsg = `هل تريد شراء: ${itemName}\nالسعر: ${price} ريال\n\n✅ سيتم تسليم الحساب فوراً!`;
            
            if(!confirm(confirmMsg)) {
                return;
            }

            // تحديد بيانات المشتري
            let buyerId = currentUserId;
            let buyerName = '{{ user_name }}';
            
            if(user && user.id) {
                buyerId = user.id;
                buyerName = user.first_name + (user.last_name ? ' ' + user.last_name : '');
            }

            if(!buyerId || buyerId == 0) {
                alert("الرجاء تسجيل الدخول أولاً!");
                return;
            }

            fetch('/buy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    buyer_id: buyerId,
                    buyer_name: buyerName,
                    item_index: itemIndex
                })
            }).then(r => r.json()).then(data => {
                if(data.status == 'success') {
                    alert('✅ تم الشراء بنجاح! تحقق من رسائل البوت لاستلام البيانات.');
                    location.reload();
                } else {
                    alert('❌ ' + data.message);
                }
            });
        }
        
        // تحميل أول قسم (نتفلكس) عند فتح الصفحة
        window.addEventListener('DOMContentLoaded', function() {
            filterCategory('نتفلكس');
        });
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
    bot.reply_to(message, f"الآيدي الخاص بك: {message.from_user.id}\n\nأرسل هذا الرقم للمالك ليضيفك كمشرف!")

# أمر إضافة مشرف (فقط للمالك)
@bot.message_handler(commands=['add_admin'])
def add_admin_command(message):
    # التحقق من أن المستخدم هو المالك
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    try:
        # الأمر: /add_admin ID
        parts = message.text.split()
        if len(parts) < 2:
            return bot.reply_to(message, "⚠️ الاستخدام الصحيح:\n/add_admin الآيدي\n\nمثال: /add_admin 123456789")
        
        new_admin_id = int(parts[1])
        
        # التحقق من عدم وجوده مسبقاً
        if new_admin_id in admins_database:
            return bot.reply_to(message, f"⚠️ المشرف {new_admin_id} موجود مسبقاً في القائمة!")
        
        # التحقق من عدد المشرفين (حد أقصى 10)
        if len(admins_database) >= 10:
            return bot.reply_to(message, "❌ لا يمكن إضافة أكثر من 10 مشرفين!")
        
        # إضافة المشرف
        admins_database.append(new_admin_id)
        
        # إشعار المالك
        bot.reply_to(message, 
                     f"✅ تم إضافة مشرف جديد!\n\n"
                     f"🆔 الآيدي: {new_admin_id}\n"
                     f"👥 عدد المشرفين: {len(admins_database)}/10")
        
        # إشعار المشرف الجديد
        try:
            bot.send_message(
                new_admin_id,
                "🎉 مبروك! تمت إضافتك كمشرف!\n\n"
                "✅ ستصلك الطلبات الجديدة مباشرة على الخاص."
            )
        except:
            pass
            
    except ValueError:
        bot.reply_to(message, "❌ الآيدي غير صحيح! يجب أن يكون رقماً.")
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {str(e)}")

# أمر حذف مشرف (فقط للمالك)
@bot.message_handler(commands=['remove_admin'])
def remove_admin_command(message):
    # التحقق من أن المستخدم هو المالك
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    try:
        # الأمر: /remove_admin ID
        parts = message.text.split()
        if len(parts) < 2:
            return bot.reply_to(message, "⚠️ الاستخدام الصحيح:\n/remove_admin الآيدي\n\nمثال: /remove_admin 123456789")
        
        admin_to_remove = int(parts[1])
        
        # التحقق من وجوده في القائمة
        if admin_to_remove not in admins_database:
            return bot.reply_to(message, f"❌ المشرف {admin_to_remove} غير موجود في القائمة!")
        
        # منع حذف المالك
        if admin_to_remove == ADMIN_ID:
            return bot.reply_to(message, "⛔ لا يمكن حذف المالك!")
        
        # حذف المشرف
        admins_database.remove(admin_to_remove)
        
        bot.reply_to(message, 
                     f"✅ تم حذف المشرف!\n\n"
                     f"🆔 الآيدي: {admin_to_remove}\n"
                     f"👥 عدد المشرفين: {len(admins_database)}/10")
        
        # إشعار المشرف المحذوف
        try:
            bot.send_message(
                admin_to_remove,
                "⚠️ تم إزالتك من قائمة المشرفين.\n"
                "لن تصلك الطلبات بعد الآن."
            )
        except:
            pass
            
    except ValueError:
        bot.reply_to(message, "❌ الآيدي غير صحيح! يجب أن يكون رقماً.")
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {str(e)}")

# أمر عرض قائمة المشرفين (فقط للمالك)
@bot.message_handler(commands=['list_admins'])
def list_admins_command(message):
    # التحقق من أن المستخدم هو المالك
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    if not admins_database:
        return bot.reply_to(message, "⚠️ لا يوجد مشرفين حالياً!")
    
    admins_list_text = f"👥 قائمة المشرفين ({len(admins_database)}/10):\n\n"
    
    for i, admin_id in enumerate(admins_database, 1):
        owner_badge = " 👑" if admin_id == ADMIN_ID else ""
        admins_list_text += f"{i}. {admin_id}{owner_badge}\n"
    
    bot.reply_to(message, admins_list_text)

# تخزين بيانات المنتج المؤقتة
temp_product_data = {}

# أمر إضافة منتج (فقط للمالك)
@bot.message_handler(commands=['add_product'])
def add_product_command(message):
    # التحقق من أن المستخدم هو المالك
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    # بدء عملية إضافة منتج جديد
    user_id = message.from_user.id
    temp_product_data[user_id] = {}
    
    msg = bot.reply_to(message, "📦 **إضافة منتج جديد**\n\n📝 أرسل اسم المنتج:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_product_name)

def process_product_name(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    temp_product_data[user_id]['item_name'] = message.text.strip()
    bot.reply_to(message, f"✅ تم إضافة الاسم: {message.text.strip()}")
    
    msg = bot.send_message(message.chat.id, "💰 أرسل سعر المنتج (بالريال):")
    bot.register_next_step_handler(msg, process_product_price)

def process_product_price(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    # التحقق من السعر
    try:
        price = float(message.text.strip())
        temp_product_data[user_id]['price'] = str(price)
        bot.reply_to(message, f"✅ تم إضافة السعر: {price} ريال")
        
        # إرسال أزرار الفئات
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
        markup.add(
            types.KeyboardButton("نتفلكس"),
            types.KeyboardButton("شاهد"),
            types.KeyboardButton("ديزني بلس"),
            types.KeyboardButton("اوسن بلس"),
            types.KeyboardButton("فديو بريميم"),
            types.KeyboardButton("اشتراكات أخرى")
        )
        
        msg = bot.send_message(message.chat.id, "🏷️ اختر فئة المنتج:", reply_markup=markup)
        bot.register_next_step_handler(msg, process_product_category)
        
    except ValueError:
        msg = bot.reply_to(message, "❌ السعر يجب أن يكون رقماً! أرسل السعر مرة أخرى:")
        bot.register_next_step_handler(msg, process_product_price)

def process_product_category(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
    
    valid_categories = ["نتفلكس", "شاهد", "ديزني بلس", "اوسن بلس", "فديو بريميم", "اشتراكات أخرى"]
    
    if message.text.strip() not in valid_categories:
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
        markup.add(
            types.KeyboardButton("نتفلكس"),
            types.KeyboardButton("شاهد"),
            types.KeyboardButton("ديزني بلس"),
            types.KeyboardButton("اوسن بلس"),
            types.KeyboardButton("فديو بريميم"),
            types.KeyboardButton("اشتراكات أخرى")
        )
        msg = bot.reply_to(message, "❌ فئة غير صحيحة! اختر من الأزرار:", reply_markup=markup)
        return bot.register_next_step_handler(msg, process_product_category)
    
    temp_product_data[user_id]['category'] = message.text.strip()
    bot.reply_to(message, f"✅ تم اختيار الفئة: {message.text.strip()}", reply_markup=types.ReplyKeyboardRemove())
    
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton("تخطي"))
    
    msg = bot.send_message(message.chat.id, "🖼️ أرسل رابط صورة المنتج (أو اضغط تخطي):", reply_markup=markup)
    bot.register_next_step_handler(msg, process_product_image)

def process_product_image(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
    
    if message.text.strip() == "تخطي":
        temp_product_data[user_id]['image_url'] = "https://via.placeholder.com/300x200?text=No+Image"
        bot.reply_to(message, "⏭️ تم تخطي الصورة", reply_markup=types.ReplyKeyboardRemove())
    else:
        temp_product_data[user_id]['image_url'] = message.text.strip()
        bot.reply_to(message, "✅ تم إضافة رابط الصورة", reply_markup=types.ReplyKeyboardRemove())
    
    msg = bot.send_message(message.chat.id, "🔐 أرسل البيانات المخفية (الايميل والباسورد مثلاً):")
    bot.register_next_step_handler(msg, process_product_hidden_data)

def process_product_hidden_data(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    temp_product_data[user_id]['hidden_data'] = message.text.strip()
    bot.reply_to(message, "✅ تم إضافة البيانات المخفية")
    
    # عرض ملخص المنتج
    product = temp_product_data[user_id]
    summary = (
        "📦 **ملخص المنتج:**\n\n"
        f"📝 الاسم: {product['item_name']}\n"
        f"💰 السعر: {product['price']} ريال\n"
        f"🏷️ الفئة: {product['category']}\n"
        f"🖼️ الصورة: {product['image_url']}\n"
        f"🔐 البيانات: {product['hidden_data']}\n\n"
        "هل تريد إضافة هذا المنتج؟"
    )
    
    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("✅ موافق"),
        types.KeyboardButton("❌ إلغاء")
    )
    
    msg = bot.send_message(message.chat.id, summary, parse_mode="Markdown", reply_markup=markup)
    bot.register_next_step_handler(msg, confirm_add_product)

def confirm_add_product(message):
    user_id = message.from_user.id
    
    if message.text == "✅ موافق":
        product = temp_product_data.get(user_id)
        
        if product:
            # إضافة المنتج
            item = {
                'item_name': product['item_name'],
                'price': product['price'],
                'seller_id': str(ADMIN_ID),
                'seller_name': 'المالك',
                'hidden_data': product['hidden_data'],
                'category': product['category'],
                'image_url': product['image_url']
            }
            marketplace_items.append(item)
            
            bot.reply_to(message,
                         f"✅ **تم إضافة المنتج بنجاح!**\n\n"
                         f"📦 المنتج: {product['item_name']}\n"
                         f"💰 السعر: {product['price']} ريال\n"
                         f"🏷️ الفئة: {product['category']}\n"
                         f"📊 إجمالي المنتجات: {len(marketplace_items)}",
                         parse_mode="Markdown",
                         reply_markup=types.ReplyKeyboardRemove())
        
        # حذف البيانات المؤقتة
        temp_product_data.pop(user_id, None)
    else:
        bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
        temp_product_data.pop(user_id, None)

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

# أمر توليد مفاتيح الشحن
# الاستخدام: /توليد AMOUNT [COUNT]
# مثال: /توليد 50 10  (توليد 10 مفاتيح بقيمة 50 ريال لكل منها)
@bot.message_handler(commands=['توليد'])
def generate_keys(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    try:
        parts = message.text.split()
        amount = float(parts[1])
        count = int(parts[2]) if len(parts) > 2 else 1
        
        # التحقق من الحدود
        if count > 100:
            return bot.reply_to(message, "❌ الحد الأقصى 100 مفتاح في المرة الواحدة!")
        
        if amount <= 0:
            return bot.reply_to(message, "❌ المبلغ يجب أن يكون أكبر من صفر!")
        
        # توليد المفاتيح
        generated_keys = []
        for i in range(count):
            # توليد مفتاح عشوائي
            key_code = f"KEY-{random.randint(10000, 99999)}-{random.randint(1000, 9999)}"
            
            # حفظ المفتاح في قاعدة البيانات
            charge_keys[key_code] = {
                'amount': amount,
                'used': False,
                'used_by': None,
                'created_at': time.time()
            }
            generated_keys.append(key_code)
        
        # إرسال المفاتيح
        if count == 1:
            response = (
                f"🎁 **تم توليد المفتاح بنجاح!**\n\n"
                f"💰 القيمة: {amount} ريال\n"
                f"🔑 المفتاح:\n"
                f"`{generated_keys[0]}`\n\n"
                f"📝 يمكن للمستخدم شحنه بإرسال: /شحن {generated_keys[0]}"
            )
        else:
            keys_text = "\n".join([f"`{key}`" for key in generated_keys])
            response = (
                f"🎁 **تم توليد {count} مفتاح بنجاح!**\n\n"
                f"💰 قيمة كل مفتاح: {amount} ريال\n"
                f"💵 المجموع الكلي: {amount * count} ريال\n\n"
                f"🔑 المفاتيح:\n{keys_text}\n\n"
                f"📝 الاستخدام: /شحن [المفتاح]"
            )
        
        bot.reply_to(message, response, parse_mode="Markdown")
        
    except IndexError:
        bot.reply_to(message, 
                     "❌ **خطأ في الاستخدام!**\n\n"
                     "📝 الصيغة الصحيحة:\n"
                     "`/توليد [المبلغ] [العدد]`\n\n"
                     "**أمثلة:**\n"
                     "• `/توليد 50` - مفتاح واحد بقيمة 50 ريال\n"
                     "• `/توليد 100 5` - 5 مفاتيح بقيمة 100 ريال لكل منها\n"
                     "• `/توليد 25 10` - 10 مفاتيح بقيمة 25 ريال لكل منها",
                     parse_mode="Markdown")
    except ValueError:
        bot.reply_to(message, "❌ الرجاء إدخال أرقام صحيحة!")

# أمر شحن الرصيد بالمفتاح
@bot.message_handler(commands=['شحن'])
def charge_with_key(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return bot.reply_to(message,
                              "❌ **خطأ في الاستخدام!**\n\n"
                              "📝 الصيغة الصحيحة:\n"
                              "`/شحن [المفتاح]`\n\n"
                              "**مثال:**\n"
                              "`/شحن KEY-12345-6789`",
                              parse_mode="Markdown")
        
        key_code = parts[1].strip()
        user_id = str(message.from_user.id)
        user_name = message.from_user.first_name
        
        # التحقق من وجود المفتاح
        if key_code not in charge_keys:
            return bot.reply_to(message, "❌ المفتاح غير صحيح أو منتهي الصلاحية!")
        
        key_data = charge_keys[key_code]
        
        # التحقق من استخدام المفتاح
        if key_data['used']:
            return bot.reply_to(message, 
                              f"❌ هذا المفتاح تم استخدامه بالفعل!\n\n"
                              f"👤 استخدمه: {key_data.get('used_by', 'مستخدم')}")
        
        # شحن الرصيد
        amount = key_data['amount']
        add_balance(user_id, amount)
        
        # تحديث حالة المفتاح
        charge_keys[key_code]['used'] = True
        charge_keys[key_code]['used_by'] = user_name
        charge_keys[key_code]['used_at'] = time.time()
        
        # إرسال رسالة نجاح
        bot.reply_to(message,
                    f"✅ **تم شحن رصيدك بنجاح!**\n\n"
                    f"💰 المبلغ المضاف: {amount} ريال\n"
                    f"💵 رصيدك الحالي: {get_balance(user_id)} ريال\n\n"
                    f"🎉 استمتع بالتسوق!",
                    parse_mode="Markdown")
        
        # إشعار المالك
        try:
            bot.send_message(ADMIN_ID,
                           f"🔔 **تم استخدام مفتاح شحن**\n\n"
                           f"👤 المستخدم: {user_name}\n"
                           f"🆔 الآيدي: {user_id}\n"
                           f"💰 المبلغ: {amount} ريال\n"
                           f"🔑 المفتاح: `{key_code}`",
                           parse_mode="Markdown")
        except:
            pass
            
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {str(e)}")

# أمر عرض المفاتيح النشطة (للمالك فقط)
@bot.message_handler(commands=['المفاتيح'])
def list_keys(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    active_keys = [k for k, v in charge_keys.items() if not v['used']]
    used_keys = [k for k, v in charge_keys.items() if v['used']]
    
    if not charge_keys:
        return bot.reply_to(message, "📭 لا توجد مفاتيح محفوظة!")
    
    response = f"📊 **إحصائيات المفاتيح**\n\n"
    response += f"✅ مفاتيح نشطة: {len(active_keys)}\n"
    response += f"🚫 مفاتيح مستخدمة: {len(used_keys)}\n"
    response += f"📈 الإجمالي: {len(charge_keys)}\n\n"
    
    if active_keys:
        total_value = sum([charge_keys[k]['amount'] for k in active_keys])
        response += f"💰 القيمة الإجمالية للمفاتيح النشطة: {total_value} ريال"
    
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=['web'])
def open_web_app(message):
    bot.send_message(message.chat.id, 
                     f"🏪 **مرحباً بك في السوق!**\n\n"
                     f"افتح الرابط التالي في متصفحك لتصفح المنتجات:\n\n"
                     f"🔗 {SITE_URL}\n\n"
                     f"💡 **نصيحة:** انسخ الرابط وافتحه في متصفح خارجي (Chrome/Safari) "
                     f"للحصول على أفضل تجربة!",
                     parse_mode="Markdown")

# زر استلام الطلب من قبل المشرف
@bot.callback_query_handler(func=lambda call: call.data.startswith('claim_'))
def claim_order(call):
    order_id = call.data.replace('claim_', '')
    admin_id = call.from_user.id
    admin_name = call.from_user.first_name
    
    # التحقق من أن المستخدم مشرف مصرح له
    if admin_id not in admins_database:
        return bot.answer_callback_query(call.id, "⛔ غير مصرح لك!", show_alert=True)
    
    # التحقق من وجود الطلب
    if order_id not in active_orders:
        return bot.answer_callback_query(call.id, "❌ الطلب غير موجود أو تم حذفه!", show_alert=True)
    
    order = active_orders[order_id]
    
    # التحقق من أن الطلب لم يتم استلامه مسبقاً
    if order['status'] == 'claimed':
        return bot.answer_callback_query(call.id, "⚠️ تم استلام هذا الطلب مسبقاً!", show_alert=True)
    
    # تحديث حالة الطلب
    order['status'] = 'claimed'
    order['admin_id'] = admin_id
    
    # تحديث رسالة المشرف الذي استلم
    try:
        bot.edit_message_text(
            f"✅ تم استلام الطلب #{order_id}\n\n"
            f"📦 المنتج: {order['item_name']}\n"
            f"💰 السعر: {order['price']} ريال\n\n"
            f"👨‍💼 أنت المسؤول عن هذا الطلب\n"
            f"⏰ الحالة: قيد التنفيذ...\n\n"
            f"🔒 سيتم إرسال البيانات السرية لك الآن...",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
    except:
        pass
    
    # حذف الرسالة من المشرفين الآخرين
    if 'admin_messages' in order:
        for other_admin_id, msg_id in order['admin_messages'].items():
            if other_admin_id != admin_id:
                try:
                    bot.delete_message(other_admin_id, msg_id)
                except:
                    pass
    
    # إرسال البيانات المخفية للمشرف على الخاص
    hidden_info = order['hidden_data'] if order['hidden_data'] else "لا توجد بيانات مخفية لهذا المنتج."
    
    # إنشاء زر لتأكيد إتمام الطلب
    markup = types.InlineKeyboardMarkup()
    complete_btn = types.InlineKeyboardButton("✅ تم التسليم للعميل", callback_data=f"complete_{order_id}")
    markup.add(complete_btn)
    
    bot.send_message(
        admin_id,
        f"🔐 بيانات الطلب السرية #{order_id}\n\n"
        f"📦 المنتج: {order['item_name']}\n\n"
        f"👤 معلومات العميل:\n"
        f"• الاسم: {order['buyer_name']}\n"
        f"• آيدي تيليجرام: {order['buyer_id']}\n"
        f"• آيدي اللعبة: {order['game_id']}\n"
        f"• الاسم في اللعبة: {order['game_name']}\n\n"
        f"🔒 البيانات المحمية:\n"
        f"{hidden_info}\n\n"
        f"⚡ قم بتنفيذ الطلب ثم اضغط الزر أدناه!",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id, "✅ تم استلام الطلب! تحقق من رسائلك الخاصة.")

# زر إتمام الطلب من قبل المشرف
@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_'))
def complete_order(call):
    order_id = call.data.replace('complete_', '')
    admin_id = call.from_user.id
    
    if order_id not in active_orders:
        return bot.answer_callback_query(call.id, "❌ الطلب غير موجود!", show_alert=True)
    
    order = active_orders[order_id]
    
    # التحقق من أن المشرف هو نفسه من استلم الطلب
    if order['admin_id'] != admin_id:
        return bot.answer_callback_query(call.id, "⛔ لم تستلم هذا الطلب!", show_alert=True)
    
    # تحويل المال للبائع
    add_balance(order['seller_id'], order['price'])
    
    # إشعار البائع
    bot.send_message(
        order['seller_id'],
        f"💰 تم بيع منتجك!\n\n"
        f"📦 المنتج: {order['item_name']}\n"
        f"💵 المبلغ: {order['price']} ريال\n\n"
        f"✅ تم إضافة المبلغ لرصيدك!"
    )
    
    # إشعار العميل
    markup = types.InlineKeyboardMarkup()
    confirm_btn = types.InlineKeyboardButton("✅ أكد الاستلام", callback_data=f"buyer_confirm_{order_id}")
    markup.add(confirm_btn)
    
    bot.send_message(
        order['buyer_id'],
        f"🎉 تم تنفيذ طلبك!\n\n"
        f"📦 المنتج: {order['item_name']}\n\n"
        f"✅ يرجى التحقق من حسابك والتأكد من استلام الخدمة\n\n"
        f"⚠️ إذا استلمت الخدمة بنجاح، اضغط الزر أدناه لتأكيد الاستلام.",
        reply_markup=markup
    )
    
    # تحديث حالة الطلب
    order['status'] = 'completed'
    
    # حذف رسالة البيانات السرية من خاص المشرف
    try:
        bot.edit_message_text(
            f"✅ تم إتمام الطلب #{order_id}\n\nتم حذف البيانات السرية للأمان.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
    except:
        pass
    
    bot.answer_callback_query(call.id, "✅ تم إتمام الطلب بنجاح!")

# زر تأكيد الاستلام من العميل
@bot.callback_query_handler(func=lambda call: call.data.startswith('buyer_confirm_'))
def buyer_confirm(call):
    order_id = call.data.replace('buyer_confirm_', '')
    
    if order_id not in active_orders:
        return bot.answer_callback_query(call.id, "✅ تم تأكيد هذا الطلب مسبقاً!")
    
    order = active_orders[order_id]
    
    # التحقق من أن المستخدم هو المشتري
    if str(call.from_user.id) != order['buyer_id']:
        return bot.answer_callback_query(call.id, "⛔ هذا ليس طلبك!", show_alert=True)
    
    # حذف الطلب من القائمة النشطة
    del active_orders[order_id]
    
    bot.edit_message_text(
        f"✅ شكراً لتأكيدك!\n\n"
        f"تم إتمام الطلب بنجاح ✨\n"
        f"نتمنى لك تجربة ممتعة! 🎮",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    
    bot.answer_callback_query(call.id, "✅ شكراً لك!")

# زر تأكيد الاستلام (يحرر المال للبائع) - الكود القديم للتوافق
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
    
    bot.edit_message_text(f"✅ تم تأكيد استلام الخدمة: {trans['item_name']}\nتم تحويل {amount} ريال للبائع.", call.message.chat.id, call.message.message_id)
    bot.send_message(seller_id, f"🤑 مبروك! قام العميل بتأكيد الاستلام.\n💰 تم إضافة {amount} ريال لرصيدك.\n📦 الطلب: {trans['item_name']}\n🎮 آيدي: {trans.get('game_id', 'غير محدد')}")

# --- مسارات الموقع (Flask) ---

# مسار تسجيل الخروج
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return {'success': True}

# مسار جلب طلبات المستخدم
@app.route('/get_orders')
def get_user_orders():
    user_id = str(request.args.get('user_id', '0'))
    
    if not user_id or user_id == '0':
        return {'orders': []}
    
    # جلب جميع الطلبات الخاصة بالمستخدم
    user_orders = []
    for order_id, order in active_orders.items():
        if str(order['buyer_id']) == user_id:
            # إضافة اسم المشرف إذا تم استلام الطلب
            admin_name = None
            if order.get('admin_id'):
                try:
                    admin_info = bot.get_chat(order['admin_id'])
                    admin_name = admin_info.first_name
                except:
                    admin_name = "مشرف"
            
            user_orders.append({
                'order_id': order_id,
                'item_name': order['item_name'],
                'price': order['price'],
                'game_id': order.get('game_id', ''),
                'game_name': order.get('game_name', ''),
                'status': order['status'],
                'admin_name': admin_name
            })
    
    # ترتيب الطلبات من الأحدث للأقدم
    user_orders.reverse()
    
    return {'orders': user_orders}

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
    seller_id = str(data.get('seller_id'))
    
    # التحقق من أن البائع هو المالك فقط
    if int(seller_id) != ADMIN_ID:
        return {'status': 'error', 'message': 'غير مصرح لك بإضافة منتجات! فقط المالك يمكنه ذلك.'}
    
    # حفظ البيانات المخفية بشكل آمن
    item = {
        'item_name': data.get('item_name'),
        'price': data.get('price'),
        'seller_id': seller_id,
        'seller_name': data.get('seller_name'),
        'hidden_data': data.get('hidden_data', ''),  # البيانات المخفية
        'category': data.get('category', ''),  # الفئة
        'image_url': data.get('image_url', '')  # رابط الصورة
    }
    marketplace_items.append(item)
    return {'status': 'success'}

@app.route('/buy', methods=['POST'])
def buy_item():
    data = request.json
    buyer_id = str(data.get('buyer_id'))
    buyer_name = data.get('buyer_name')
    item_index = int(data.get('item_index'))
    
    if item_index >= len(marketplace_items):
        return {'status': 'error', 'message': 'المنتج غير موجود'}
    
    item = marketplace_items[item_index]
    
    # التحقق من أن المنتج لم يُباع بعد
    if item.get('sold', False):
        return {'status': 'error', 'message': 'هذا المنتج مباع بالفعل! 🚫'}
    
    price = float(item['price'])
    
    # 1. التحقق من الرصيد
    buyer_balance = get_balance(buyer_id)
    if buyer_balance < price:
        return {'status': 'error', 'message': 'الرصيد غير كافي'}
    
    # 2. خصم الرصيد
    users_wallets[buyer_id] -= price
    
    # 3. تحويل المال للبائع فوراً
    add_balance(item['seller_id'], price)
    
    # 4. إنشاء معرف فريد للطلب
    order_id = f"ORD_{random.randint(100000, 999999)}"
    
    # 5. حفظ الطلب في قائمة الطلبات (للسجل فقط)
    active_orders[order_id] = {
        'buyer_id': buyer_id,
        'buyer_name': buyer_name,
        'item_name': item['item_name'],
        'price': price,
        'hidden_data': item.get('hidden_data', ''),
        'seller_id': item['seller_id'],
        'seller_name': item['seller_name'],
        'status': 'completed',
        'admin_id': str(ADMIN_ID),
        'message_id': None
    }
    
    # 6. تحديد المنتج كمباع
    marketplace_items[item_index]['sold'] = True
    marketplace_items[item_index]['buyer_name'] = buyer_name
    
    # 7. إرسال البيانات المخفية للمشتري فوراً
    hidden_info = item.get('hidden_data', 'لا توجد بيانات إضافية')
    
    message_sent = False
    try:
        bot.send_message(
            int(buyer_id),
            f"✅ تم الشراء بنجاح!\n\n"
            f"📦 المنتج: {item['item_name']}\n"
            f"💰 المبلغ المدفوع: {price} ريال\n"
            f"🆔 رقم الطلب: #{order_id}\n\n"
            f"🔐 بيانات الحساب:\n"
            f"{hidden_info}\n\n"
            f"✨ استمتع بخدمتك!\n"
            f"شكراً لاستخدامك متجرنا 🎉"
        )
        message_sent = True
        print(f"✅ تم إرسال البيانات للمشتري {buyer_id}")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة للمشتري {buyer_id}: {str(e)}")
        # إذا فشل الإرسال، نخبر المستخدم أن يبدأ محادثة مع البوت
        return {
            'status': 'error', 
            'message': f'تم خصم المبلغ ولكن لم نتمكن من إرسال البيانات!\n\nالرجاء:\n1. افتح البوت @{bot.get_me().username}\n2. اضغط /start\n3. ثم أرسل رقم الطلب: {order_id}'
        }
    
    # 8. إشعار للبائع
    try:
        bot.send_message(
            int(item['seller_id']),
            f"💰 تم بيع منتجك!\n\n"
            f"📦 المنتج: {item['item_name']}\n"
            f"💵 المبلغ: {price} ريال\n"
            f"👤 المشتري: {buyer_name}\n"
            f"🆔 رقم الطلب: #{order_id}\n\n"
            f"✅ تم إضافة المبلغ لرصيدك!"
        )
        print(f"✅ تم إرسال إشعار للبائع {item['seller_id']}")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة للبائع: {str(e)}")
    
    # 9. إشعار للمالك
    try:
        bot.send_message(
            ADMIN_ID,
            f"🔔 عملية شراء جديدة\n\n"
            f"📦 المنتج: {item['item_name']}\n"
            f"💰 السعر: {price} ريال\n"
            f"👤 المشتري: {buyer_name}\n"
            f"🆔 رقم الطلب: #{order_id}\n\n"
            f"✅ تم التسليم الفوري\n"
            f"📊 المنتجات المتبقية: {len(marketplace_items)}"
        )
        print(f"✅ تم إرسال إشعار للمالك")
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة للمالك: {str(e)}")

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

# Health check endpoint for Render
@app.route('/health')
def health():
    return {'status': 'ok'}, 200

if __name__ == "__main__":
    # هذا السطر يجعل البوت يعمل على المنفذ الصحيح في ريندر أو 10000 في جهازك
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
