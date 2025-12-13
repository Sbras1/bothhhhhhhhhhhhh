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
import uuid
import firebase_admin
from firebase_admin import credentials, firestore

# محاولة استيراد FieldFilter للنسخ الجديدة
try:
    from google.cloud.firestore_v1.base_query import FieldFilter
    USE_FIELD_FILTER = True
except ImportError:
    USE_FIELD_FILTER = False

# --- إعدادات Firebase ---
# التحقق من وجود متغير البيئة أولاً (للإنتاج في Render)
firebase_credentials_json = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_credentials_json:
    # استخدام المتغير البيئي (Render)
    cred_dict = json.loads(firebase_credentials_json)
    cred = credentials.Certificate(cred_dict)
    print("✅ Firebase: استخدام المتغير البيئي (Production)")
else:
    # استخدام الملف المحلي (للتطوير)
    cred = credentials.Certificate('serviceAccountKey.json')
    print("✅ Firebase: استخدام الملف المحلي (Development)")

firebase_admin.initialize_app(cred)
db = firestore.client()

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

# دالة للتعامل مع where بالطريقة المتوافقة
def query_where(collection_ref, field, op, value):
    """استخدام where بطريقة متوافقة مع جميع النسخ"""
    if USE_FIELD_FILTER:
        return collection_ref.where(filter=FieldFilter(field, op, value))
    else:
        return collection_ref.where(field, op, value)

def get_balance(user_id):
    """جلب الرصيد من Firebase"""
    try:
        uid = str(user_id)
        doc = db.collection('users').document(uid).get()
        if doc.exists:
            return doc.to_dict().get('balance', 0.0)
        return 0.0
    except Exception as e:
        print(f"⚠️ خطأ في جلب الرصيد: {e}")
        return users_wallets.get(str(user_id), 0.0)

