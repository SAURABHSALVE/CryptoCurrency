# import os
# import datetime
# import requests
# from flask import Flask, render_template, jsonify, request
# from pymongo import MongoClient
# from bson.objectid import ObjectId
# from dotenv import load_dotenv
# import logging
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# import time
# from openai import OpenAI
# from requests.exceptions import HTTPError

# # Configure Logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('app.log'),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)

# # Load environment variables
# load_dotenv()
# MONGO_URI = os.getenv("MONGO_URI")
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# if not MONGO_URI or not OPENAI_API_KEY:
#     raise RuntimeError("Please set MONGO_URI and OPENAI_API_KEY in the .env file.")

# # Instantiate OpenAI client
# client = OpenAI(api_key=OPENAI_API_KEY)

# # Connect to MongoDB
# client_db = MongoClient(MONGO_URI)
# db = client_db.get_default_database()
# portfolio_col = db.get_collection("portfolio")
# alerts_col = db.get_collection("alerts")
# prices_cache_col = db.get_collection("prices_cache")
# historical_cache_col = db.get_collection("historical_cache")

# # Create indexes for TTL cache expiration
# prices_cache_col.create_index("timestamp", expireAfterSeconds=300)  # 5 minutes for live prices
# historical_cache_col.create_index("timestamp", expireAfterSeconds=3600)  # 1 hour for historical data

# # CoinGecko API Helper
# COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# @retry(
#     stop=stop_after_attempt(5),
#     wait=wait_exponential(multiplier=1, min=4, max=60),
#     retry=retry_if_exception_type((requests.exceptions.RequestException, HTTPError)),
#     after=lambda retry_state: logger.info(f"Retrying CoinGecko API call, attempt {retry_state.attempt_number}")
# )
# def fetch_coingecko_prices(coin_ids, vs_currency="usd"):
#     logger.info(f"Fetching prices from CoinGecko for coins: {coin_ids}")
#     params = {
#         "ids": ",".join(coin_ids),
#         "vs_currencies": vs_currency,
#         "include_market_cap": "true",
#         "include_24hr_vol": "true",
#         "include_24hr_change": "true"
#     }
#     resp = requests.get(COINGECKO_SIMPLE_PRICE_URL, params=params, timeout=10)
#     if resp.status_code == 429:
#         logger.warning("Rate limit exceeded for CoinGecko API")
#         raise HTTPError("429 Too Many Requests")
#     resp.raise_for_status()
#     prices = resp.json()
#     logger.info(f"CoinGecko API response: {prices}")
#     prices_cache_col.insert_one({
#         "coin_ids": sorted(coin_ids),
#         "prices": prices,
#         "timestamp": time.time()
#     })
#     return prices

# @retry(
#     stop=stop_after_attempt(5),
#     wait=wait_exponential(multiplier=1, min=4, max=60),
#     retry=retry_if_exception_type((requests.exceptions.RequestException, HTTPError)),
#     after=lambda retry_state: logger.info(f"Retrying CoinGecko historical API call, attempt {retry_state.attempt_number}")
# )
# def fetch_historical_prices(coin, days=30, vs_currency="usd"):
#     logger.info(f"Fetching historical prices for {coin}")
#     url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency={vs_currency}&days={days}"
#     resp = requests.get(url, timeout=10)
#     if resp.status_code == 429:
#         logger.warning("Rate limit exceeded for CoinGecko historical API")
#         raise HTTPError("429 Too Many Requests")
#     resp.raise_for_status()
#     data = resp.json()
#     historical = {
#         "labels": [datetime.datetime.fromtimestamp(p[0] / 1000).strftime('%Y-%m-%d') for p in data.get("prices", [])],
#         "prices": [p[1] for p in data.get("prices", [])],
#         "timestamp": time.time()
#     }
#     historical_cache_col.insert_one({
#         "coin": coin,
#         "days": days,
#         "data": historical,
#         "timestamp": time.time()
#     })
#     return historical

# def get_live_prices(coin_ids, vs_currency="usd"):
#     cache_key = sorted(coin_ids)
#     cache = prices_cache_col.find_one({"coin_ids": cache_key})
#     if cache:
#         logger.info(f"Using cached prices for coins: {coin_ids}")
#         return cache["prices"]
#     return fetch_coingecko_prices(coin_ids, vs_currency)

# def get_historical_prices(coin, days=30, vs_currency="usd"):
#     cache = historical_cache_col.find_one({"coin": coin, "days": days})
#     if cache:
#         logger.info(f"Using cached historical prices for {coin}")
#         return cache["data"]
#     return fetch_historical_prices(coin, days, vs_currency)

# # Flask App
# app = Flask(__name__)

# # Routes: Render Pages
# def register_routes():
#     @app.route("/")
#     def root():
#         return render_template("dashboard.html")

#     @app.route("/dashboard")
#     def dashboard_page():
#         return render_template("dashboard.html")

#     @app.route("/portfolio")
#     def portfolio_page():
#         return render_template("portfolio.html")

#     @app.route("/compare")
#     def compare_page():
#         return render_template("compare.html")

#     @app.route("/alerts")
#     def alerts_page():
#         return render_template("alerts.html")

# register_routes()

# # ========== API ROUTES ==========

