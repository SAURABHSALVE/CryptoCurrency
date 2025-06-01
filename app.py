import os
import datetime
import requests
import openai
from flask import Flask, render_template, jsonify, request
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv

# ─── Load environment variables ───────────────────────────────────────────────
load_dotenv()  # loads variables from .env into os.environ

app = Flask(__name__)

MONGO_URI = os.getenv("MONGO_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not MONGO_URI or not OPENAI_API_KEY:
    raise RuntimeError("Please set MONGO_URI and OPENAI_API_KEY in the .env file.")

openai.api_key = OPENAI_API_KEY

# ─── Connect to MongoDB ───────────────────────────────────────────────────────
client = MongoClient(MONGO_URI)
db = client.get_default_database()  # database name from URI (crypto_tracker)

portfolio_col = db.get_collection("portfolio")
alerts_col = db.get_collection("alerts")


# 3) A small helper: fetch live prices from CoinGecko (no API key needed).
COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"


def get_live_prices(coin_ids, vs_currency="usd"):
    """
    coin_ids: list of CoinGecko IDs, e.g. ["bitcoin", "ethereum", "ripple"]
    Returns a dict: { "bitcoin": {"usd": 27345.12}, "ethereum": {"usd": 1845.33}, ... }
    """
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": vs_currency
    }
    resp = requests.get(COINGECKO_SIMPLE_PRICE_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ─── Routes: Render pages ──────────────────────────────────────────────────────

@app.route("/")
def root():
    return render_template("dashboard.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/portfolio")
def portfolio_page():
    return render_template("portfolio.html")


@app.route("/compare")
def compare_page():
    return render_template("compare.html")


@app.route("/alerts")
def alerts_page():
    return render_template("alerts.html")


# ─── API Endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/prices", methods=["GET"])
def api_prices():
    """
    Query string: ?coins=bitcoin,ethereum,ripple,...
    Returns: { "bitcoin": {"usd": 27234.12}, "ethereum": {"usd": 1845.33}, ... }
    """
    coin_list = request.args.get("coins", "")
    if coin_list.strip() == "":
        return jsonify({"error": "No coins specified."}), 400

    coin_ids = [c.strip().lower() for c in coin_list.split(",")]
    try:
        prices = get_live_prices(coin_ids)
        return jsonify(prices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/market_summary", methods=["GET"])
def api_market_summary():
    """
    1) Fetches live prices for a fixed set of popular coins. 
    2) Sends a prompt to OpenAI to generate a short market summary.
    Returns: { "summary": "<generated text>" }
    """
    # You can customize which coins to show by default
    default_coins = ["bitcoin", "ethereum", "ripple", "litecoin", "dogecoin"]
    try:
        prices = get_live_prices(default_coins)
    except Exception as e:
        return jsonify({"error": "Failed to fetch live prices: " + str(e)}), 500

    # Build a prompt that includes current prices.
    market_lines = []
    for coin in default_coins:
        price_usd = prices.get(coin, {}).get("usd", None)
        if price_usd is not None:
            market_lines.append(f"- {coin.capitalize()}: ${price_usd:,.2f}")
        else:
            market_lines.append(f"- {coin.capitalize()}: (price unavailable)")

    prompt = (
        "You are a cryptocurrency market analyst. "
        "Here are the current prices for some major coins (all in USD):\n\n"
        + "\n".join(market_lines)
        + "\n\n"
        "Please write a 2–3 sentence summary of the current market situation, "
        "mention any notable movements or trends, and keep it concise."
    )

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a crypto market summary generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        summary_text = completion.choices[0].message.content.strip()
        return jsonify({"summary": summary_text})
    except Exception as e:
        return jsonify({"error": "OpenAI API error: " + str(e)}), 500


# ─ Portfolio CRUD ──────────────────────────────────────────────────────────────

@app.route("/api/portfolio", methods=["GET"])
def api_get_portfolio():
    """
    Returns all portfolio items as a list.
    Each item: { "_id": <id>, "coin": <string>, "amount": <number> }
    """
    items = []
    for doc in portfolio_col.find():
        items.append({
            "_id": str(doc["_id"]),
            "coin": doc["coin"],
            "amount": doc["amount"]
        })
    return jsonify(items)


@app.route("/api/portfolio", methods=["POST"])
def api_add_portfolio():
    """
    Expect JSON body: { "coin": <coin_id>, "amount": <number> }
    If coin already exists, update amount; else insert new.
    """
    data = request.get_json(force=True)
    coin   = data.get("coin", "").strip().lower()
    amount = data.get("amount", None)

    if not coin or amount is None:
        return jsonify({"error": "Both 'coin' and 'amount' are required."}), 400

    try:
        amount = float(amount)
    except ValueError:
        return jsonify({"error": "'amount' must be a number."}), 400

    existing = portfolio_col.find_one({"coin": coin})
    if existing:
        portfolio_col.update_one({"_id": existing["_id"]}, {"$set": {"amount": amount}})
    else:
        portfolio_col.insert_one({"coin": coin, "amount": amount})

    return jsonify({"status": "success"}), 200


@app.route("/api/portfolio/<id>", methods=["DELETE"])
def api_delete_portfolio(id):
    """
    Delete one portfolio item by its ObjectId.
    """
    try:
        portfolio_col.delete_one({"_id": ObjectId(id)})
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─ Compare Two Coins ────────────────────────────────────────────────────────────

@app.route("/api/compare", methods=["GET"])
def api_compare():
    """
    Query params: ?coin1=bitcoin&coin2=ethereum
    Returns json with both prices and the difference.
    """
    coin1 = request.args.get("coin1", "").strip().lower()
    coin2 = request.args.get("coin2", "").strip().lower()

    if not coin1 or not coin2:
        return jsonify({"error": "Both 'coin1' and 'coin2' are required."}), 400

    try:
        prices = get_live_prices([coin1, coin2])
    except Exception as e:
        return jsonify({"error": "Failed to fetch live prices: " + str(e)}), 500

    price1 = prices.get(coin1, {}).get("usd", None)
    price2 = prices.get(coin2, {}).get("usd", None)
    if price1 is None or price2 is None:
        return jsonify({"error": "One or both coin IDs are invalid/unavailable."}), 400

    diff = price1 - price2
    return jsonify({
        "coin1": coin1,
        "price1": price1,
        "coin2": coin2,
        "price2": price2,
        "difference": diff
    })


# ─ Alerts CRUD ─────────────────────────────────────────────────────────────────

@app.route("/api/alerts", methods=["GET"])
def api_get_alerts():
    """
    Returns all alerts: 
    [ { "_id": <id>, "coin": <string>, "condition": "above"/"below", "price": <number> } ]
    """
    items = []
    for doc in alerts_col.find():
        items.append({
            "_id": str(doc["_id"]),
            "coin": doc["coin"],
            "condition": doc["condition"],
            "price": doc["price"]
        })
    return jsonify(items)


@app.route("/api/alerts", methods=["POST"])
def api_add_alert():
    """
    JSON body: { "coin": <coin_id>, "condition": "above" or "below", "price": <number> }
    """
    data = request.get_json(force=True)
    coin      = data.get("coin", "").strip().lower()
    condition = data.get("condition", "").strip().lower()
    price     = data.get("price", None)

    if not coin or condition not in ("above", "below") or price is None:
        return jsonify({"error": "Fields 'coin', 'condition' (above/below), and 'price' are required."}), 400

    try:
        price = float(price)
    except ValueError:
        return jsonify({"error": "'price' must be a number."}), 400

    alerts_col.insert_one({"coin": coin, "condition": condition, "price": price})
    return jsonify({"status": "success"}), 200


@app.route("/api/alerts/<id>", methods=["DELETE"])
def api_delete_alert(id):
    """
    Delete one alert by its ObjectId.
    """
    try:
        alerts_col.delete_one({"_id": ObjectId(id)})
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── Run the Flask App ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
