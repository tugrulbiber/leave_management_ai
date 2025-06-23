from flask import Flask, request, jsonify
import joblib
import psycopg2
import time

app = Flask(__name__)

# Model ve encoder'ları yükle
model = joblib.load("leave_model.pkl")
le_role = joblib.load("role_encoder.pkl")
le_leave_type = joblib.load("leave_type_encoder.pkl")
le_status = joblib.load("status_encoder.pkl")

# PostgreSQL bağlantısını retry mekanizmasıyla kur
conn = None
for i in range(10):
    try:
        conn = psycopg2.connect(
            host="postgres-db",
            port=5432,
            database="leave_management_db",
            user="postgres",
            password="123"
        )
        print("✅ Veritabanına bağlantı başarılı.")
        break
    except psycopg2.OperationalError:
        print(f"🔁 Veritabanı hazır değil, tekrar deneniyor... ({i+1}/10)")
        time.sleep(3)
else:
    print("❌ Veritabanına bağlanılamadı. Çıkılıyor.")
    exit(1)

from datetime import datetime, timedelta


@app.route("/predict", methods=["POST"])
def predict():
    data = request.get_json()

    try:
        user_id = data["user_id"]
        leave_type = data["leave_type"]

        # Tarihleri al ve duration hesapla
        start_date = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
        end_date = datetime.strptime(data["end_date"], "%Y-%m-%d").date()

        if end_date < start_date:
            return jsonify({"error": "Bitiş tarihi, başlangıç tarihinden önce olamaz."}), 400

        duration = (end_date - start_date).days + 1

        cursor = conn.cursor()

        # Kullanıcının rolünü ve ofisini al
        cursor.execute("SELECT role, office_id FROM users WHERE id_user = %s", (user_id,))
        user_result = cursor.fetchone()
        if not user_result:
            return jsonify({"error": "Kullanıcı bulunamadı."}), 404
        role, office_id = user_result

        # Kullanıcının izin bakiyesi
        cursor.execute("""
            SELECT used_days, remaining_days
            FROM leave_balances
            WHERE user_id = %s
        """, (user_id,))
        balance_result = cursor.fetchone()
        if not balance_result:
            return jsonify({"error": "İzin bakiyesi bulunamadı."}), 404
        used_days, remaining_days = balance_result

        # Bakiye yetersizse
        if remaining_days < duration:
            cursor.execute("""
                INSERT INTO ai_predictions (user_id, leave_type, duration, used_days, remaining_days, prediction)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, leave_type, duration, used_days, remaining_days, "REJECTED"))
            conn.commit()
            return jsonify({"prediction": "REJECTED (bakiye yetersiz)"}), 200

        # %50 kontrolü – artık CURRENT_DATE yerine start_date ile yapılır
        cursor.execute("SELECT COUNT(*) FROM users WHERE office_id = %s", (office_id,))
        total_employees = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM leave_requests
            WHERE status = 'APPROVED'
              AND start_date <= %s
              AND end_date >= %s
              AND user_id IN (SELECT id_user FROM users WHERE office_id = %s)
        """, (start_date, start_date, office_id))
        approved_on_that_day = cursor.fetchone()[0]

        if approved_on_that_day >= (total_employees / 2):
            cursor.execute("""
                INSERT INTO ai_predictions (user_id, leave_type, duration, used_days, remaining_days, prediction)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, leave_type, duration, used_days, remaining_days, "REJECTED"))
            conn.commit()
            return jsonify({"prediction": "REJECTED (ofiste %50 sınırı aşıldı)"}), 200

        # Encode işlemi
        role_encoded = le_role.transform([role])[0]
        leave_type_encoded = le_leave_type.transform([leave_type])[0]

        features = [[user_id, role_encoded, leave_type_encoded, duration, used_days, remaining_days]]
        prediction = model.predict(features)[0]
        prediction_label = le_status.inverse_transform([prediction])[0]

        # Tahmini kaydet
        cursor.execute("""
            INSERT INTO ai_predictions (user_id, leave_type, duration, used_days, remaining_days, prediction)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, leave_type, duration, used_days, remaining_days, prediction_label))
        conn.commit()

        return jsonify({"prediction": prediction_label})

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/ai/suggest/next", methods=["GET"])
def suggest_next_available_dates():
    try:
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id zorunludur."}), 400

        user_id = int(user_id)
        cursor = conn.cursor()

        # Kullanıcının ofisini al
        cursor.execute("SELECT office_id FROM users WHERE id_user = %s", (user_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Kullanıcı bulunamadı."}), 404
        office_id = result[0]

        # Ofisteki toplam çalışan sayısı
        cursor.execute("SELECT COUNT(*) FROM users WHERE office_id = %s", (office_id,))
        total_employees = cursor.fetchone()[0]

        suggested = []
        current = datetime.today().date()

        while len(suggested) < 7:
            cursor.execute("""
                SELECT COUNT(*) FROM leave_requests
                WHERE status = 'APPROVED'
                  AND start_date <= %s
                  AND end_date >= %s
                  AND user_id IN (
                      SELECT id_user FROM users WHERE office_id = %s
                  )
            """, (current, current, office_id))
            count = cursor.fetchone()[0]
            if count < (total_employees / 2):
                suggested.append(str(current))
            current += timedelta(days=1)

        return jsonify({
            "suggested_dates": suggested,
            "limit": 7,
            "starting_from": str(datetime.today().date())
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/suggest-dates/range", methods=["POST"])
def suggest_dates_in_range():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        start = data.get("start_date")
        end = data.get("end_date")

        if not user_id or not start or not end:
            return jsonify({"error": "user_id, start_date ve end_date zorunludur."}), 400

        user_id = int(user_id)
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()

        if end_date < start_date:
            return jsonify({"error": "Bitiş tarihi, başlangıç tarihinden önce olamaz."}), 400

        cursor = conn.cursor()

        # Kullanıcının ofisini al
        cursor.execute("SELECT office_id FROM users WHERE id_user = %s", (user_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Kullanıcı bulunamadı."}), 404
        office_id = result[0]

        # Ofisteki toplam çalışan sayısı
        cursor.execute("SELECT COUNT(*) FROM users WHERE office_id = %s", (office_id,))
        total_employees = cursor.fetchone()[0]

        suggested = []
        current = start_date

        while current <= end_date and len(suggested) < 7:
            cursor.execute("""
                SELECT COUNT(*) FROM leave_requests
                WHERE status = 'APPROVED'
                  AND start_date <= %s
                  AND end_date >= %s
                  AND user_id IN (
                      SELECT id_user FROM users WHERE office_id = %s
                  )
            """, (current, current, office_id))
            count = cursor.fetchone()[0]
            if count < (total_employees / 2):
                suggested.append(str(current))
            current += timedelta(days=1)

        return jsonify({
            "suggested_dates": suggested,
            "limit": 7,
            "range": f"{start_date} → {end_date}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/ai/retrain", methods=["POST"])
def retrain_model():
    global model, le_leave_type, le_status  # EN BAŞTA OLMALI

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, leave_type, duration, used_days, remaining_days, prediction
            FROM ai_predictions
        """)
        rows = cursor.fetchall()

        if not rows:
            return jsonify({"error": "Yeniden eğitim için veri bulunamadı."}), 400

        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import LabelEncoder

        df = pd.DataFrame(rows, columns=[
            "user_id", "leave_type", "duration", "used_days", "remaining_days", "status"
        ])

        le_leave_type = LabelEncoder()
        le_status = LabelEncoder()

        df["leave_type_enc"] = le_leave_type.fit_transform(df["leave_type"])
        df["status_enc"] = le_status.fit_transform(df["status"])
        df["role_enc"] = 1  # Dummy değer (gerekirse role da kullanabilirsin)

        X = df[["user_id", "role_enc", "leave_type_enc", "duration", "used_days", "remaining_days"]]
        y = df["status_enc"]

        model = RandomForestClassifier()
        model.fit(X, y)

        joblib.dump(model, "leave_model.pkl")
        joblib.dump(le_leave_type, "leave_type_encoder.pkl")
        joblib.dump(le_status, "status_encoder.pkl")

        # Yeni modeli belleğe tekrar yükle
        model = joblib.load("leave_model.pkl")
        le_leave_type = joblib.load("leave_type_encoder.pkl")
        le_status = joblib.load("status_encoder.pkl")

        return jsonify({"message": "✅ Model başarıyla yeniden eğitildi."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai/stats", methods=["GET"])
def ai_stats():
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT leave_type, COUNT(*) AS count
            FROM ai_predictions
            GROUP BY leave_type
            ORDER BY count DESC
            LIMIT 1
        """)
        top_leave_type = cursor.fetchone()

        cursor.execute("""
            SELECT prediction, COUNT(*) AS count
            FROM ai_predictions
            GROUP BY prediction
        """)
        prediction_counts = cursor.fetchall()
        prediction_summary = {row[0]: row[1] for row in prediction_counts}

        cursor.execute("""
            SELECT user_id, COUNT(*) AS count
            FROM ai_predictions
            GROUP BY user_id
            ORDER BY count DESC
            LIMIT 1
        """)
        top_user = cursor.fetchone()

        stats = {
            "top_leave_type": {
                "leave_type": top_leave_type[0],
                "count": top_leave_type[1]
            },
            "prediction_summary": prediction_summary,
            "most_predicted_user": {
                "user_id": top_user[0],
                "count": top_user[1]
            }
        }

        return jsonify(stats)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