# @app.route("/api/prices", methods=["GET"])
# def api_prices():
#     coin_list = request.args.get("coins", "").strip()
#     if not coin_list:
#         return jsonify({"error": "No coins specified."}), 400
#     coin_ids = [c.strip().lower() for c in coin_list.split(",")]
#     try:
#         prices = get_live_prices(coin_ids)
#         return jsonify(prices)
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         logger.error(f"Error in /api/prices: {e}")
#         return jsonify({"error": f"Failed to fetch prices: {e}"}), 500
#     except Exception as e:
#         logger.error(f"Error in /api/prices: {e}")
#         return jsonify({"error": f"Failed to fetch prices: {e}"}), 500

# @app.route("/api/market_summary", methods=["GET"])
# def api_market_summary():
#     default_coins = ["bitcoin", "ethereum", "ripple", "litecoin", "dogecoin"]
#     try:
#         prices = get_live_prices(default_coins)
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         logger.error(f"Failed to fetch prices: {e}")
#         return jsonify({"error": f"Failed to fetch live prices: {e}"}), 500
#     except Exception as e:
#         logger.error(f"Failed to fetch prices: {e}")
#         return jsonify({"error": f"Failed to fetch live prices: {e}"}), 500

#     market_lines = []
#     for coin in default_coins:
#         price = prices.get(coin, {}).get("usd")
#         if price is not None:
#             market_lines.append(f"- {coin.capitalize()}: ${price:,.2f}")
#         else:
#             market_lines.append(f"- {coin.capitalize()}: (unavailable)")

#     prompt = (
#         "You are a cryptocurrency market analyst. Here are the current prices (USD):\n\n"
#         + "\n".join(market_lines)
#         + "\n\nPlease write a 2–3 sentence summary of the current market situation, mention any notable movements or trends, and keep it concise."
#     )

#     models = ["gpt-4o-mini", "gpt-3.5-turbo"]
#     for model in models:
#         try:
#             completion = client.chat.completions.create(
#                 model=model,
#                 messages=[
#                     {"role": "system", "content": "You are a crypto market summary generator."},
#                     {"role": "user", "content": prompt}
#                 ],
#                 temperature=0.7,
#                 max_tokens=150
#             )
#             summary = completion.choices[0].message.content.strip()
#             return jsonify({"summary": summary})
#         except Exception as e:
#             logger.error(f"OpenAI API error with {model}: {e}")
#             if model == models[-1]:
#                 return jsonify({"error": f"OpenAI API error: {e}"}), 500

# @app.route("/api/compare", methods=["GET"])
# def api_compare():
#     coin1 = request.args.get("coin1", "").strip().lower()
#     coin2 = request.args.get("coin2", "").strip().lower()
#     if not coin1 or not coin2:
#         return jsonify({"error": "Both 'coin1' and 'coin2' required."}), 400

#     try:
#         # Fetch live prices with additional metrics
#         prices = get_live_prices([coin1, coin2])
#         p1 = prices.get(coin1, {}).get("usd")
#         p2 = prices.get(coin2, {}).get("usd")
#         market_cap1 = prices.get(coin1, {}).get("usd_market_cap")
#         market_cap2 = prices.get(coin2, {}).get("usd_market_cap")
#         volume_24h1 = prices.get(coin1, {}).get("usd_24h_vol")
#         volume_24h2 = prices.get(coin2, {}).get("usd_24h_vol")
#         change_24h1 = prices.get(coin1, {}).get("usd_24h_change")
#         change_24h2 = prices.get(coin2, {}).get("usd_24h_change")

#         if p1 is None or p2 is None:
#             return jsonify({"error": "Invalid coin IDs or price data unavailable."}), 400

#         # Fetch historical prices from cache or API
#         historical1 = get_historical_prices(coin1)
#         historical2 = get_historical_prices(coin2)

#         return jsonify({
#             "coin1": coin1,
#             "price1": p1,
#             "market_cap1": market_cap1 if market_cap1 is not None else None,
#             "volume_24h1": volume_24h1 if volume_24h1 is not None else None,
#             "change_24h1": change_24h1 if change_24h1 is not None else None,
#             "coin2": coin2,
#             "price2": p2,
#             "market_cap2": market_cap2 if market_cap2 is not None else None,
#             "volume_24h2": volume_24h2 if volume_24h2 is not None else None,
#             "change_24h2": change_24h2 if change_24h2 is not None else None,
#             "historical1": historical1,
#             "historical2": historical2,
#             "difference": p1 - p2 if p1 is not None and p2 is not None else None
#         })
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         logger.error(f"Error in /api/compare: {e}")
#         return jsonify({"error": f"Failed to fetch data: {e}"}), 500
#     except Exception as e:
#         logger.error(f"Error in /api/compare: {e}")
#         return jsonify({"error": f"Failed to fetch data: {e}"}), 500

# @app.route("/api/alerts", methods=["GET", "POST"])
# def api_alerts():
#     if request.method == "GET":
#         items = [{"_id": str(d["_id"]), "coin": d["coin"], "condition": d['condition'], "price": d['price']} for d in alerts_col.find()]
#         return jsonify(items)

#     data = request.get_json(force=True)
#     coin = data.get("coin", "").strip().lower()
#     cond = data.get("condition", "").strip().lower()
#     price = data.get("price")

#     if cond not in ("above", "below") or not coin or price is None:
#         return jsonify({"error": "Fields 'coin', 'condition', 'price' required."}), 400
#     try:
#         price = float(price)
#     except ValueError:
#         return jsonify({"error": "'price' must be number."}), 400

