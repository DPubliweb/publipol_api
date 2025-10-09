from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/ciblage", methods=["POST"])
def handle_ciblage():
    try:
        data = request.get_json(force=True)
        print("📥 /ciblage reçu :", data)
        return jsonify({"status": "success", "message": "Ciblage bien reçu"}), 200
    except Exception as e:
        print("❌ Erreur /ciblage :", e)
        return jsonify({"status": "error", "message": "JSON invalide"}), 400

@app.route("/commande", methods=["POST"])
def handle_commande():
    try:
        data = request.get_json(force=True)
        print("📥 /commande reçu :", data)
        return jsonify({"status": "success", "message": "Commande bien reçue"}), 200
    except Exception as e:
        print("❌ Erreur /commande :", e)
        return jsonify({"status": "error", "message": "JSON invalide"}), 400

@app.route("/facture", methods=["POST"])
def handle_facture():
    try:
        data = request.get_json(force=True)
        print("📥 /facture reçu :", data)
        return jsonify({"status": "success", "message": "Facture bien reçue"}), 200
    except Exception as e:
        print("❌ Erreur /facture :", e)
        return jsonify({"status": "error", "message": "JSON invalide"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8002)
