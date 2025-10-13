from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import uuid

load_dotenv()

API_KEY = os.getenv("API_KEY")

app = Flask(__name__)

# Middleware de vérification d'API key
@app.before_request
def verify_api_key():
    key = request.headers.get("x-api-key")
    if not key or key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json()
    if not data or "geo_selection" not in data:
        return jsonify({"error": "Missing geo_selection"}), 400
    # Logique de ciblage (placeholder)
    return jsonify({"message": "Ciblage reçu avec succès", "count": 8500})

@app.route("/tarification", methods=["POST"])
def tarification():
    data = request.get_json()
    required_fields = ["contacts", "sms", "lp"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    # Logique de tarification (placeholder)
    montant = 0.08 * data["contacts"] * data["sms"]
    if data["lp"]:
        montant += 0.02 * data["contacts"]
    return jsonify({"tarif_total": round(montant, 2)})

@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing payload"}), 400

    for section in ["candidat", "mandataire", "lp"]:
        if section not in data:
            return jsonify({"error": f"Missing section: {section}"}), 400

    # Génération ID de commande unique
    commande_id = str(uuid.uuid4())

    # Logique de sauvegarde de commande (placeholder)
    return jsonify({"message": "Commande créée avec succès", "commande_id": commande_id}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8002)