#     alerts_col.insert_one({"coin": coin, "condition": cond, "price": price})
#     return jsonify({"status": "success"}), 200

# @app.route("/api/alerts/<id>", methods=["DELETE"])
# def api_delete_alert(id):
#     try:
#         alerts_col.delete_one({"_id": ObjectId(id)})
#         return jsonify({"status": "deleted"}), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# @app.route("/api/historical_prices", methods=["GET"])
# def api_historical_prices():
#     coin = request.args.get("coin", "").strip().lower()
#     days = request.args.get("days", "30").strip()
#     if not coin:
#         return jsonify({"error": "Coin ID required."}), 400
#     try:
#         days = int(days)
#     except ValueError:
#         return jsonify({"error": "Days must be integer."}), 400

#     try:
#         historical = get_historical_prices(coin, days)
#         prices = historical["prices"]
#         labels = historical["labels"]
#         if len(prices) >= 7:
#             ma = [sum(prices[i:i+7])/7 for i in range(len(prices)-6)]
#             ma = [None]*(len(prices)-len(ma)) + ma
#         else:
#             ma = [None]*len(prices)
#         return jsonify({"labels": labels, "prices": prices, "moving_average": ma})
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         return jsonify({"error": "Failed to fetch historical data."}), 500
#     except Exception as e:
#         return jsonify({"error": "Failed to fetch historical data."}), 500

# @app.route("/api/portfolio", methods=["GET", "POST"])
# def api_portfolio():
#     if request.method == "GET":
#         items = [{"_id": str(d["_id"]), "coin": d["coin"], "amount": d["amount"]} for d in portfolio_col.find()]
#         return jsonify(items)

#     data = request.get_json(force=True)
#     coin = data.get("coin", "").strip().lower()
#     amount = data.get("amount")

#     if not coin or amount is None:
#         return jsonify({"error": "Both 'coin' and 'amount' are required."}), 400

#     try:
#         amount = float(amount)
#     except ValueError:
#         return jsonify({"error": "'amount' must be a number."}), 400

#     existing = portfolio_col.find_one({"coin": coin})
#     if existing:
#         portfolio_col.update_one({"_id": existing["_id"]}, {"$set": {"amount": amount}})
#     else:
#         portfolio_col.insert_one({"coin": coin, "amount": amount})

#     return jsonify({"status": "success"}), 200

# @app.route("/api/portfolio/<id>", methods=["DELETE"])
# def delete_portfolio(id):
#     try:
#         result = portfolio_col.delete_one({"_id": ObjectId(id)})
#         if result.deleted_count == 0:
#             return jsonify({"error": "Item not found."}), 404
#         return jsonify({"status": "deleted"}), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# if __name__ == "__main__":
#     app.run(debug=True, host="0.0.0.0", port=5000)
    
    
# import os
# import datetime
# import requests
# from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
# from pymongo import MongoClient
# from bson.objectid import ObjectId
# from dotenv import load_dotenv
# import logging
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# import time
# from openai import OpenAI
# from requests.exceptions import HTTPError
# from werkzeug.security import generate_password_hash, check_password_hash
# from functools import wraps



# # Configure Logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('app.log'),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)

# # Load environment variables
# load_dotenv()
# MONGO_URI = os.getenv("MONGO_URI")
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# SECRET_KEY = os.getenv("SECRET_KEY", "change-this!")

# if not MONGO_URI or not OPENAI_API_KEY:
#     raise RuntimeError("Please set MONGO_URI and OPENAI_API_KEY in the .env file.")

# # Instantiate OpenAI client
# client = OpenAI(api_key=OPENAI_API_KEY)

# # Connect to MongoDB
# client_db = MongoClient(MONGO_URI)
# db = client_db.get_default_database()
# portfolio_col = db.get_collection("portfolio")
# alerts_col = db.get_collection("alerts")
# prices_cache_col = db.get_collection("prices_cache")
# historical_cache_col = db.get_collection("historical_cache")
# users_col = db.get_collection("users")

# # Create indexes for TTL cache expiration
# prices_cache_col.create_index("timestamp", expireAfterSeconds=300)  # 5 minutes for live prices
# historical_cache_col.create_index("timestamp", expireAfterSeconds=3600)  # 1 hour for historical data

# # Flask App
# app = Flask(__name__)
# app.secret_key = SECRET_KEY

# # Decorators
# def login_required(fn):
#     @wraps(fn)
#     def wrapper(*args, **kwargs):
#         if "username" not in session:
#             flash("Please log in to access that page.", "warning")
#             return redirect(url_for("login_page"))
#         return fn(*args, **kwargs)
#     return wrapper

# def api_login_required(fn):
#     @wraps(fn)
#     def wrapper(*args, **kwargs):
#         if "username" not in session:
#             return jsonify({"error": "Authentication required."}), 401
#         return fn(*args, **kwargs)
#     return wrapper

# # Auth Routes
# @app.route("/signup", methods=["GET", "POST"])
# def signup_page():
#     if request.method == "POST":
#         username = request.form["username"].strip().lower()
#         password = request.form["password"]
#         if users_col.find_one({"username": username}):
#             flash("Username already taken.", "danger")
#             return redirect(url_for("signup_page"))
#         pw_hash = generate_password_hash(password)
#         users_col.insert_one({"username": username, "password": pw_hash})
#         flash("Account created! Please log in.", "success")
#         return redirect(url_for("login_page"))
#     return render_template("signup.html")