def add_balance(user_id, amount):
    """إضافة رصيد للمستخدم في Firebase والذاكرة"""
    uid = str(user_id)
    if uid not in users_wallets:
        users_wallets[uid] = 0.0
    users_wallets[uid] += float(amount)
    
    # حفظ في Firebase
    try:
        db.collection('users').document(uid).set({
            'balance': users_wallets[uid],
            'telegram_id': uid,
            'updated_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
        print(f"✅ تم حفظ رصيد المستخدم {uid}: {users_wallets[uid]} ريال في Firestore")
    except Exception as e:
        print(f"❌ خطأ في حفظ الرصيد إلى Firebase: {e}")

# إضافة UUID للمنتجات الموجودة (إذا لم يكن لديها ID)
def ensure_product_ids():
    for item in marketplace_items:
        if 'id' not in item:
            item['id'] = str(uuid.uuid4())

# دالة لرفع البيانات من الذاكرة إلى Firebase
def migrate_data_to_firebase():
    """نقل البيانات من المتغيرات في الذاكرة إلى Firebase"""
    try:
        print("🔄 بدء نقل البيانات إلى Firebase...")
        
        # 1. رفع المنتجات
        if marketplace_items:
            products_ref = db.collection('products')
            for item in marketplace_items:
                product_id = item.get('id', str(uuid.uuid4()))
                products_ref.document(product_id).set({
                    'item_name': item.get('item_name', ''),
                    'price': float(item.get('price', 0)),
                    'seller_id': str(item.get('seller_id', '')),
                    'seller_name': item.get('seller_name', ''),
                    'hidden_data': item.get('hidden_data', ''),
                    'image_url': item.get('image_url', ''),
                    'category': item.get('category', 'أخرى'),
                    'details': item.get('details', ''),
                    'sold': item.get('sold', False),
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            print(f"✅ تم رفع {len(marketplace_items)} منتج")
        
        # 2. رفع أرصدة المستخدمين
        if users_wallets:
            users_ref = db.collection('users')
            for user_id, balance in users_wallets.items():
                users_ref.document(str(user_id)).set({
                    'balance': float(balance),
                    'telegram_id': str(user_id),
                    'updated_at': firestore.SERVER_TIMESTAMP
                }, merge=True)
            print(f"✅ تم رفع {len(users_wallets)} مستخدم")
        
        # 3. رفع الطلبات النشطة
        if active_orders:
            orders_ref = db.collection('orders')
            for order_id, order_data in active_orders.items():
                orders_ref.document(str(order_id)).set({
                    'item_name': order_data.get('item_name', ''),
                    'price': float(order_data.get('price', 0)),
                    'buyer_id': str(order_data.get('buyer_id', '')),
                    'buyer_name': order_data.get('buyer_name', ''),
                    'seller_id': str(order_data.get('seller_id', '')),
                    'status': order_data.get('status', 'pending'),
                    'admin_id': str(order_data.get('admin_id', '')) if order_data.get('admin_id') else '',
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            print(f"✅ تم رفع {len(active_orders)} طلب")
        
        # 4. رفع مفاتيح الشحن
        if charge_keys:
            keys_ref = db.collection('charge_keys')
            for key_code, key_data in charge_keys.items():
                keys_ref.document(key_code).set({
                    'amount': float(key_data.get('amount', 0)),
                    'used': key_data.get('used', False),
                    'used_by': str(key_data.get('used_by', '')) if key_data.get('used_by') else '',
                    'created_at': key_data.get('created_at', time.time())
                })
            print(f"✅ تم رفع {len(charge_keys)} مفتاح شحن")
        
        print("🎉 تم رفع جميع البيانات إلى Firebase بنجاح!")
        return True
        
    except Exception as e:
        print(f"❌ خطأ في رفع البيانات: {e}")
        return False

# دالة لتحميل البيانات من Firebase إلى الذاكرة (عند بدء التشغيل)
def load_data_from_firebase():
    """تحميل البيانات من Firebase إلى المتغيرات في الذاكرة للاستخدام السريع"""
    global marketplace_items, users_wallets, charge_keys, active_orders
    
    try:
        print("📥 بدء تحميل البيانات من Firebase...")
        
        # 1. تحميل المنتجات (غير المباعة فقط)
        print("🔄 جاري تحميل المنتجات من Firestore...")
        products_ref = query_where(db.collection('products'), 'sold', '==', False)
        marketplace_items = []
        for doc in products_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            marketplace_items.append(data)
            print(f"  📦 منتج: {data.get('item_name', 'بدون اسم')} - {data.get('price', 0)} ريال")
        print(f"✅ تم تحميل {len(marketplace_items)} منتج من Firestore")
        
        # 2. تحميل أرصدة المستخدمين
        print("🔄 جاري تحميل المستخدمين من Firestore...")
        users_ref = db.collection('users')
        users_wallets = {}
        for doc in users_ref.stream():
            data = doc.to_dict()
            users_wallets[doc.id] = data.get('balance', 0.0)
            print(f"  👤 مستخدم {doc.id}: {data.get('balance', 0)} ريال")
        print(f"✅ تم تحميل {len(users_wallets)} مستخدم من Firestore")
        
        # 3. تحميل مفاتيح الشحن (غير المستخدمة فقط)
        keys_ref = query_where(db.collection('charge_keys'), 'used', '==', False)
        charge_keys = {}
        for doc in keys_ref.stream():
            data = doc.to_dict()
            charge_keys[doc.id] = {
                'amount': data.get('amount', 0),
                'used': data.get('used', False),
                'used_by': data.get('used_by'),
                'created_at': data.get('created_at', time.time())
            }
        print(f"✅ تم تحميل {len(charge_keys)} مفتاح شحن")
        
        # 4. تحميل الطلبات النشطة (pending فقط)
        orders_ref = query_where(db.collection('orders'), 'status', '==', 'pending')
        active_orders = {}
        for doc in orders_ref.stream():
            data = doc.to_dict()
            active_orders[doc.id] = data
        print(f"✅ تم تحميل {len(active_orders)} طلب نشط")
        
        print("🎉 تم تحميل جميع البيانات من Firebase بنجاح!")
        return True
        
    except Exception as e:
        print(f"⚠️ تحذير: لم يتم تحميل البيانات من Firebase: {e}")
        print("سيتم البدء ببيانات فارغة")
        return False

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
        
        /* نافذة التأكيد */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.8);
            animation: fadeIn 0.3s;
        }
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        .modal-content {
            background: linear-gradient(135deg, #2d2d2d 0%, #1a1a1a 100%);
            margin: 5% auto 80px auto;
            padding: 0;
            border-radius: 20px;
            max-width: 440px;
            max-height: 85vh;
            width: 90%;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            animation: slideDown 0.3s;
            overflow-y: auto;
        }
        @keyframes slideDown {
            from { transform: translateY(-50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        .modal-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 18px;
            text-align: center;
            color: white;
        }
        .modal-header h2 {
            margin: 0;
            font-size: 20px;
        }
        .modal-body {
            padding: 20px;
            color: var(--text-color);
        }
        .modal-product-info {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 12px;
            margin: 15px 0;
        }
        .modal-info-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .modal-info-row:last-child {
            border-bottom: none;
        }
        .modal-info-label {
            color: #888;
            font-size: 14px;
        }
        .modal-info-value {
            color: var(--text-color);
            font-weight: bold;
            font-size: 15px;
        }
        .modal-price {
            color: #00b894;
            font-size: 28px !important;
            font-weight: bold;
        }
        .modal-details {
            background: rgba(102, 126, 234, 0.1);
            padding: 12px;
            border-radius: 10px;
            margin: 15px 0;
            border-right: 4px solid #667eea;
            color: var(--text-color);
            font-size: 14px;
            line-height: 1.6;
        }
        .modal-footer {
            display: flex;
            gap: 10px;
            padding: 0 20px 20px 20px;
        }
        .modal-btn {
            flex: 1;
            padding: 15px;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
        }
        .modal-btn-confirm {
            background: linear-gradient(135deg, #00b894, #00cec9);
            color: white;
        }
        .modal-btn-confirm:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 15px rgba(0, 184, 148, 0.4);
        }
        .modal-btn-cancel {
            background: #e74c3c;
            color: white;
        }
        .modal-btn-cancel:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 15px rgba(231, 76, 60, 0.4);
        }
        
        /* نافذة النجاح */
        .success-modal .modal-header {
            background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
        }
        .success-icon {
            font-size: 80px;
            text-align: center;
            margin: 20px 0;
            animation: scaleIn 0.5s;
        }
        @keyframes scaleIn {
            0% { transform: scale(0); }
            50% { transform: scale(1.2); }
            100% { transform: scale(1); }
        }
        .success-message {
            text-align: center;
            font-size: 18px;
            color: var(--text-color);
            margin: 20px 0;
            line-height: 1.6;
        }
        .success-note {
            background: rgba(0, 184, 148, 0.1);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            color: #00b894;
            font-size: 14px;
            border: 2px dashed #00b894;
            margin: 20px 0;
        }
        
        /* نافذة التحذير */
        .warning-modal .modal-header {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);
            padding: 18px;
        }
        .warning-icon {
            font-size: 55px;
            text-align: center;
            margin: 10px 0 15px 0;
            animation: bounce 0.6s ease-in-out;
            filter: drop-shadow(0 5px 15px rgba(255, 107, 107, 0.3));
        }
        @keyframes bounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-20px); }
        }
        .warning-message {
            text-align: center;
            font-size: 15px;
            color: var(--text-color);
            margin: 0 0 18px 0;
            line-height: 1.4;
            font-weight: 500;
        }
        .balance-comparison {
            display: flex;
            gap: 12px;
            margin: 18px 0;
        }
        .balance-box {
            flex: 1;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.02) 100%);
            padding: 15px;
            border-radius: 12px;
            text-align: center;
            border: 2px solid rgba(255, 255, 255, 0.1);
            position: relative;
            overflow: hidden;
        }
        .balance-box::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #ff6b6b, #ee5a6f);
        }
        .balance-box.current::before {
            background: linear-gradient(90deg, #a29bfe, #6c5ce7);
        }
        .balance-label {
            color: #999;
            font-size: 11px;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .balance-value {
            font-size: 28px;
            font-weight: bold;
            color: #ff6b6b;
            margin: 8px 0;
            text-shadow: 0 2px 10px rgba(255, 107, 107, 0.3);
        }
        .balance-box.current .balance-value {
            color: #a29bfe;
            text-shadow: 0 2px 10px rgba(162, 155, 254, 0.3);
        }
        .balance-currency {
            font-size: 12px;
            color: #666;
            font-weight: normal;
        }
        .warning-actions {
            background: linear-gradient(135deg, rgba(255, 193, 7, 0.1) 0%, rgba(255, 152, 0, 0.1) 100%);
            padding: 15px;
            border-radius: 12px;
            margin: 18px 0 0 0;
            border: 2px solid rgba(255, 193, 7, 0.3);
        }
        .warning-actions h4 {
            color: #ffc107;
            font-size: 14px;
            margin: 0 0 12px 0;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }
        .action-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 0;
            color: var(--text-color);
            font-size: 13px;
        }
        .action-icon {
            font-size: 18px;
            min-width: 28px;
            text-align: center;
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
        
        /* صف الأزرار العلوية */
        .top-buttons-row {
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
        }
        
        /* زر حسابي */
        .account-btn {
            background: linear-gradient(135deg, #6c5ce7, #a29bfe);
            color: white;
            padding: 10px 16px;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 15px rgba(108, 92, 231, 0.3);
            transition: all 0.3s;
            flex: 1;
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
        
        /* زر شحن الكود */
        .charge-btn {
            background: linear-gradient(135deg, #00b894, #55efc4);
            color: white;
            padding: 10px 16px;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: bold;
            box-shadow: 0 4px 15px rgba(0, 184, 148, 0.3);
            transition: all 0.3s;
            flex: 1;
            justify-content: center;
        }
        .charge-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 184, 148, 0.4);
        }
        
        /* أزرار الشحن السريع */
        .quick-charge-row {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }
        .quick-charge-btn {
            flex: 1;
            min-width: 70px;
            background: linear-gradient(135deg, #fdcb6e, #f39c12);
            color: #2d3436;
            padding: 10px 8px;
            border-radius: 10px;
            cursor: pointer;
            text-align: center;
            font-weight: bold;
            font-size: 13px;
            box-shadow: 0 3px 10px rgba(243, 156, 18, 0.3);
            transition: all 0.3s;
            text-decoration: none;
            display: block;
        }
        .quick-charge-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(243, 156, 18, 0.4);
        }
        .quick-charge-btn span {
            display: block;
            font-size: 11px;
            opacity: 0.8;
            margin-top: 2px;
        }
        
        /* نافذة شحن الكود */
        .charge-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .charge-modal.active {
            display: flex;
        }
        .charge-modal-content {
            background: var(--card-bg);
            padding: 25px;
            border-radius: 16px;
            width: 90%;
            max-width: 350px;
            text-align: center;
        }
        .charge-modal-content h3 {
            color: #00b894;
            margin-bottom: 20px;
        }
        .charge-input {
            width: 100%;
            padding: 12px;
            border: 2px solid #444;
            border-radius: 10px;
            background: #2d3436;
            color: white;
            font-size: 16px;
            text-align: center;
            margin-bottom: 15px;
            box-sizing: border-box;
        }
        .charge-input:focus {
            border-color: #00b894;
            outline: none;
        }
        .charge-submit-btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #00b894, #55efc4);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-bottom: 10px;
        }
        .charge-cancel-btn {
            width: 100%;
            padding: 10px;
            background: #636e72;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 14px;
            cursor: pointer;
        }
        
        /* محتوى حسابي والشحن */
        .account-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.4s ease;
        }
        .account-content.open {
            max-height: 600px;
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

    <!-- صف الأزرار العلوية -->
    <div class="top-buttons-row">
        <!-- زر حسابي -->
        <div class="account-btn" onclick="toggleAccount()" id="accountBtn">
            <div class="account-btn-left">
                <span class="account-icon">👤</span>
                <span>حسابي</span>
            </div>
            <span class="arrow" id="accountArrow">▼</span>
        </div>
        
        <!-- زر شحن الكود -->
        <div class="charge-btn" onclick="toggleCharge()" id="chargeBtn">
            <div class="account-btn-left">
                <span>💳</span>
                <span>شحن كود</span>
            </div>
            <span class="arrow" id="chargeArrow">▼</span>
        </div>
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
    
    <!-- محتوى شحن الكود -->
    <div class="account-content" id="chargeContent">
        <div class="account-details" style="background: linear-gradient(135deg, rgba(0, 184, 148, 0.1), rgba(85, 239, 196, 0.1)); border: 1px solid rgba(0, 184, 148, 0.3);">
            <h4 style="color: #00b894; margin: 0 0 15px 0; text-align: center;">💳 شحن رصيدك</h4>
            
            <!-- شحن بكود -->
            <div style="margin-bottom: 20px;">
                <label style="color: #888; font-size: 13px; display: block; margin-bottom: 8px; text-align: right;">شحن بكود:</label>
                <div style="display: flex; gap: 10px;">
                    <button onclick="submitChargeCode()" style="padding: 12px 20px; background: linear-gradient(135deg, #00b894, #55efc4); color: white; border: none; border-radius: 10px; font-weight: bold; cursor: pointer; white-space: nowrap;">شحن ⚡</button>
                    <input type="text" id="chargeCodeInput" placeholder="أدخل كود الشحن" style="flex: 1; padding: 12px; border: 2px solid #444; border-radius: 10px; background: #2d3436; color: white; font-size: 14px; text-align: right;">
                </div>
            </div>
            
            <!-- أزرار الشحن السريع -->
            <div>
                <label style="color: #888; font-size: 13px; display: block; margin-bottom: 10px;">شراء رصيد:</label>
                <div class="quick-charge-row">
                    <a href="#" class="quick-charge-btn" id="charge20">
                        20 ريال
                        <span>اشتري</span>
                    </a>
                    <a href="#" class="quick-charge-btn" id="charge50">
                        50 ريال
                        <span>اشتري</span>
                    </a>
                    <a href="#" class="quick-charge-btn" id="charge100">
                        100 ريال
                        <span>اشتري</span>
                    </a>
                    <a href="#" class="quick-charge-btn" id="charge150">
                        150 ريال
                        <span>اشتري</span>
                    </a>
                </div>
            </div>
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
    <!-- نافذة التأكيد -->
    <div id="buyModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>🛒 تأكيد الشراء</h2>
            </div>
            <div class="modal-body">
                <div class="modal-product-info">
                    <div class="modal-info-row">
                        <span class="modal-info-label">📦 المنتج:</span>
                        <span class="modal-info-value" id="modalProductName"></span>
                    </div>
                    <div class="modal-info-row">
                        <span class="modal-info-label">🏷️ الفئة:</span>
                        <span class="modal-info-value" id="modalProductCategory"></span>
                    </div>
                    <div class="modal-info-row">
                        <span class="modal-info-label">💰 السعر:</span>
                        <span class="modal-info-value modal-price" id="modalProductPrice"></span>
                    </div>
                </div>
                <div class="modal-details" id="modalProductDetails"></div>
                <div style="text-align: center; color: #00b894; font-size: 14px; margin-top: 15px;">
                    ⚡ سيتم تسليم الحساب فوراً بعد الشراء
                </div>
            </div>
            <div class="modal-footer">
                <button class="modal-btn modal-btn-cancel" onclick="closeModal()">إلغاء</button>
                <button class="modal-btn modal-btn-confirm" onclick="confirmPurchase()">تأكيد الشراء ✓</button>
            </div>
        </div>
    </div>
    
    <!-- نافذة النجاح -->
    <div id="successModal" class="modal">
        <div class="modal-content success-modal">
            <div class="modal-header">
                <h2>✅ تم الشراء بنجاح</h2>
            </div>
            <div class="modal-body">
                <div class="success-icon">🎉</div>
                <div class="success-message">
                    تم شراء المنتج بنجاح!<br>
                    تحقق من رسائل البوت لاستلام بيانات الحساب
                </div>
                <div class="success-note">
                    📱 افتح البوت الآن للحصول على:<br>
                    🔐 البريد الإلكتروني<br>
                    🔑 كلمة المرور<br>
                    ✨ استمتع بخدمتك!
                </div>
            </div>
            <div class="modal-footer">
                <button class="modal-btn modal-btn-confirm" onclick="closeSuccessModal()" style="width: 100%;">حسناً 👍</button>
            </div>
        </div>
    </div>
    
    <!-- نافذة الرصيد غير كافٍ -->
    <div id="warningModal" class="modal">
        <div class="modal-content warning-modal">
            <div class="modal-header">
                <h2>⚠️ رصيد غير كافٍ</h2>
            </div>
            <div class="modal-body">
                <div class="warning-icon">�</div>
                <div class="warning-message">
                    عذراً، رصيدك الحالي غير كافٍ لإتمام عملية الشراء
                </div>
                <div class="balance-comparison">
                    <div class="balance-box current">
                        <div class="balance-label">رصيدك الحالي</div>
                        <div class="balance-value"><span id="warningBalance">0.00</span> <span class="balance-currency">ريال</span></div>
                    </div>
                    <div class="balance-box">
                        <div class="balance-label">المطلوب</div>
                        <div class="balance-value"><span id="warningPrice">0.00</span> <span class="balance-currency">ريال</span></div>
                    </div>
                </div>
                <div class="warning-actions">
                    <h4>💡 كيفية الشحن</h4>
                    <div class="action-item">
                        <div class="action-icon">👤</div>
                        <div>التواصل مع الإدارة لشحن الرصيد</div>
                    </div>
                    <div class="action-item">
                        <div class="action-icon">🔑</div>
                        <div>استخدام مفتاح شحن عبر الأمر /شحن</div>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="modal-btn modal-btn-cancel" onclick="closeWarningModal()" style="width: 100%;">حسناً</button>
            </div>
        </div>
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
                        <button class="product-buy-btn" onclick='buyItem("{{ item.id }}", {{ item.price }}, "{{ item.item_name|replace('"', '\\"') }}", "{{ item.get('category', '')|replace('"', '\\"') }}", {{ item.get('details', '')|tojson }})'>شراء 🛒</button>
                    {% else %}
                        <div class="my-product-badge">منتجك ⭐</div>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>

    <!-- قسم مشترياتي -->
    {% if my_purchases %}
    <div style="margin-top: 30px;">
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
            <h3 style="margin: 0; color: #00b894;">🛍️ مشترياتي</h3>
            <span style="background: #00b894; color: white; padding: 3px 10px; border-radius: 15px; font-size: 12px;">{{ my_purchases|length }}</span>
        </div>
        <div class="product-grid">
            {% for purchase in my_purchases %}
            <div class="product-card" style="border: 2px solid #00b894;">
                <div class="product-badge" style="background: linear-gradient(135deg, #00b894, #00cec9);">مشترياتي ✓</div>
                <div class="product-image" style="background: linear-gradient(135deg, #00b894, #00cec9);">
                    🎉
                </div>
                <div class="product-info">
                    <span class="product-category" style="background: rgba(0, 184, 148, 0.2); color: #00b894;">{{ purchase.get('item_name', 'منتج') }}</span>
                    <div class="product-name">{{ purchase.get('item_name', 'منتج') }}</div>
                    <div class="product-seller">🆔 #{{ purchase.get('order_id', '')[:12] }}</div>
                    <div class="product-footer">
                        <div class="product-price">{{ purchase.get('price', 0) }} ريال</div>
                        <span style="color: #00b894; font-weight: bold; font-size: 12px;">✅ مكتمل</span>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <!-- قسم المنتجات المباعة -->
    {% if sold_items %}
    <div style="margin-top: 30px;">
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
            <h3 style="margin: 0; color: #e74c3c;">✅ المنتجات المباعة</h3>
            <span style="background: #e74c3c; color: white; padding: 3px 10px; border-radius: 15px; font-size: 12px;">{{ sold_items|length }}</span>
            <span id="soldCategoryFilter" style="color: #e74c3c; font-size: 14px; font-weight: bold;"></span>
        </div>
        
        <div class="product-grid" id="soldProductsGrid">
            {% for item in sold_items %}
            <div class="product-card sold-product sold-item-card" data-category="{{ item.get('category', '') }}" style="opacity: 0.7;">
                <div class="sold-ribbon">مباع ✓</div>
                <div class="product-image">
                    {% if item.get('image_url') %}
                    <img src="{{ item.image_url }}" alt="{{ item.item_name }}" style="filter: grayscale(50%);">
                    {% else %}
                    🎁
                    {% endif %}
                </div>
                {% if item.get('category') %}
                <div class="product-badge" style="background: #e74c3c;">{{ item.category }}</div>
                {% endif %}
                <div class="product-info">
                    {% if item.get('category') %}
                    <span class="product-category" style="background: rgba(231, 76, 60, 0.2); color: #e74c3c;">{{ item.category }}</span>
                    {% endif %}
                    <div class="product-name">{{ item.item_name }}</div>
                    <div class="product-seller">🏪 {{ item.seller_name }}</div>
                    {% if item.get('buyer_name') %}
                    <div class="sold-info">🎉 تم شراءه بواسطة: {{ item.buyer_name }}</div>
                    {% endif %}
                    <div class="product-footer">
                        <div class="product-price" style="color: #e74c3c; text-decoration: line-through;">{{ item.price }} ريال</div>
                        <span style="color: #e74c3c; font-weight: bold; font-size: 12px;">مباع 🚫</span>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

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
        
        // دالة لفتح/إغلاق قسم شحن الكود
        function toggleCharge() {
            // التحقق من تسجيل الدخول
            if(!isTelegramWebApp && (!currentUserId || currentUserId == 0)) {
                showLoginModal();
                return;
            }
            
            // إغلاق قسم حسابي إذا كان مفتوحاً
            const accountContent = document.getElementById("accountContent");
            const accountArrow = document.getElementById("accountArrow");
            if(accountContent.classList.contains("open")) {
                accountContent.classList.remove("open");
                accountArrow.classList.remove("open");
            }
            
            // فتح/إغلاق قسم الشحن
            const chargeContent = document.getElementById("chargeContent");
            const chargeArrow = document.getElementById("chargeArrow");
            chargeContent.classList.toggle("open");
            chargeArrow.classList.toggle("open");
        }
        
        async function submitChargeCode() {
            const code = document.getElementById('chargeCodeInput').value.trim();
            if(!code) {
                alert('❌ الرجاء إدخال كود الشحن');
                return;
            }
            
            try {
                const response = await fetch('/charge_balance', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        user_id: currentUserId,
                        charge_key: code
                    })
                });
                
                const result = await response.json();
                if(result.success) {
                    alert('✅ ' + result.message);
                    userBalance = result.new_balance;
                    document.getElementById('balance').textContent = userBalance;
                    document.getElementById('chargeCodeInput').value = '';
                } else {
                    alert('❌ ' + result.message);
                }
            } catch(error) {
                alert('❌ حدث خطأ في الاتصال');
            }
        }
        
        // دالة لفتح/إغلاق قسم حسابي
        function toggleAccount() {
            // إذا كان المستخدم في متصفح عادي وغير مسجل دخول
            if(!isTelegramWebApp && (!currentUserId || currentUserId == 0)) {
                // توجيهه لصفحة تسجيل الدخول المدمجة
                showLoginModal();
                return;
            }
            
            // إغلاق قسم الشحن إذا كان مفتوحاً
            const chargeContent = document.getElementById("chargeContent");
            const chargeArrow = document.getElementById("chargeArrow");
            if(chargeContent.classList.contains("open")) {
                chargeContent.classList.remove("open");
                chargeArrow.classList.remove("open");
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
        let currentCategory = 'all'; // متغير لتتبع الفئة الحالية
        
        function filterCategory(category) {
            currentCategory = category; // حفظ الفئة الحالية
            
            // تحديث نص الفئة
            const categoryFilterText = document.getElementById('categoryFilter');
            if(category === 'all') {
                categoryFilterText.textContent = '';
            } else {
                categoryFilterText.textContent = `- ${category}`;
            }
            
            // تحديث مظهر بطاقات الأقسام
            document.querySelectorAll('.cat-card').forEach(card => {
                card.style.opacity = '0.5';
                card.style.transform = 'scale(0.95)';
            });
            if(category !== 'all') {
                document.querySelectorAll('.cat-card').forEach(card => {
                    if(card.querySelector('.cat-title').textContent.trim() === category) {
                        card.style.opacity = '1';
                        card.style.transform = 'scale(1)';
                        card.style.boxShadow = '0 0 15px rgba(108, 92, 231, 0.5)';
                    }
                });
            } else {
                document.querySelectorAll('.cat-card').forEach(card => {
                    card.style.opacity = '1';
                    card.style.transform = 'scale(1)';
                    card.style.boxShadow = '';
                });
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
            } else {
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
                                            `<button class="product-buy-btn" onclick='buyItem("${item.id}", ${item.price}, "${(item.item_name || '').replace(/"/g, '\\"')}", "${(item.category || '').replace(/"/g, '\\"')}", ${JSON.stringify(item.details || '')})'>شراء 🛒</button>` : 
                                            `<div class="my-product-badge">منتجك ⭐</div>`)
                                    }
                                </div>
                            </div>
                        </div>
                    `;
                    market.innerHTML += productHTML;
                });
            }
            
            // تصفية المنتجات المباعة أيضاً
            filterSoldByMainCategory(category);
        }
        
        // دالة لتصفية المنتجات المباعة بناءً على اختيار القسم الرئيسي
        function filterSoldByMainCategory(category) {
            // تحديث نص القسم المختار
            const soldCategoryFilter = document.getElementById('soldCategoryFilter');
            if(soldCategoryFilter) {
                if(category === 'all') {
                    soldCategoryFilter.textContent = '';
                } else {
                    soldCategoryFilter.textContent = `- ${category}`;
                }
            }
            
            document.querySelectorAll('.sold-item-card').forEach(card => {
                if(category === 'all' || card.dataset.category === category) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        }

        let currentPurchaseData = null;
        
        function buyItem(itemId, price, itemName, category, details) {
            // التحقق من الرصيد أولاً
            if(userBalance < price) {
                showWarningModal(price);
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

            // حفظ بيانات الشراء
            currentPurchaseData = {
                itemId: itemId,
                buyerId: buyerId,
                buyerName: buyerName
            };

            // عرض نافذة التأكيد
            document.getElementById('modalProductName').textContent = itemName;
            document.getElementById('modalProductCategory').textContent = category || 'غير محدد';
            document.getElementById('modalProductPrice').textContent = price + ' ريال';
            document.getElementById('modalProductDetails').textContent = details || 'لا توجد تفاصيل إضافية';
            document.getElementById('buyModal').style.display = 'block';
        }

        function closeModal() {
            document.getElementById('buyModal').style.display = 'none';
            currentPurchaseData = null;
        }

        function confirmPurchase() {
            if(!currentPurchaseData) return;

            fetch('/buy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    buyer_id: currentPurchaseData.buyerId,
                    buyer_name: currentPurchaseData.buyerName,
                    item_id: currentPurchaseData.itemId
                })
            }).then(r => r.json()).then(data => {
                if(data.status == 'success') {
                    closeModal();
                    showSuccessModal();
                } else {
                    closeModal();
                    alert('❌ ' + data.message);
                }
            });
        }

        function showSuccessModal() {
            document.getElementById('successModal').style.display = 'block';
        }

        function closeSuccessModal() {
            document.getElementById('successModal').style.display = 'none';
            location.reload();
        }

        function showWarningModal(price) {
            document.getElementById('warningBalance').textContent = userBalance.toFixed(2);
            document.getElementById('warningPrice').textContent = parseFloat(price).toFixed(2);
            document.getElementById('warningModal').style.display = 'block';
        }

        function closeWarningModal() {
            document.getElementById('warningModal').style.display = 'none';
        }

        // إغلاق النافذة عند الضغط خارجها
        window.onclick = function(event) {
            const buyModal = document.getElementById('buyModal');
            const successModal = document.getElementById('successModal');
            const warningModal = document.getElementById('warningModal');
            if(event.target == buyModal) {
                closeModal();
            }
            if(event.target == successModal) {
                closeSuccessModal();
            }
            if(event.target == warningModal) {
                closeWarningModal();
            }
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
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    if message.from_user.last_name:
        user_name += ' ' + message.from_user.last_name
    username = message.from_user.username or ''
    
    # حفظ معلومات المستخدم في Firebase
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            # مستخدم جديد - إنشاء حساب
            user_ref.set({
                'telegram_id': user_id,
                'name': user_name,
                'username': username,
                'balance': 0.0,
                'created_at': firestore.SERVER_TIMESTAMP,
                'last_seen': firestore.SERVER_TIMESTAMP
            })
            users_wallets[user_id] = 0.0
        else:
            # مستخدم موجود - تحديث آخر ظهور
            user_ref.update({
                'name': user_name,
                'username': username,
                'last_seen': firestore.SERVER_TIMESTAMP
            })
    except Exception as e:
        print(f"⚠️ خطأ في حفظ معلومات المستخدم: {e}")
    
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
    
    msg = bot.send_message(message.chat.id, "📝 أرسل تفاصيل المنتج (مثل: مدة الاشتراك، المميزات، إلخ):")
    bot.register_next_step_handler(msg, process_product_details)

def process_product_details(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    temp_product_data[user_id]['details'] = message.text.strip()
    bot.reply_to(message, "✅ تم إضافة التفاصيل")
    
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
        f"� التفاصيل: {product['details']}\n"
        f"�🖼️ الصورة: {product['image_url']}\n"
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
            product_id = str(uuid.uuid4())  # رقم فريد لا يتكرر
            item = {
                'id': product_id,
                'item_name': product['item_name'],
                'price': str(product['price']),
                'seller_id': str(ADMIN_ID),
                'seller_name': 'المالك',
                'hidden_data': product['hidden_data'],
                'category': product['category'],
                'details': product['details'],
                'image_url': product['image_url'],
                'sold': False
            }
            
            # حفظ في Firebase أولاً
            try:
                db.collection('products').document(product_id).set({
                    'item_name': item['item_name'],
                    'price': float(product['price']),
                    'seller_id': str(ADMIN_ID),
                    'seller_name': 'المالك',
                    'hidden_data': item['hidden_data'],
                    'category': item['category'],
                    'details': item['details'],
                    'image_url': item['image_url'],
                    'sold': False,
                    'created_at': firestore.SERVER_TIMESTAMP
                })
                print(f"✅ تم حفظ المنتج {product_id} في Firebase")
            except Exception as e:
                print(f"❌ خطأ في حفظ المنتج في Firebase: {e}")
            
            # حفظ في الذاكرة
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
            
            # حفظ المفتاح في الذاكرة
            charge_keys[key_code] = {
                'amount': amount,
                'used': False,
                'used_by': None,
                'created_at': time.time()
            }
            
            # حفظ في Firebase
            try:
                db.collection('charge_keys').document(key_code).set({
                    'amount': float(amount),
                    'used': False,
                    'used_by': '',
                    'created_at': time.time()
                })
            except Exception as e:
                print(f"⚠️ خطأ في حفظ المفتاح في Firebase: {e}")
            
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
        
        # تحديث حالة المفتاح في الذاكرة
        charge_keys[key_code]['used'] = True
        charge_keys[key_code]['used_by'] = user_name
        charge_keys[key_code]['used_at'] = time.time()
        
        # تحديث في Firebase
        try:
            db.collection('charge_keys').document(key_code).update({
                'used': True,
                'used_by': user_name,
                'used_at': time.time()
            })
        except Exception as e:
            print(f"⚠️ خطأ في تحديث المفتاح في Firebase: {e}")
        
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
    
    # تحديث حالة الطلب في الذاكرة
    order['status'] = 'claimed'
    order['admin_id'] = admin_id
    
    # تحديث في Firebase
    try:
        db.collection('orders').document(order_id).update({
            'status': 'claimed',
            'admin_id': str(admin_id),
            'claimed_at': firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"⚠️ خطأ في تحديث الطلب في Firebase: {e}")
    
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
    
    # تحديث في Firebase
    try:
        db.collection('orders').document(order_id).update({
            'status': 'confirmed',
            'confirmed_at': firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"⚠️ خطأ في تحديث الطلب في Firebase: {e}")
    
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
    # التحقق من جلسة المستخدم
    user_id = session.get('user_id') or request.args.get('user_id')
    user_name = session.get('user_name', 'ضيف')
    
    # 1. جلب الرصيد (محدث من Firebase)
    balance = 0.0
    if user_id:
        balance = get_balance(user_id)
    
    # 2. جلب المنتجات (مباشرة من Firebase لضمان ظهورها)
    items = []
    try:
        # جلب المنتجات التي لم تُبع (sold == False)
        docs = query_where(db.collection('products'), 'sold', '==', False).stream()
        
        for doc in docs:
            p = doc.to_dict()
            p['id'] = doc.id  # مهم جداً لعملية الشراء
            items.append(p)
        
        print(f"✅ تم جلب {len(items)} منتج من Firebase للمتجر")
            
    except Exception as e:
        print(f"❌ خطأ في جلب المنتجات للمتجر: {e}")
        # في حال الفشل، نعود لاستخدام الذاكرة كاحتياط
        items = [i for i in marketplace_items if not i.get('sold')]

    # 3. جلب المنتجات المباعة (لعرضها في قسم منفصل)
    sold_items = []
    try:
        sold_docs = query_where(db.collection('products'), 'sold', '==', True).stream()
        for doc in sold_docs:
            p = doc.to_dict()
            p['id'] = doc.id
            sold_items.append(p)
        print(f"✅ تم جلب {len(sold_items)} منتج مباع من Firebase")
    except Exception as e:
        print(f"❌ خطأ في جلب المنتجات المباعة: {e}")
        sold_items = [i for i in marketplace_items if i.get('sold')]

    # 4. جلب مشتريات المستخدم الحالي
    my_purchases = []
    if user_id:
        try:
            purchases_docs = query_where(db.collection('orders'), 'buyer_id', '==', str(user_id)).stream()
            for doc in purchases_docs:
                p = doc.to_dict()
                p['order_id'] = doc.id
                my_purchases.append(p)
            print(f"✅ تم جلب {len(my_purchases)} مشتريات للمستخدم {user_id}")
        except Exception as e:
            print(f"❌ خطأ في جلب مشتريات المستخدم: {e}")

    # عرض الصفحة
    return render_template_string(HTML_PAGE, 
                                  items=items,
                                  sold_items=sold_items,
                                  my_purchases=my_purchases,
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
        'id': str(uuid.uuid4()),  # رقم فريد لا يتكرر
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
    try:
        data = request.json
        buyer_id = str(data.get('buyer_id'))
        buyer_name = data.get('buyer_name')
        item_id = str(data.get('item_id'))  # تأكد أنه نص

        print(f"🛒 محاولة شراء - item_id: {item_id}, buyer_id: {buyer_id}")

        # 1. البحث عن المنتج في Firebase مباشرة
        doc_ref = db.collection('products').document(item_id)
        doc = doc_ref.get()

        if not doc.exists:
            print(f"❌ المنتج {item_id} غير موجود في Firebase")
            # محاولة البحث في الذاكرة كاحتياط
            item = None
            for prod in marketplace_items:
                if prod.get('id') == item_id:
                    item = prod
                    print(f"✅ تم إيجاد المنتج في الذاكرة: {item.get('item_name')}")
                    break
            
            if not item:
                return {'status': 'error', 'message': 'المنتج غير موجود أو تم حذفه!'}
        else:
            item = doc.to_dict()
            item['id'] = doc.id
            print(f"✅ تم إيجاد المنتج في Firebase: {item.get('item_name')}")

        # 2. التحقق من أن المنتج لم يُباع
        if item.get('sold', False):
            return {'status': 'error', 'message': 'عذراً، هذا المنتج تم بيعه للتو! 🚫'}

        price = float(item.get('price', 0))

        # 3. التحقق من رصيد المشتري (من Firebase مباشرة)
        user_ref = db.collection('users').document(buyer_id)
        user_doc = user_ref.get()
        current_balance = user_doc.to_dict().get('balance', 0.0) if user_doc.exists else 0.0

        if current_balance < price:
            return {'status': 'error', 'message': 'رصيدك غير كافي للشراء!'}

        # 4. تنفيذ العملية (خصم + تحديث حالة المنتج)
        # نستخدم batch لضمان تنفيذ كل الخطوات معاً أو فشلها معاً
        batch = db.batch()

        # خصم الرصيد
        new_balance = current_balance - price
        batch.update(user_ref, {'balance': new_balance})

        # تحديث المنتج كمباع (تأكد من استخدام document reference الصحيح)
        product_doc_ref = db.collection('products').document(item_id)
        batch.set(product_doc_ref, {
            'sold': True,
            'buyer_id': buyer_id,
            'buyer_name': buyer_name,
            'sold_at': firestore.SERVER_TIMESTAMP
        }, merge=True)

        # حفظ الطلب
        order_id = f"ORD_{random.randint(100000, 999999)}"
        order_ref = db.collection('orders').document(order_id)
        batch.set(order_ref, {
            'buyer_id': buyer_id,
            'buyer_name': buyer_name,
            'item_name': item.get('item_name'),
            'price': price,
            'hidden_data': item.get('hidden_data'),
            'seller_id': item.get('seller_id'),
            'status': 'completed',
            'created_at': firestore.SERVER_TIMESTAMP
        })

        # تنفيذ التغييرات
        batch.commit()

        # 5. تحديث الذاكرة المحلية (اختياري لكن جيد للسرعة)
        users_wallets[buyer_id] = new_balance
        # البحث عن المنتج في القائمة المحلية وتحديثه
        for prod in marketplace_items:
            if prod.get('id') == item_id:
                prod['sold'] = True
                break

        # 6. إرسال المنتج للمشتري
        try:
            hidden_info = item.get('hidden_data', 'لا توجد بيانات')
            bot.send_message(
                int(buyer_id),
                f"✅ **تم الشراء بنجاح!**\n\n"
                f"📦 المنتج: {item.get('item_name')}\n"
                f"💰 السعر: {price} ريال\n"
                f"🆔 رقم الطلب: #{order_id}\n\n"
                f"🔐 **بياناتك:**\n`{hidden_info}`",
                parse_mode="Markdown"
            )
            
            # إشعار للمالك
            bot.send_message(
                ADMIN_ID,
                f"🔔 **عملية بيع جديدة!**\n"
                f"📦 المنتج: {item.get('item_name')}\n"
                f"👤 المشتري: {buyer_name}\n"
                f"💰 السعر: {price} ريال"
            )
        except Exception as e:
            print(f"⚠️ فشل إرسال الرسالة: {e}")

        return {'status': 'success'}

    except Exception as e:
        print(f"❌ Error in buy_item: {e}")
        return {'status': 'error', 'message': 'حدث خطأ أثناء الشراء، حاول مرة أخرى.'}

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

# مسار لرفع البيانات إلى Firebase (للمالك فقط)
@app.route('/migrate_to_firebase')
def migrate_to_firebase_route():
    # التحقق من أن المستخدم هو المالك (يمكنك إضافة password parameter)
    password = request.args.get('password', '')
    admin_password = os.environ.get('ADMIN_PASS', 'admin123')
    
    if password != admin_password:
        return {'status': 'error', 'message': 'غير مصرح'}, 403
    
    # تنفيذ الرفع
    success = migrate_data_to_firebase()
    
    if success:
        return {
            'status': 'success',
            'message': 'تم رفع البيانات بنجاح إلى Firebase',
            'data': {
                'products': len(marketplace_items),
                'users': len(users_wallets),
                'orders': len(active_orders),
                'keys': len(charge_keys)
            }
        }, 200
    else:
        return {'status': 'error', 'message': 'فشل رفع البيانات'}, 500

# صفحة تسجيل الدخول للوحة التحكم (HTML منفصل)
LOGIN_HTML = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>دخول المالك</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-box {
            background: white;
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            max-width: 400px;
            width: 90%;
        }
        h1 { color: #667eea; margin-bottom: 30px; text-align: center; }
        input {
            width: 100%;
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 16px;
            margin-bottom: 20px;
            text-align: center;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.3s;
        }
        button:hover { transform: scale(1.05); }
        .error { color: red; text-align: center; margin-top: 15px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🔐 دخول الآدمن</h1>
        <form method="POST">
            <input type="password" name="pass" placeholder="كلمة المرور" required autofocus>
            <button type="submit">دخول</button>
        </form>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
    </div>
</body>
</html>
"""

# لوحة التحكم للمالك (محدثة بنظام Session آمن)
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    # 1. إذا أرسل المستخدم الباسورد (ضغط زر دخول)
    if request.method == 'POST':
        password = request.form.get('pass', '')
        admin_password = os.environ.get('ADMIN_PASS', 'admin123')
        
        if password == admin_password:
            session['is_admin'] = True  # حفظ حالة الدخول في الجلسة
            return redirect('/dashboard')  # إعادة توجيه لرابط نظيف
        else:
            return render_template_string(LOGIN_HTML, error="❌ كلمة مرور خاطئة!")
    
    # 2. إذا كان المستخدم مسجل دخول مسبقاً (في الجلسة)
    if not session.get('is_admin'):
        # إذا لم يكن مسجل دخول -> عرض صفحة الدخول
        return render_template_string(LOGIN_HTML, error="")
    
    # 3. المستخدم مسجل دخول -> عرض لوحة التحكم
    
    # --- جلب الإحصائيات الحقيقية من Firebase ---
    try:
        # عدد المستخدمين
        users_ref = db.collection('users')
        total_users = len(list(users_ref.stream()))
        
        # مجموع الأرصدة (يحتاج لعمل Loop)
        total_balance = 0
        for user in users_ref.stream():
            total_balance += user.to_dict().get('balance', 0)

        # المنتجات
        products_ref = db.collection('products')
        all_products = list(products_ref.stream())
        total_products = len(all_products)
        
        # حساب المباع والمتاح
        sold_products = 0
        available_products = 0
        for p in all_products:
            p_data = p.to_dict()
            if p_data.get('sold'):
                sold_products += 1
            else:
                available_products += 1
                
        # الطلبات (Orders)
        orders_ref = db.collection('orders')
        # نجلب آخر 10 طلبات فقط للعرض
        recent_orders_docs = orders_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(10).stream()
        recent_orders = []
        for doc in recent_orders_docs:
            data = doc.to_dict()
            # تنسيق البيانات للعرض في الجدول
            recent_orders.append((
                doc.id[:8], # رقم طلب قصير
                {
                    'item_name': data.get('item_name', 'منتج'),
                    'price': data.get('price', 0),
                    'buyer_name': data.get('buyer_name', 'مشتري')
                }
            ))

        # المفاتيح - جلبها من Firebase مباشرة
        keys_ref = db.collection('charge_keys')
        all_keys_docs = list(keys_ref.stream())
        
        # تحضير قائمة المفاتيح للعرض
        charge_keys_display = {}
        active_keys = 0
        used_keys = 0
        
        for k in all_keys_docs:
            data = k.to_dict()
            key_code = k.id
            is_used = data.get('used', False)
            
            if is_used:
                used_keys += 1
            else:
                active_keys += 1
            
            charge_keys_display[key_code] = data
        
        # إجمالي الطلبات
        total_orders = len(list(orders_ref.stream()))
        
        # جلب آخر 20 مستخدم للعرض في الجدول
        users_list = []
        for user_doc in users_ref.limit(20).stream():
            user_data = user_doc.to_dict()
            users_list.append((user_doc.id, user_data.get('balance', 0)))

    except Exception as e:
        print(f"Error loading stats from Firebase: {e}")
        # قيم افتراضية عند الخطأ
        total_users = 0
        total_balance = 0
        total_products = 0
        available_products = 0
        sold_products = 0
        total_orders = 0
        recent_orders = []
        users_list = []
        active_keys = len([k for k, v in charge_keys.items() if not v.get('used', False)])
        used_keys = len([k for k, v in charge_keys.items() if v.get('used', False)])
        charge_keys_display = charge_keys
    
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة التحكم - المالك</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                min-height: 100vh;
                padding: 20px;
                color: #333;
            }}
            .container {{
                max-width: 1400px;
                margin: 0 auto;
            }}
            .header {{
                background: white;
                padding: 20px 30px;
                border-radius: 15px;
                margin-bottom: 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            }}
            .header h1 {{ color: #667eea; font-size: 28px; }}
            .logout-btn {{
                background: #e74c3c;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }}
            .stat-card {{
                background: white;
                padding: 20px;
                border-radius: 15px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                text-align: center;
            }}
            .stat-card .icon {{ font-size: 40px; margin-bottom: 10px; }}
            .stat-card .value {{ font-size: 32px; font-weight: bold; color: #667eea; }}
            .stat-card .label {{ color: #888; margin-top: 5px; }}
            .section {{
                background: white;
                padding: 25px;
                border-radius: 15px;
                margin-bottom: 20px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            }}
            .section h2 {{ color: #667eea; margin-bottom: 20px; border-bottom: 3px solid #667eea; padding-bottom: 10px; }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 12px;
                text-align: right;
                border-bottom: 1px solid #ddd;
            }}
            th {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                font-weight: bold;
            }}
            tr:hover {{ background: #f5f5f5; }}
            .badge {{
                display: inline-block;
                padding: 5px 12px;
                border-radius: 15px;
                font-size: 12px;
                font-weight: bold;
            }}
            .badge-success {{ background: #00b894; color: white; }}
            .badge-danger {{ background: #e74c3c; color: white; }}
            .badge-warning {{ background: #fdcb6e; color: #333; }}
            .badge-info {{ background: #74b9ff; color: white; }}
            .tools {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 15px;
            }}
            .tool-box {{
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                border-left: 4px solid #667eea;
            }}
            .tool-box h3 {{ color: #667eea; margin-bottom: 15px; }}
            .tool-box input, .tool-box select {{
                width: 100%;
                padding: 10px;
                border: 2px solid #ddd;
                border-radius: 8px;
                margin-bottom: 10px;
            }}
            .tool-box button {{
                width: 100%;
                padding: 12px;
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                cursor: pointer;
            }}
            .tool-box button:hover {{ opacity: 0.9; }}
            
            /* نافذة عرض المفاتيح */
            .keys-modal {{
                display: none;
                position: fixed;
                z-index: 9999;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.8);
                animation: fadeIn 0.3s;
            }}
            .keys-modal-content {{
                background: white;
                margin: 5% auto;
                padding: 0;
                border-radius: 15px;
                max-width: 500px;
                width: 90%;
                max-height: 80vh;
                overflow-y: auto;
                animation: slideDown 0.3s;
            }}
            .keys-modal-header {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                padding: 20px;
                border-radius: 15px 15px 0 0;
                color: white;
                text-align: center;
            }}
            .keys-modal-body {{
                padding: 20px;
            }}
            .key-item {{
                background: #f8f9fa;
                padding: 12px;
                border-radius: 8px;
                margin-bottom: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-left: 4px solid #667eea;
            }}
            .key-code {{
                font-family: monospace;
                font-size: 14px;
                color: #333;
                font-weight: bold;
                flex: 1;
                word-break: break-all;
            }}
            .copy-btn {{
                background: #00b894;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 12px;
                font-weight: bold;
                margin-left: 10px;
                transition: all 0.3s;
            }}
            .copy-btn:hover {{ background: #00a383; }}
            .copy-btn.copied {{
                background: #fdcb6e;
                color: #333;
            }}
            .keys-modal-footer {{
                padding: 15px 20px;
                text-align: center;
                border-top: 1px solid #ddd;
            }}
            .close-modal-btn {{
                background: #e74c3c;
                color: white;
                border: none;
                padding: 12px 30px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
                font-size: 14px;
            }}
            @keyframes fadeIn {{
                from {{ opacity: 0; }}
                to {{ opacity: 1; }}
            }}
            @keyframes slideDown {{
                from {{ transform: translateY(-50px); opacity: 0; }}
                to {{ transform: translateY(0); opacity: 1; }}
            }}
        </style>
    </head>
    <body>
        <!-- نافذة عرض المفاتيح -->
        <div id="keysModal" class="keys-modal">
            <div class="keys-modal-content">
                <div class="keys-modal-header">
                    <h2 style="margin: 0; font-size: 20px;">🔑 المفاتيح المولدة</h2>
                    <p style="margin: 10px 0 0 0; font-size: 14px; opacity: 0.9;" id="keysCount"></p>
                </div>
                <div class="keys-modal-body" id="keysContainer">
                    <!-- سيتم إضافة المفاتيح هنا -->
                </div>
                <div class="keys-modal-footer">
                    <button class="close-modal-btn" onclick="closeKeysModal()">إغلاق</button>
                </div>
            </div>
        </div>
        
        <div class="container">
            <div class="header">
                <h1>🎛️ لوحة التحكم - المالك</h1>
                <div style="display: flex; gap: 10px;">
                    <button class="logout-btn" onclick="window.location.href='/logout_admin'" style="background: #e74c3c;">🚪 تسجيل خروج</button>
                    <button class="logout-btn" onclick="window.location.href='/'" style="background: #3498db;">⬅️ الموقع</button>
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="icon">👥</div>
                    <div class="value">{total_users}</div>
                    <div class="label">المستخدمين</div>
                </div>
                <div class="stat-card">
                    <div class="icon">📦</div>
                    <div class="value">{available_products}</div>
                    <div class="label">منتجات متاحة</div>
                </div>
                <div class="stat-card">
                    <div class="icon">✅</div>
                    <div class="value">{sold_products}</div>
                    <div class="label">منتجات مباعة</div>
                </div>
                <div class="stat-card">
                    <div class="icon">🔑</div>
                    <div class="value">{active_keys}</div>
                    <div class="label">مفاتيح نشطة</div>
                </div>
                <div class="stat-card">
                    <div class="icon">🎫</div>
                    <div class="value">{used_keys}</div>
                    <div class="label">مفاتيح مستخدمة</div>
                </div>
                <div class="stat-card">
                    <div class="icon">💰</div>
                    <div class="value">{total_balance:.0f}</div>
                    <div class="label">إجمالي الأرصدة</div>
                </div>
            </div>
            
            <div class="section">
                <h2>️ أدوات سريعة</h2>
                <div class="tools">
                    <div class="tool-box">
                        <h3>💳 شحن رصيد مستخدم</h3>
                        <input type="number" id="userId" placeholder="آيدي المستخدم">
                        <input type="number" id="amount" placeholder="المبلغ">
                        <button onclick="addBalance()">شحن</button>
                    </div>
                    <div class="tool-box">
                        <h3>🔑 توليد مفاتيح شحن</h3>
                        <input type="number" id="keyAmount" placeholder="قيمة المفتاح">
                        <input type="number" id="keyCount" placeholder="عدد المفاتيح" value="1">
                        <button onclick="generateKeys()">توليد</button>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>📋 آخر الطلبات</h2>
                <table>
                    <thead>
                        <tr>
                            <th>رقم الطلب</th>
                            <th>المنتج</th>
                            <th>السعر</th>
                            <th>المشتري</th>
                            <th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f'''
                        <tr>
                            <td>#{order_id}</td>
                            <td>{order['item_name']}</td>
                            <td>{order['price']} ريال</td>
                            <td>{order['buyer_name']}</td>
                            <td><span class="badge badge-success">مكتمل</span></td>
                        </tr>
                        ''' for order_id, order in recent_orders]) if recent_orders else '<tr><td colspan="5" style="text-align: center;">لا توجد طلبات</td></tr>'}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h2>👥 المستخدمين والأرصدة</h2>
                <table>
                    <thead>
                        <tr>
                            <th>آيدي المستخدم</th>
                            <th>الرصيد</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f'''
                        <tr>
                            <td>{user_id}</td>
                            <td>{balance:.2f} ريال</td>
                        </tr>
                        ''' for user_id, balance in users_list]) if users_list else '<tr><td colspan="2" style="text-align: center;">لا يوجد مستخدمين</td></tr>'}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h2>🔑 المفاتيح النشطة</h2>
                <table>
                    <thead>
                        <tr>
                            <th>المفتاح</th>
                            <th>القيمة</th>
                            <th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"""
                        <tr>
                            <td><code>{key_code}</code></td>
                            <td>{key_data.get('amount', 0)} ريال</td>
                            <td><span class="badge {'badge-success' if not key_data.get('used', False) else 'badge-danger'}">{'نشط' if not key_data.get('used', False) else f"مستخدم"}</span></td>
                        </tr>
                        """ for key_code, key_data in list(charge_keys_display.items())[:20]]) if charge_keys_display else '<tr><td colspan="3" style="text-align: center;">لا توجد مفاتيح</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
        
        <script>
            function addBalance() {{
                const userId = document.getElementById('userId').value;
                const amount = document.getElementById('amount').value;
                
                if(!userId || !amount) {{
                    alert('الرجاء ملء جميع الحقول!');
                    return;
                }}
                
                fetch('/api/add_balance', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{user_id: userId, amount: parseFloat(amount)}})
                }})
                .then(r => r.json())
                .then(data => {{
                    if(data.status === 'success') {{
                        alert('✅ تم شحن الرصيد بنجاح!');
                        location.reload();
                    }} else {{
                        alert('❌ ' + data.message);
                    }}
                }});
            }}
            
            function generateKeys() {{
                const amount = document.getElementById('keyAmount').value;
                const count = document.getElementById('keyCount').value;
                
                if(!amount || !count) {{
                    alert('الرجاء ملء جميع الحقول!');
                    return;
                }}
                
                fetch('/api/generate_keys', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{amount: parseFloat(amount), count: parseInt(count)}})
                }})
                .then(r => r.json())
                .then(data => {{
                    if(data.status === 'success') {{
                        showKeysModal(data.keys, amount);
                    }} else {{
                        alert('❌ ' + data.message);
                    }}
                }});
            }}
            
            function showKeysModal(keys, amount) {{
                const modal = document.getElementById('keysModal');
                const container = document.getElementById('keysContainer');
                const countText = document.getElementById('keysCount');
                
                countText.textContent = 'تم توليد ' + keys.length + ' مفتاح بقيمة ' + amount + ' ريال لكل منها';
                
                container.innerHTML = '';
                keys.forEach((key, index) => {{
                    const keyItem = document.createElement('div');
                    keyItem.className = 'key-item';
                    keyItem.innerHTML = '<div class="key-code">' + key + '</div>' +
                        '<button class="copy-btn" onclick="copyKey(\'' + key + '\', this)">📋 نسخ</button>';
                    container.appendChild(keyItem);
                }});
                
                modal.style.display = 'block';
            }}
            
            function copyKey(key, btn) {{
                navigator.clipboard.writeText(key).then(() => {{
                    btn.textContent = '✅ تم النسخ';
                    btn.classList.add('copied');
                    setTimeout(() => {{
                        btn.textContent = '📋 نسخ';
                        btn.classList.remove('copied');
                    }}, 2000);
                }}).catch(err => {{
                    alert('فشل النسخ: ' + err);
                }});
            }}
            
            function closeKeysModal() {{
                document.getElementById('keysModal').style.display = 'none';
                location.reload();
            }}
            
            window.onclick = function(event) {{
                const modal = document.getElementById('keysModal');
                if(event.target == modal) {{
                    closeKeysModal();
                }}
            }}
        </script>
    </body>
    </html>
    """

# API لشحن رصيد من لوحة التحكم
@app.route('/api/add_balance', methods=['POST'])
def api_add_balance():
    data = request.json
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount'))
    
    if not user_id or amount <= 0:
        return {'status': 'error', 'message': 'بيانات غير صحيحة'}
    
    add_balance(user_id, amount)
    
    # إشعار المستخدم
    try:
        bot.send_message(int(user_id), f"🎉 تم شحن رصيدك بمبلغ {amount} ريال!")
    except:
        pass
    
    return {'status': 'success'}

# --- API لإضافة منتج (مصحح للحفظ في Firebase) ---
@app.route('/api/add_product', methods=['POST'])
def api_add_product():
    try:
        data = request.json
        name = data.get('name')
        price = data.get('price')
        category = data.get('category')
        details = data.get('details', '')
        image = data.get('image', '')
        hidden_data = data.get('hidden_data')
        
        # التحقق من البيانات
        if not name or not price or not hidden_data:
            return {'status': 'error', 'message': 'بيانات غير كاملة'}
        
        # إنشاء بيانات المنتج
        new_id = str(uuid.uuid4())
        item = {
            'id': new_id,
            'item_name': name,
            'price': float(price),
            'seller_id': str(ADMIN_ID),
            'seller_name': 'المالك',
            'hidden_data': hidden_data,
            'category': category,
            'details': details,
            'image_url': image,
            'sold': False,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        
        # 1. الحفظ في Firebase (المهم)
        db.collection('products').document(new_id).set(item)
        print(f"✅ تم حفظ المنتج {new_id} في Firestore: {name}")
        
        # 2. تحديث الذاكرة المحلية (للعرض السريع)
        marketplace_items.append(item)
        print(f"✅ تم إضافة المنتج للذاكرة. إجمالي المنتجات: {len(marketplace_items)}")
        
        # 3. إشعار المالك (داخل try/except لضمان عدم توقف العملية)
        try:
            bot.send_message(
                ADMIN_ID,
                f"✅ **تم إضافة منتج جديد**\n📦 {name}\n💰 {price} ريال",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"فشل إرسال الإشعار: {e}")
            
        return {'status': 'success', 'message': 'تم الحفظ في قاعدة البيانات'}

    except Exception as e:
        print(f"Error in add_product: {e}")
        return {'status': 'error', 'message': f'حدث خطأ في السيرفر: {str(e)}'}

# --- API لتوليد المفاتيح (مصحح للحفظ في Firebase) ---
@app.route('/api/generate_keys', methods=['POST'])
def api_generate_keys():
    try:
        data = request.json
        amount = float(data.get('amount'))
        count = int(data.get('count', 1))
        
        if amount <= 0 or count <= 0 or count > 100:
            return {'status': 'error', 'message': 'أرقام غير صحيحة'}
        
        generated_keys = []
        batch = db.batch() # استخدام الدفعات للحفظ السريع
        
        for _ in range(count):
            # إنشاء كود عشوائي
            key_code = f"KEY-{random.randint(10000, 99999)}-{random.randint(1000, 9999)}"
            
            key_data = {
                'amount': amount,
                'used': False,
                'used_by': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            # تجهيز الحفظ في Firebase
            doc_ref = db.collection('charge_keys').document(key_code)
            batch.set(doc_ref, key_data)
            
            # تحديث الذاكرة
            charge_keys[key_code] = key_data
            generated_keys.append(key_code)
            
        # تنفيذ الحفظ في Firebase دفعة واحدة
        batch.commit()
        
        return {'status': 'success', 'keys': generated_keys}

    except Exception as e:
        print(f"Error generating keys: {e}")
        return {'status': 'error', 'message': f'فشل التوليد: {str(e)}'}

# مسار لتسجيل خروج الآدمن
@app.route('/logout_admin')
def logout_admin():
    session.pop('is_admin', None)
    return redirect('/dashboard')

if __name__ == "__main__":
    # تحميل البيانات من Firebase عند بدء التشغيل
    print("🚀 بدء تشغيل التطبيق...")
    load_data_from_firebase()
    
    # التأكد من أن جميع المنتجات لديها UUID
    ensure_product_ids()
    
    # هذا السطر يجعل البوت يعمل على المنفذ الصحيح في ريندر أو 10000 في جهازك
    port = int(os.environ.get("PORT", 10000))
    print(f"✅ التطبيق يعمل على المنفذ {port}")
    app.run(host="0.0.0.0", port=port)
