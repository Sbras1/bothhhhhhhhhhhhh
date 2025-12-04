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

        /* تحسين مظهر الكروت */
        .card {
            background: var(--card-bg);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            animation: fadeIn 0.5s ease-in-out;
        }

        /* قسم المعلومات الشخصية */
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

        /* حقول الإدخال */
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

        /* زر البيع */
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

        /* قائمة المنتجات */
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
        
        .price-tag {
            background-color: rgba(108, 92, 231, 0.15);
            color: #a29bfe;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9rem;
        }

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
                <div class="price-tag">{{ item.price }} ريال</div>
            </div>
            {% endfor %}
        {% endif %}
    </div>

    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();

        // ألوان التطبيق بناءً على ثيم المستخدم
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

            // زر تحميل
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