# @app.route("/login", methods=["GET", "POST"])
# def login_page():
#     if request.method == "POST":
#         username = request.form["username"].strip().lower()
#         password = request.form["password"]
#         user = users_col.find_one({"username": username})
#         if not user or not check_password_hash(user["password"], password):
#             flash("Invalid username or password.", "danger")
#             return redirect(url_for("login_page"))
#         session["username"] = username
#         flash(f"Welcome back, {username}!", "success")
#         return redirect(url_for("dashboard_page"))
#     return render_template("login.html")

# @app.route("/logout")
# def logout():
#     session.pop("username", None)
#     flash("You have been logged out.", "info")
#     return redirect(url_for("login_page"))

# # CoinGecko API Helpers
# COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# @retry(
#     stop=stop_after_attempt(5),
#     wait=wait_exponential(multiplier=1, min=4, max=60),
#     retry=retry_if_exception_type((requests.exceptions.RequestException, HTTPError)),
#     after=lambda retry_state: logger.info(f"Retrying CoinGecko API call, attempt {retry_state.attempt_number}")
# )
# def fetch_coingecko_prices(coin_ids, vs_currency="usd"):
#     logger.info(f"Fetching prices from CoinGecko for coins: {coin_ids}")
#     params = {
#         "ids": ",".join(coin_ids),
#         "vs_currencies": vs_currency,
#         "include_market_cap": "true",
#         "include_24hr_vol": "true",
#         "include_24hr_change": "true"
#     }
#     resp = requests.get(COINGECKO_SIMPLE_PRICE_URL, params=params, timeout=10)
#     if resp.status_code == 429:
#         logger.warning("Rate limit exceeded for CoinGecko API")
#         raise HTTPError("429 Too Many Requests")
#     resp.raise_for_status()
#     prices = resp.json()
#     logger.info(f"CoinGecko API response: {prices}")
#     prices_cache_col.insert_one({
#         "coin_ids": sorted(coin_ids),
#         "prices": prices,
#         "timestamp": time.time()
#     })
#     return prices

# @retry(
#     stop=stop_after_attempt(5),
#     wait=wait_exponential(multiplier=1, min=4, max=60),
#     retry=retry_if_exception_type((requests.exceptions.RequestException, HTTPError)),
#     after=lambda retry_state: logger.info(f"Retrying CoinGecko historical API call, attempt {retry_state.attempt_number}")
# )
# def fetch_historical_prices(coin, days=30, vs_currency="usd"):
#     logger.info(f"Fetching historical prices for {coin}")
#     url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency={vs_currency}&days={days}"
#     resp = requests.get(url, timeout=10)
#     if resp.status_code == 429:
#         logger.warning("Rate limit exceeded for CoinGecko historical API")
#         raise HTTPError("429 Too Many Requests")
#     resp.raise_for_status()
#     data = resp.json()
#     historical = {
#         "labels": [datetime.datetime.fromtimestamp(p[0] / 1000).strftime('%Y-%m-%d') for p in data.get("prices", [])],
#         "prices": [p[1] for p in data.get("prices", [])],
#         "timestamp": time.time()
#     }
#     historical_cache_col.insert_one({
#         "coin": coin,
#         "days": days,
#         "data": historical,
#         "timestamp": time.time()
#     })
#     return historical

# def get_live_prices(coin_ids, vs_currency="usd"):
#     cache_key = sorted(coin_ids)
#     cache = prices_cache_col.find_one({"coin_ids": cache_key})
#     if cache:
#         logger.info(f"Using cached prices for coins: {coin_ids}")
#         return cache["prices"]
#     return fetch_coingecko_prices(coin_ids, vs_currency)

# def get_historical_prices(coin, days=30, vs_currency="usd"):
#     cache = historical_cache_col.find_one({"coin": coin, "days": days})
#     if cache:
#         logger.info(f"Using cached historical prices for {coin}")
#         return cache["data"]
#     return fetch_historical_prices(coin, days, vs_currency)

# # Page Routes
# @app.route("/")
# @login_required
# def root():
#     return render_template("dashboard.html", username=session.get("username"))

# @app.route("/dashboard")
# @login_required
# def dashboard_page():
#     return render_template("dashboard.html", username=session.get("username"))

# @app.route("/portfolio")
# @login_required
# def portfolio_page():
#     return render_template("portfolio.html", username=session.get("username"))

# @app.route("/compare")
# @login_required
# def compare_page():
#     return render_template("compare.html", username=session.get("username"))

# @app.route("/alerts")
# @login_required
# def alerts_page():
#     return render_template("alerts.html", username=session.get("username"))

# # API Routes
# @app.route("/api/prices", methods=["GET"])
# @api_login_required
# def api_prices():
#     coin_list = request.args.get("coins", "").strip()
#     if not coin_list:
#         return jsonify({"error": "No coins specified."}), 400
#     coin_ids = [c.strip().lower() for c in coin_list.split(",")]
#     try:
#         prices = get_live_prices(coin_ids)
#         return jsonify(prices)
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         logger.error(f"Error in /api/prices: {e}")
#         return jsonify({"error": f"Failed to fetch prices: {e}"}), 500
#     except Exception as e:
#         logger.error(f"Error in /api/prices: {e}")
#         return jsonify({"error": f"Failed to fetch prices: {e}"}), 500

