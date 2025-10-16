from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import uuid
import psycopg2


API_KEY = os.getenv("API_KEY")

app = Flask(__name__)
CORS(app)

# Middleware for API key authentication
@app.before_request
def authenticate():
    if request.path.startswith('/ciblage') or request.path.startswith('/commande'):
        api_key = request.headers.get('x-api-key')
        if api_key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

@app.route("/test-redshift")
def test_redshift():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("REDSHIFT_DBNAME"),
            user=os.getenv("REDSHIFT_USER"),
            password=os.getenv("REDSHIFT_PASSWORD"),
            host=os.getenv("REDSHIFT_HOST"),
            port=os.getenv("REDSHIFT_PORT", 5439)
        )
        cur = conn.cursor()
        cur.execute("SELECT current_date;")
        result = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "success ✅", "current_date": result[0]})
    except Exception as e:
        return jsonify({"status": "error ❌", "message": str(e)})
    

@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json()
    required_fields = ["geo_selection", "type_selection", "departement"]
    
    missing_fields = [f for f in required_fields if f not in data]
    if missing_fields:
        return jsonify({"error": f"Missing fields: {', '.join(missing_fields)}"}), 400

    # Exemple de réponse simulée
    response = {
        "nombre_contacts": 8500,
        "departement": data["departement"],
        "type_selection": data["type_selection"],
        "geo_selection": data["geo_selection"]
    }
    return jsonify(response)

@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()

    required_fields = [
        # Candidat
        "candidat_nom", "candidat_prenom", "candidat_id_paralos",
        "candidat_adresse", "candidat_cp", "candidat_ville",
        "candidat_tel1", "candidat_email",
        # Mandataire
        "mandataire_nom", "mandataire_prenom",
        "mandataire_adresse", "mandataire_cp", "mandataire_ville",
        "mandataire_tel1", "mandataire_email",
        # LP
        "lp_active", "type_lp", "photo_url", "profession_de_foi_url", "bulletin_url",
        # Tarification
        "nombre_contacts", "sms_count", "prix_total"
    ]

    missing_fields = [f for f in required_fields if f not in data]
    if missing_fields:
        return jsonify({"error": f"Missing fields: {', '.join(missing_fields)}"}), 400

    commande_id = str(uuid.uuid4())

    return jsonify({
        "commande_id": commande_id,
        "statut": "reçue",
        "details": {
            "candidat": {
                "nom": data["candidat_nom"],
                "prenom": data["candidat_prenom"]
            },
            "mandataire": {
                "nom": data["mandataire_nom"],
                "prenom": data["mandataire_prenom"]
            },
            "lp": {
                "active": data["lp_active"],
                "type_lp": data["type_lp"]
            },
            "tarification": {
                "contacts": data["nombre_contacts"],
                "sms": data["sms_count"],
                "prix": data["prix_total"]
            }
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))  # valeur par défaut 8002 en local
    app.run(host="0.0.0.0", port=port, debug=True)