# @app.route("/api/market_summary", methods=["GET"])
# @api_login_required
# def api_market_summary():
#     default_coins = ["bitcoin", "ethereum", "ripple", "litecoin", "dogecoin"]
#     try:
#         prices = get_live_prices(default_coins)
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         logger.error(f"Failed to fetch prices: {e}")
#         return jsonify({"error": f"Failed to fetch live prices: {e}"}), 500
#     except Exception as e:
#         logger.error(f"Failed to fetch prices: {e}")
#         return jsonify({"error": f"Failed to fetch live prices: {e}"}), 500

#     market_lines = []
#     for coin in default_coins:
#         price = prices.get(coin, {}).get("usd")
#         if price is not None:
#             market_lines.append(f"- {coin.capitalize()}: ${price:,.2f}")
#         else:
#             market_lines.append(f"- {coin.capitalize()}: (unavailable)")

#     prompt = (
#         "You are a cryptocurrency market analyst. Here are the current prices (USD):\n\n"
#         + "\n".join(market_lines)
#         + "\n\nPlease write a 2–3 sentence summary of the current market situation, mention any notable movements or trends, and keep it concise."
#     )

#     models = ["gpt-4o-mini", "gpt-3.5-turbo"]
#     for model in models:
#         try:
#             completion = client.chat.completions.create(
#                 model=model,
#                 messages=[
#                     {"role": "system", "content": "You are a crypto market summary generator."},
#                     {"role": "user", "content": prompt}
#                 ],
#                 temperature=0.7,
#                 max_tokens=150
#             )
#             summary = completion.choices[0].message.content.strip()
#             return jsonify({"summary": summary})
#         except Exception as e:
#             logger.error(f"OpenAI API error with {model}: {e}")
#             if model == models[-1]:
#                 return jsonify({"error": f"OpenAI API error: {e}"}), 500

# @app.route("/api/compare", methods=["GET"])
# @api_login_required
# def api_compare():
#     coin1 = request.args.get("coin1", "").strip().lower()
#     coin2 = request.args.get("coin2", "").strip().lower()
#     if not coin1 or not coin2:
#         return jsonify({"error": "Both 'coin1' and 'coin2' required."}), 400

#     try:
#         prices = get_live_prices([coin1, coin2])
#         p1 = prices.get(coin1, {}).get("usd")
#         p2 = prices.get(coin2, {}).get("usd")
#         market_cap1 = prices.get(coin1, {}).get("usd_market_cap")
#         market_cap2 = prices.get(coin2, {}).get("usd_market_cap")
#         volume_24h1 = prices.get(coin1, {}).get("usd_24h_vol")
#         volume_24h2 = prices.get(coin2, {}).get("usd_24h_vol")
#         change_24h1 = prices.get(coin1, {}).get("usd_24h_change")
#         change_24h2 = prices.get(coin2, {}).get("usd_24h_change")

#         if p1 is None or p2 is None:
#             return jsonify({"error": "Invalid coin IDs or price data unavailable."}), 400

#         historical1 = get_historical_prices(coin1)
#         historical2 = get_historical_prices(coin2)

#         return jsonify({
#             "coin1": coin1,
#             "price1": p1,
#             "market_cap1": market_cap1 if market_cap1 is not None else None,
#             "volume_24h1": volume_24h1 if volume_24h1 is not None else None,
#             "change_24h1": change_24h1 if change_24h1 is not None else None,
#             "coin2": coin2,
#             "price2": p2,
#             "market_cap2": market_cap2 if market_cap2 is not None else None,
#             "volume_24h2": volume_24h2 if volume_24h2 is not None else None,
#             "change_24h2": change_24h2 if change_24h2 is not None else None,
#             "historical1": historical1,
#             "historical2": historical2,
#             "difference": p1 - p2 if p1 is not None and p2 is not None else None
#         })
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         logger.error(f"Error in /api/compare: {e}")
#         return jsonify({"error": f"Failed to fetch data: {e}"}), 500
#     except Exception as e:
#         logger.error(f"Error in /api/compare: {e}")
#         return jsonify({"error": f"Failed to fetch data: {e}"}), 500

# @app.route("/api/alerts", methods=["GET", "POST"])
# @api_login_required
# def api_alerts():
#     username = session["username"]
#     if request.method == "GET":
#         items = [{"_id": str(d["_id"]), "coin": d["coin"], "condition": d["condition"], "price": d["price"]} for d in alerts_col.find({"username": username})]
#         return jsonify(items)

#     data = request.get_json(force=True)
#     coin = data.get("coin", "").strip().lower()
#     cond = data.get("condition", "").strip().lower()
#     price = data.get("price")

#     if cond not in ("above", "below") or not coin or price is None:
#         return jsonify({"error": "Fields 'coin', 'condition', 'price' required."}), 400
#     try:
#         price = float(price)
#     except ValueError:
#         return jsonify({"error": "'price' must be number."}), 400

#     alerts_col.insert_one({"username": username, "coin": coin, "condition": cond, "price": price})
#     return jsonify({"status": "success"}), 200

# @app.route("/api/alerts/<id>", methods=["DELETE"])
# @api_login_required
# def api_delete_alert(id):
#     username = session["username"]
#     try:
#         result = alerts_col.delete_one({"_id": ObjectId(id), "username": username})
#         if result.deleted_count == 0:
#             return jsonify({"error": "Alert not found or not owned by user."}), 404
#         return jsonify({"status": "deleted"}), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# @app.route("/api/historical_prices", methods=["GET"])
# @api_login_required
# def api_historical_prices():
#     coin = request.args.get("coin", "").strip().lower()
#     days = request.args.get("days", "30").strip()
#     if not coin:
#         return jsonify({"error": "Coin ID required."}), 400
#     try:
#         days = int(days)
#     except ValueError:
#         return jsonify({"error": "Days must be integer."}), 400

#     try:
#         historical = get_historical_prices(coin, days)
#         prices = historical["prices"]
#         labels = historical["labels"]
#         if len(prices) >= 7:
#             ma = [sum(prices[i:i+7])/7 for i in range(len(prices)-6)]
#             ma = [None]*(len(prices)-len(ma)) + ma
#         else:
#             ma = [None]*len(prices)
#         return jsonify({"labels": labels, "prices": prices, "moving_average": ma})
#     except HTTPError as e:
#         if "429" in str(e):
#             return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
#         return jsonify({"error": "Failed to fetch historical data."}), 500
#     except Exception as e:
#         return jsonify({"error": "Failed to fetch historical data."}), 500

# @app.route("/api/portfolio", methods=["GET", "POST"])
# @api_login_required
# def api_portfolio():
#     username = session["username"]
#     if request.method == "GET":
#         items = [{"_id": str(d["_id"]), "coin": d["coin"], "amount": d["amount"]} for d in portfolio_col.find({"username": username})]
#         return jsonify(items)

#     data = request.get_json(force=True)
#     coin = data.get("coin", "").strip().lower()
#     amount = data.get("amount")

#     if not coin or amount is None:
#         return jsonify({"error": "Both 'coin' and 'amount' are required."}), 400

#     try:
#         amount = float(amount)
#     except ValueError:
#         return jsonify({"error": "'amount' must be a number."}), 400

#     existing = portfolio_col.find_one({"username": username, "coin": coin})
#     if existing:
#         portfolio_col.update_one({"_id": existing["_id"]}, {"$set": {"amount": amount}})
#     else:
#         portfolio_col.insert_one({"username": username, "coin": coin, "amount": amount})

#     return jsonify({"status": "success"}), 200

# @app.route("/api/portfolio/<id>", methods=["DELETE"])
# @api_login_required
# def delete_portfolio(id):
#     username = session["username"]
#     try:
#         result = portfolio_col.delete_one({"_id": ObjectId(id), "username": username})
#         if result.deleted_count == 0:
#             return jsonify({"error": "Item not found or not owned by user."}), 404
#         return jsonify({"status": "deleted"}), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# if __name__ == "__main__":
#     app.run(debug=True, host="0.0.0.0", port=5000)





import os
import datetime
import requests
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import time
from openai import OpenAI
from requests.exceptions import HTTPError
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
# Connect directly to local MongoDB
MONGO_URI = "mongodb://localhost:27017/"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this!")

if not OPENAI_API_KEY:
    raise RuntimeError("Please set OPENAI_API_KEY in the .env file.")

# Instantiate OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Connect to MongoDB
client_db = MongoClient(MONGO_URI)
db = client_db.crypto_app  # Use a specific database name

# Create collections if they don't exist
if "portfolio" not in db.list_collection_names():
    db.create_collection("portfolio")
if "alerts" not in db.list_collection_names():
    db.create_collection("alerts")
if "prices_cache" not in db.list_collection_names():
    db.create_collection("prices_cache")
if "historical_cache" not in db.list_collection_names():
    db.create_collection("historical_cache")
if "users" not in db.list_collection_names():
    db.create_collection("users")

portfolio_col = db.portfolio
alerts_col = db.alerts
prices_cache_col = db.prices_cache
historical_cache_col = db.historical_cache
users_col = db.users

# Create indexes for TTL cache expiration
try:
    prices_cache_col.create_index("timestamp", expireAfterSeconds=300)
    historical_cache_col.create_index("timestamp", expireAfterSeconds=3600)
except Exception as e:
    logger.error(f"Error creating indexes: {e}")

# Flask App
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Decorators
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to access that page.", "warning")
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)
    return wrapper

def api_login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required."}), 401
        return fn(*args, **kwargs)
    return wrapper

# Auth Routes
@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        if users_col.find_one({"username": username}):
            flash("Username already taken.", "danger")
            return redirect(url_for("signup_page"))
        pw_hash = generate_password_hash(password)
        users_col.insert_one({"username": username, "password": pw_hash})
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login_page"))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        user = users_col.find_one({"username": username})
        if not user or not check_password_hash(user["password"], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login_page"))
        session["username"] = username
        flash(f"Welcome back, {username}!", "success")
        return redirect(url_for("dashboard_page"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("login_page"))

# CoinGecko API Helpers
COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((requests.exceptions.RequestException, HTTPError)),
    after=lambda retry_state: logger.info(f"Retrying CoinGecko API call, attempt {retry_state.attempt_number}")
)
def fetch_coingecko_prices(coin_ids, vs_currency="usd"):
    logger.info(f"Fetching prices from CoinGecko for coins: {coin_ids}")
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": vs_currency,
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true"
    }
    resp = requests.get(COINGECKO_SIMPLE_PRICE_URL, params=params, timeout=10)
    if resp.status_code == 429:
        logger.warning("Rate limit exceeded for CoinGecko API")
        raise HTTPError("429 Too Many Requests")
    resp.raise_for_status()
    prices = resp.json()
    logger.info(f"CoinGecko API response: {prices}")
    prices_cache_col.insert_one({
        "coin_ids": sorted(coin_ids),
        "prices": prices,
        "timestamp": time.time()
    })
    return prices

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((requests.exceptions.RequestException, HTTPError)),
    after=lambda retry_state: logger.info(f"Retrying CoinGecko historical API call, attempt {retry_state.attempt_number}")
)
def fetch_historical_prices(coin, days=30, vs_currency="usd"):
    logger.info(f"Fetching historical prices for {coin}")
    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency={vs_currency}&days={days}"
    resp = requests.get(url, timeout=10)
    if resp.status_code == 429:
        logger.warning("Rate limit exceeded for CoinGecko historical API")
        raise HTTPError("429 Too Many Requests")
    resp.raise_for_status()
    data = resp.json()
    historical = {
        "labels": [datetime.datetime.fromtimestamp(p[0] / 1000).strftime('%Y-%m-%d') for p in data.get("prices", [])],
        "prices": [p[1] for p in data.get("prices", [])],
        "timestamp": time.time()
    }
    historical_cache_col.insert_one({
        "coin": coin,
        "days": days,
        "data": historical,
        "timestamp": time.time()
    })
    return historical

def get_live_prices(coin_ids, vs_currency="usd"):
    cache_key = sorted(coin_ids)
    cache = prices_cache_col.find_one({"coin_ids": cache_key})
    if cache:
        logger.info(f"Using cached prices for coins: {coin_ids}")
        return cache["prices"]
    return fetch_coingecko_prices(coin_ids, vs_currency)

def get_historical_prices(coin, days=30, vs_currency="usd"):
    cache = historical_cache_col.find_one({"coin": coin, "days": days})
    if cache:
        logger.info(f"Using cached historical prices for {coin}")
        return cache["data"]
    return fetch_historical_prices(coin, days, vs_currency)

# Page Routes
@app.route("/")
@login_required
def root():
    return render_template("dashboard.html", username=session.get("username"))

@app.route("/dashboard")
@login_required
def dashboard_page():
    return render_template("dashboard.html", username=session.get("username"))

@app.route("/portfolio")
@login_required
def portfolio_page():
    return render_template("portfolio.html", username=session.get("username"))

@app.route("/compare")
@login_required
def compare_page():
    return render_template("compare.html", username=session.get("username"))

@app.route("/alerts")
@login_required
def alerts_page():
    return render_template("alerts.html", username=session.get("username"))

# API Routes
@app.route("/api/prices", methods=["GET"])
@api_login_required
def api_prices():
    coin_list = request.args.get("coins", "").strip()
    if not coin_list:
        return jsonify({"error": "No coins specified."}), 400
    coin_ids = [c.strip().lower() for c in coin_list.split(",")]
    try:
        prices = get_live_prices(coin_ids)
        return jsonify(prices)
    except HTTPError as e:
        if "429" in str(e):
            return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
        logger.error(f"Error in /api/prices: {e}")
        return jsonify({"error": f"Failed to fetch prices: {e}"}), 500
    except Exception as e:
        logger.error(f"Error in /api/prices: {e}")
        return jsonify({"error": f"Failed to fetch prices: {e}"}), 500

@app.route("/api/market_summary", methods=["GET"])
@api_login_required
def api_market_summary():
    default_coins = ["bitcoin", "ethereum", "ripple", "litecoin", "dogecoin"]
    try:
        prices = get_live_prices(default_coins)
    except HTTPError as e:
        if "429" in str(e):
            return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
        logger.error(f"Failed to fetch prices: {e}")
        return jsonify({"error": f"Failed to fetch live prices: {e}"}), 500
    except Exception as e:
        logger.error(f"Failed to fetch prices: {e}")
        return jsonify({"error": f"Failed to fetch live prices: {e}"}), 500

    market_lines = []
    for coin in default_coins:
        price = prices.get(coin, {}).get("usd")
        if price is not None:
            market_lines.append(f"- {coin.capitalize()}: ${price:,.2f}")
        else:
            market_lines.append(f"- {coin.capitalize()}: (unavailable)")

    prompt = (
        "You are a cryptocurrency market analyst. Here are the current prices (USD):\n\n"
        + "\n".join(market_lines)
        + "\n\nPlease write a 2–3 sentence summary of the current market situation, mention any notable movements or trends, and keep it concise."
    )

    models = ["gpt-4o-mini", "gpt-3.5-turbo"]
    for model in models:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a crypto market summary generator."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            summary = completion.choices[0].message.content.strip()
            return jsonify({"summary": summary})
        except Exception as e:
            logger.error(f"OpenAI API error with {model}: {e}")
            if model == models[-1]:
                return jsonify({"error": f"OpenAI API error: {e}"}), 500

@app.route("/api/compare", methods=["GET"])
@api_login_required
def api_compare():
    coin1 = request.args.get("coin1", "").strip().lower()
    coin2 = request.args.get("coin2", "").strip().lower()
    if not coin1 or not coin2:
        return jsonify({"error": "Both 'coin1' and 'coin2' required."}), 400

    try:
        prices = get_live_prices([coin1, coin2])
        p1 = prices.get(coin1, {}).get("usd")
        p2 = prices.get(coin2, {}).get("usd")
        market_cap1 = prices.get(coin1, {}).get("usd_market_cap")
        market_cap2 = prices.get(coin2, {}).get("usd_market_cap")
        volume_24h1 = prices.get(coin1, {}).get("usd_24h_vol")
        volume_24h2 = prices.get(coin2, {}).get("usd_24h_vol")
        change_24h1 = prices.get(coin1, {}).get("usd_24h_change")
        change_24h2 = prices.get(coin2, {}).get("usd_24h_change")

        if p1 is None or p2 is None:
            return jsonify({"error": "Invalid coin IDs or price data unavailable."}), 400

        historical1 = get_historical_prices(coin1)
        historical2 = get_historical_prices(coin2)

        return jsonify({
            "coin1": coin1,
            "price1": p1,
            "market_cap1": market_cap1 if market_cap1 is not None else None,
            "volume_24h1": volume_24h1 if volume_24h1 is not None else None,
            "change_24h1": change_24h1 if change_24h1 is not None else None,
            "coin2": coin2,
            "price2": p2,
            "market_cap2": market_cap2 if market_cap2 is not None else None,
            "volume_24h2": volume_24h2 if volume_24h2 is not None else None,
            "change_24h2": change_24h2 if change_24h2 is not None else None,
            "historical1": historical1,
            "historical2": historical2,
            "difference": p1 - p2 if p1 is not None and p2 is not None else None
        })
    except HTTPError as e:
        if "429" in str(e):
            return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
        logger.error(f"Error in /api/compare: {e}")
        return jsonify({"error": f"Failed to fetch data: {e}"}), 500
    except Exception as e:
        logger.error(f"Error in /api/compare: {e}")
        return jsonify({"error": f"Failed to fetch data: {e}"}), 500

@app.route("/api/alerts", methods=["GET", "POST"])
@api_login_required
def api_alerts():
    username = session["username"]
    if request.method == "GET":
        items = [{"_id": str(d["_id"]), "coin": d["coin"], "condition": d["condition"], "price": d["price"]} for d in alerts_col.find({"username": username})]
        return jsonify(items)

    data = request.get_json(force=True)
    coin = data.get("coin", "").strip().lower()
    cond = data.get("condition", "").strip().lower()
    price = data.get("price")

    if cond not in ("above", "below") or not coin or price is None:
        return jsonify({"error": "Fields 'coin', 'condition', 'price' required."}), 400
    try:
        price = float(price)
    except ValueError:
        return jsonify({"error": "'price' must be number."}), 400

    alerts_col.insert_one({"username": username, "coin": coin, "condition": cond, "price": price})
    return jsonify({"status": "success"}), 200

@app.route("/api/alerts/<id>", methods=["DELETE"])
@api_login_required
def api_delete_alert(id):
    username = session["username"]
    try:
        result = alerts_col.delete_one({"_id": ObjectId(id), "username": username})
        if result.deleted_count == 0:
            return jsonify({"error": "Alert not found or not owned by user."}), 404
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/historical_prices", methods=["GET"])
@api_login_required
def api_historical_prices():
    coin = request.args.get("coin", "").strip().lower()
    days = request.args.get("days", "30").strip()
    if not coin:
        return jsonify({"error": "Coin ID required."}), 400
    try:
        days = int(days)
    except ValueError:
        return jsonify({"error": "Days must be integer."}), 400

    try:
        historical = get_historical_prices(coin, days)
        prices = historical["prices"]
        labels = historical["labels"]
        if len(prices) >= 7:
            ma = [sum(prices[i:i+7])/7 for i in range(len(prices)-6)]
            ma = [None]*(len(prices)-len(ma)) + ma
        else:
            ma = [None]*len(prices)
        return jsonify({"labels": labels, "prices": prices, "moving_average": ma})
    except HTTPError as e:
        if "429" in str(e):
            return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
        return jsonify({"error": "Failed to fetch historical data."}), 500
    except Exception as e:
        return jsonify({"error": "Failed to fetch historical data."}), 500

@app.route("/api/portfolio", methods=["GET", "POST"])
@api_login_required
def api_portfolio():
    username = session["username"]
    if request.method == "GET":
        items = [{"_id": str(d["_id"]), "coin": d["coin"], "amount": d["amount"]} for d in portfolio_col.find({"username": username})]
        return jsonify(items)

    data = request.get_json(force=True)
    coin = data.get("coin", "").strip().lower()
    amount = data.get("amount")

    if not coin or amount is None:
        return jsonify({"error": "Both 'coin' and 'amount' are required."}), 400

    try:
        amount = float(amount)
    except ValueError:
        return jsonify({"error": "'amount' must be a number."}), 400

    existing = portfolio_col.find_one({"username": username, "coin": coin})
    if existing:
        portfolio_col.update_one({"_id": existing["_id"]}, {"$set": {"amount": amount}})
    else:
        portfolio_col.insert_one({"username": username, "coin": coin, "amount": amount})

    return jsonify({"status": "success"}), 200

@app.route("/api/portfolio/<id>", methods=["DELETE"])
@api_login_required
def delete_portfolio(id):
    username = session["username"]
    try:
        result = portfolio_col.delete_one({"_id": ObjectId(id), "username": username})
        if result.deleted_count == 0:
            return jsonify({"error": "Item not found or not owned by user."}), 404
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
