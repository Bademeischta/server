import json
import os
import random
import time
import html
import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION & GLOBALS ---
DATA_FILE = "bankdaten_secure.json"
MAX_CHAT_HISTORY = 30
ONLINE_TIMEOUT = 120  # 2 minutes to be considered online

# Game Constants
JOBS = {
    "flaschensammler": {"name": "Flaschensammler", "req_level": 1, "salary": 10, "xp": 10, "cooldown": 10, "desc": "Mühsam nährt sich das Eichhörnchen."},
    "tellerwaescher": {"name": "Tellerwäscher", "req_level": 2, "salary": 25, "xp": 20, "cooldown": 30, "desc": "Immer schön sauber bleiben."},
    "zeitung": {"name": "Zeitungsjunge", "req_level": 5, "salary": 60, "xp": 40, "cooldown": 60, "desc": "Jeden Morgen pünktlich."},
    "nachhilfe": {"name": "Nachhilfe-Lehrer", "req_level": 10, "salary": 150, "xp": 80, "cooldown": 120, "desc": "Erkläre Mathe den Kleinen."},
    "informatiker": {"name": "Schul-Admin", "req_level": 20, "salary": 400, "xp": 200, "cooldown": 300, "desc": "Hast du es schon mit Neustarten versucht?"},
    "bankier": {"name": "Investment Banker", "req_level": 50, "salary": 2000, "xp": 1000, "cooldown": 600, "desc": "Geld arbeitet für dich."}
}

ITEMS = {
    "energy_drink": {"name": "Energy Drink", "price": 50, "type": "consumable", "desc": "Entfernt sofort den Arbeits-Cooldown.", "effect": "reset_work"},
    "spickzettel": {"name": "Spickzettel", "price": 200, "type": "consumable", "desc": "+20% Hack-Chance für 5 Min.", "effect": "buff_hack", "duration": 300},
    "glücksbringer": {"name": "Hasenpfote", "price": 1000, "type": "passive", "desc": "+5% Gewinnchance bei Crime (Passiv).", "value": 0.05},
    "laptop": {"name": "Hacker-Laptop", "price": 5000, "type": "passive", "desc": "Sicherere Überfälle (Jail -10%).", "value": 0.10},
    "anwalt": {"name": "Guter Anwalt", "price": 15000, "type": "passive", "desc": "Halbiert Gefängniszeit.", "value": 0.5},
    "rolex": {"name": "Goldene Uhr", "price": 50000, "type": "cosmetic", "desc": "Zeigt Reichtum im Profil."}
}

# Stocks definition
STOCKS = {
    "PAU": {"name": "Pausenbrot AG", "price": 10.0, "volatility": 0.02, "trend": 0},
    "CRY": {"name": "Kryptokeller", "price": 50.0, "volatility": 0.10, "trend": 0},
    "LEH": {"name": "LehrerPult Inc", "price": 100.0, "volatility": 0.05, "trend": 0}
}
stock_last_update = time.time()

chat_history = []
online_users = {} # name -> last_seen_timestamp

# --- DATA MANAGEMENT ---
class Database:
    def __init__(self):
        self.filename = DATA_FILE
        self.data = {"users": {}, "ips": {}}
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r") as f:
                    temp = json.load(f)
                    if "users" in temp:
                        self.data = temp
            except:
                pass

    def save(self):
        with open(self.filename, "w") as f:
            json.dump(self.data, f)

    def get_user(self, name):
        return self.data["users"].get(name)

    def create_user(self, name, pw, ip):
        if name in self.data["users"]:
            return False, "Name vergeben!"

        # Initial user structure
        self.data["users"][name] = {
            "passwort": pw,
            "geld": 100.0,
            "xp": 0,
            "level": 1,
            "inventory": {}, # changed to dict: item_key -> count
            "stocks": {}, # symbol -> amount
            "cooldowns": {},
            "buffs": {}, # buff_name -> expire_time
            "stats": {"wins": 0, "games": 0},
            "daily_claimed": None, # date string
            "blackjack": None,
            "crash": None
        }
        self.data["ips"][ip] = name
        self.save()
        return True, "User erstellt."

db = Database()

# --- HELPER FUNCTIONS ---
def update_economy():
    global stock_last_update
    now = time.time()
    if now - stock_last_update > 10: # Update every 10s
        for sym, stock in STOCKS.items():
            change = random.uniform(-stock["volatility"], stock["volatility"])
            # Slight drift back to 100 if too low/high? Or random walk.
            stock["price"] *= (1 + change)
            if stock["price"] < 1.0: stock["price"] = 1.0
        stock_last_update = now

def check_levelup(user):
    # XP formula: Level L requires 100 * L^1.2 XP roughly
    req_xp = int(100 * (user["level"] ** 1.2))
    if user["xp"] >= req_xp:
        user["xp"] -= req_xp
        user["level"] += 1
        return True, user["level"]
    return False, user["level"]

def get_active_buffs(user):
    # Returns multipliers/adders based on passive items and active buffs
    buffs = {"crime_chance": 0.0, "jail_safety": 0.0, "jail_time_mult": 1.0, "hack_bonus": 0.0}

    # Inventory Passives
    inv = user.get("inventory", {})
    if inv.get("glücksbringer", 0) > 0: buffs["crime_chance"] += ITEMS["glücksbringer"]["value"]
    if inv.get("laptop", 0) > 0: buffs["jail_safety"] += ITEMS["laptop"]["value"]
    if inv.get("anwalt", 0) > 0: buffs["jail_time_mult"] = ITEMS["anwalt"]["value"]

    # Active Consumable Buffs
    now = time.time()
    user_buffs = user.get("buffs", {})
    to_remove = []
    for b_key, expire in user_buffs.items():
        if now < expire:
            if b_key == "buff_hack": buffs["hack_bonus"] += 0.20
        else:
            to_remove.append(b_key)

    for k in to_remove: del user_buffs[k]

    return buffs

# --- ROUTES ---

@app.route('/')
def index():
    return open("index.html", "r", encoding="utf-8").read()

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    cmd = data.get("cmd")
    name = data.get("name")
    pw = data.get("pw")
    ip = request.remote_addr

    if not name or len(name) > 20: return jsonify({"ok": False, "msg": "Ungültiger Name"})

    if cmd == "register":
        success, msg = db.create_user(name, pw, ip)
        return jsonify({"ok": success, "msg": msg})

    elif cmd == "login":
        user = db.get_user(name)
        if user and user["passwort"] == pw:
            return jsonify({"ok": True, "msg": "Willkommen zurück!"})
        return jsonify({"ok": False, "msg": "Falsche Daten!"})

@app.route('/api/data', methods=['POST'])
def get_data():
    name = request.json.get("name")
    pw = request.json.get("pw")
    user = db.get_user(name)

    if not user or user["passwort"] != pw:
        return jsonify({"ok": False})

    # Update Online Status
    online_users[name] = time.time()

    # Clean up offline users
    now = time.time()
    active_users_count = sum(1 for t in online_users.values() if now - t < ONLINE_TIMEOUT)

    update_economy()

    # Check Jail
    jail_until = user["cooldowns"].get("jail_until", 0)
    is_jailed = now < jail_until

    # XP Progress for UI
    req_xp = int(100 * (user["level"] ** 1.2))

    # Leaderboard (Top 10 Money)
    sorted_users = sorted(db.data["users"].items(), key=lambda x: x[1]["geld"], reverse=True)[:10]
    leaderboard = [{"name": k, "geld": int(v["geld"]), "level": v["level"]} for k,v in sorted_users]

    # Check Daily
    today_str = datetime.date.today().isoformat()
    can_claim_daily = user.get("daily_claimed") != today_str

    # Format Inventory for Client
    # Convert dict {"item": count} to list of objects
    client_inv = []
    for k, count in user.get("inventory", {}).items():
        if count > 0:
            item_def = ITEMS.get(k, {})
            client_inv.append({"key": k, "name": item_def.get("name", k), "count": count, "type": item_def.get("type", "misc")})

    return jsonify({
        "ok": True,
        "user": {
            "geld": user["geld"],
            "xp": user["xp"],
            "xp_next": req_xp,
            "level": user["level"],
            "inventory": client_inv,
            "stocks": user.get("stocks", {}),
            "is_jailed": is_jailed,
            "jail_time": int(max(0, jail_until - now)),
            "can_daily": can_claim_daily
        },
        "market": STOCKS,
        "chat": chat_history,
        "leaderboard": leaderboard,
        "online_count": active_users_count
    })

@app.route('/api/daily', methods=['POST'])
def daily():
    name = request.json.get("name")
    user = db.get_user(name)
    if not user: return jsonify({"ok": False})

    today_str = datetime.date.today().isoformat()
    if user.get("daily_claimed") == today_str:
        return jsonify({"ok": False, "msg": "Schon abgeholt!"})

    reward = 100 * user["level"]
    user["geld"] += reward
    user["daily_claimed"] = today_str
    db.save()
    return jsonify({"ok": True, "msg": f"Tagesbonus: +{reward}€ erhalten!", "reward": reward})

@app.route('/api/work', methods=['POST'])
def work():
    name = request.json.get("name")
    user = db.get_user(name)
    job_key = request.json.get("job")

    if not user: return jsonify({"ok": False})

    if time.time() < user["cooldowns"].get("jail_until", 0):
         return jsonify({"ok": False, "msg": "Du bist im Gefängnis!"})

    job = JOBS.get(job_key)
    if not job: return jsonify({"ok": False, "msg": "Job existiert nicht."})

    if user["level"] < job["req_level"]:
        return jsonify({"ok": False, "msg": f"Level {job['req_level']} benötigt!"})

    last_work = user["cooldowns"].get(f"work_{job_key}", 0)
    if time.time() < last_work + job["cooldown"]:
        rem = int((last_work + job["cooldown"]) - time.time())
        return jsonify({"ok": False, "msg": f"Pause! Warte {rem}s."})

    # Success
    user["geld"] += job["salary"]
    user["xp"] += job["xp"]
    user["cooldowns"][f"work_{job_key}"] = time.time()

    levelup, new_lvl = check_levelup(user)
    db.save()

    msg = f"Gearbeitet! +{job['salary']}€, +{job['xp']} XP."
    if levelup: msg += f" LEVEL UP! Stufe {new_lvl}"

    return jsonify({"ok": True, "msg": msg, "leveled_up": levelup})

@app.route('/api/crime', methods=['POST'])
def crime():
    name = request.json.get("name")
    user = db.get_user(name)
    risk_type = request.json.get("type") # 'bank', 'hack', 'steal'

    if not user: return jsonify({"ok": False})
    if time.time() < user["cooldowns"].get("jail_until", 0):
         return jsonify({"ok": False, "msg": "Immer noch im Knast!"})

    last_crime = user["cooldowns"].get("crime", 0)
    if time.time() < last_crime + 60:
         return jsonify({"ok": False, "msg": "Füße stillhalten! (Cooldown)"})

    buffs = get_active_buffs(user)

    jail_seconds = 0
    potential_win = 0
    success_chance = 0.0

    if risk_type == "bank":
        success_chance = 0.30 + buffs["crime_chance"]
        potential_win = random.randint(500, 2000) * user["level"]
        jail_seconds = 120
    elif risk_type == "hack":
        success_chance = 0.50 + buffs["crime_chance"] + buffs["hack_bonus"]
        potential_win = random.randint(100, 500) * user["level"]
        jail_seconds = 60
    elif risk_type == "steal": # Steal from dummy/npc
        success_chance = 0.70 + buffs["crime_chance"]
        potential_win = random.randint(20, 100) * user["level"]
        jail_seconds = 30
    else:
        return jsonify({"ok": False, "msg": "Unbekanntes Verbrechen"})

    user["cooldowns"]["crime"] = time.time()

    if random.random() < success_chance:
        user["geld"] += potential_win
        user["xp"] += 50
        lvl, _ = check_levelup(user)
        db.save()
        return jsonify({"ok": True, "msg": f"Erfolg! {potential_win}€ erbeutet!", "win": True})
    else:
        jail_time = int(jail_seconds * buffs["jail_time_mult"])
        user["cooldowns"]["jail_until"] = time.time() + jail_time
        loss = int(user["geld"] * 0.1)
        user["geld"] -= loss
        db.save()
        return jsonify({"ok": True, "msg": f"ERWISCHT! {jail_time}s Knast & -{loss}€ Strafe.", "win": False})

@app.route('/api/shop/buy', methods=['POST'])
def shop_buy():
    name = request.json.get("name")
    item_key = request.json.get("item")
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})
    item = ITEMS.get(item_key)
    if not item: return jsonify({"ok": False, "msg": "Item nicht gefunden."})

    if user["geld"] < item["price"]:
        return jsonify({"ok": False, "msg": "Zu wenig Geld!"})

    # Deduct money
    user["geld"] -= item["price"]

    # Add to inventory (dict)
    inv = user.setdefault("inventory", {})
    # Initialize if it was a list in old data
    if isinstance(inv, list): inv = {}; user["inventory"] = inv

    current_count = inv.get(item_key, 0)
    inv[item_key] = current_count + 1

    db.save()
    return jsonify({"ok": True, "msg": f"{item['name']} gekauft!"})

@app.route('/api/item/use', methods=['POST'])
def use_item():
    name = request.json.get("name")
    item_key = request.json.get("item")
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})
    inv = user.get("inventory", {})
    if inv.get(item_key, 0) <= 0:
        return jsonify({"ok": False, "msg": "Item nicht im Besitz."})

    item_def = ITEMS.get(item_key)
    if item_def.get("type") != "consumable":
        return jsonify({"ok": False, "msg": "Nicht benutzbar."})

    # Apply Effect
    effect = item_def.get("effect")
    if effect == "reset_work":
        # Reset all work cooldowns
        keys_to_reset = [k for k in user["cooldowns"] if k.startswith("work_")]
        for k in keys_to_reset: del user["cooldowns"][k]
        msg = "Arbeitskraft wiederhergestellt!"
    elif effect == "buff_hack":
        user.setdefault("buffs", {})
        user["buffs"]["buff_hack"] = time.time() + item_def["duration"]
        msg = "Hacking-Fähigkeit verbessert!"
    else:
        msg = "Item benutzt."

    # Consume
    inv[item_key] -= 1
    if inv[item_key] <= 0: del inv[item_key]

    db.save()
    return jsonify({"ok": True, "msg": msg})

@app.route('/api/stock', methods=['POST'])
def stock_trade():
    name = request.json.get("name")
    action = request.json.get("action") # 'buy', 'sell'
    symbol = request.json.get("symbol")
    amount = int(request.json.get("amount", 0))
    user = db.get_user(name)

    if not user or amount <= 0: return jsonify({"ok": False, "msg": "Ungültig."})

    stock = STOCKS.get(symbol)
    if not stock: return jsonify({"ok": False, "msg": "Aktie nicht gefunden."})

    update_economy()
    current_price = stock["price"]

    user_stocks = user.setdefault("stocks", {}) # Ensure dict

    if action == "buy":
        cost = current_price * amount
        if user["geld"] >= cost:
            user["geld"] -= cost
            user_stocks[symbol] = user_stocks.get(symbol, 0) + amount
            db.save()
            return jsonify({"ok": True, "msg": f"{amount} {symbol} gekauft."})
        else:
            return jsonify({"ok": False, "msg": "Zu wenig Geld."})

    elif action == "sell":
        if user_stocks.get(symbol, 0) >= amount:
            gain = current_price * amount
            user_stocks[symbol] -= amount
            if user_stocks[symbol] == 0: del user_stocks[symbol]
            user["geld"] += gain
            db.save()
            return jsonify({"ok": True, "msg": f"{amount} {symbol} verkauft."})
        else:
            return jsonify({"ok": False, "msg": "Nicht genug Aktien."})

    return jsonify({"ok": False})

@app.route('/api/chat', methods=['POST'])
def chat():
    name = request.json.get("name")
    msg = request.json.get("msg")

    if not name or not msg: return jsonify({"ok": False})
    if len(msg) > 200: msg = msg[:200]

    clean_msg = html.escape(msg)

    # Commands
    if clean_msg.startswith("/stats"):
        # System reply
        chat_history.append({"name": "SYSTEM", "msg": f"Online: {len(online_users)} User.", "time": time.strftime("%H:%M")})
        return jsonify({"ok": True})

    chat_history.append({"name": name, "msg": clean_msg, "time": time.strftime("%H:%M")})

    if len(chat_history) > MAX_CHAT_HISTORY:
        chat_history.pop(0)

    return jsonify({"ok": True})

@app.route('/api/transfer', methods=['POST'])
def transfer():
    sender_name = request.json.get("name")
    receiver_name = request.json.get("receiver")
    amount = int(request.json.get("amount", 0))

    sender = db.get_user(sender_name)
    receiver = db.get_user(receiver_name)

    if not sender or not receiver: return jsonify({"ok": False, "msg": "User nicht gefunden."})
    if amount <= 0: return jsonify({"ok": False, "msg": "Ungültiger Betrag."})
    if sender["geld"] < amount: return jsonify({"ok": False, "msg": "Nicht genug Geld."})

    sender["geld"] -= amount
    receiver["geld"] += amount
    db.save()
    return jsonify({"ok": True, "msg": f"{amount}€ an {receiver_name} gesendet."})

# --- GAMES ---

def get_deck():
    ranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
    suits = ['♥','♦','♠','♣']
    deck = [{'r':r, 's':s} for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

def calc_hand(hand):
    score = 0; aces = 0
    for card in hand:
        r = card['r']
        if r in ['J','Q','K']: score += 10
        elif r == 'A': score += 11; aces += 1
        else: score += int(r)
    while score > 21 and aces: score -= 10; aces -= 1
    return score

@app.route('/api/game/blackjack', methods=['POST'])
def blackjack():
    name = request.json.get("name")
    action = request.json.get("action") # start, hit, stand, double
    bet = int(request.json.get("bet", 0))
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})

    if action == "start":
        if user["blackjack"]: return jsonify({"ok": False, "msg": "Spiel läuft schon."})
        if bet <= 0 or user["geld"] < bet: return jsonify({"ok": False, "msg": "Einsatz ungültig."})

        user["geld"] -= bet
        deck = get_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        user["blackjack"] = {
            "deck": deck, "player": player, "dealer": dealer, "bet": bet, "status": "playing"
        }

        # Instant BJ
        if calc_hand(player) == 21:
            win = bet * 2.5
            user["geld"] += win
            user["blackjack"]["status"] = "win"
            user["blackjack"]["msg"] = "BLACKJACK! (x2.5)"
            state = user["blackjack"]
            user["blackjack"] = None
            db.save()
            return jsonify({"ok": True, "state": state})

        db.save()
        vis = user["blackjack"].copy()
        vis["dealer"] = [vis["dealer"][0], {"r":"?", "s":"?"}]
        del vis["deck"]
        return jsonify({"ok": True, "state": vis})

    state = user["blackjack"]
    if not state: return jsonify({"ok": False, "msg": "Kein Spiel."})

    if action == "hit" or action == "double":
        if action == "double":
            # Double check money
            if user["geld"] < state["bet"]:
                return jsonify({"ok": False, "msg": "Nicht genug Geld für Double."})
            user["geld"] -= state["bet"]
            state["bet"] *= 2

        state["player"].append(state["deck"].pop())
        score = calc_hand(state["player"])

        bust = False
        if score > 21:
            state["status"] = "lose"
            state["msg"] = "BUST! Über 21."
            user["blackjack"] = None
            bust = True

        if action == "double" and not bust:
            # Force Stand after double
            action = "stand"
        elif bust:
            db.save()
            return jsonify({"ok": True, "state": state})
        else:
            db.save()
            vis = state.copy()
            vis["dealer"] = [vis["dealer"][0], {"r":"?", "s":"?"}]
            del vis["deck"]
            return jsonify({"ok": True, "state": vis})

    if action == "stand":
        # Dealer turn
        while calc_hand(state["dealer"]) < 17:
            state["dealer"].append(state["deck"].pop())

        p = calc_hand(state["player"])
        d = calc_hand(state["dealer"])
        win_amt = 0
        if d > 21 or p > d:
            state["status"] = "win"
            state["msg"] = "Gewonnen!"
            win_amt = state["bet"] * 2
        elif p == d:
            state["status"] = "push"
            state["msg"] = "Unentschieden."
            win_amt = state["bet"]

        win_amount = 0
        if d_score > 21 or p_score >= d_score:
            state["status"] = "win"
            state["msg"] = "Gewonnen!"
            win_amount = state["bet"] * 2

        else:
            state["status"] = "lose"
            state["msg"] = "Bank gewinnt."

        user["geld"] += win_amt
        user["stats"]["games"] += 1
        if win_amt > state["bet"]: user["stats"]["wins"] += 1

        user["blackjack"] = None
        db.save()
        del state["deck"]
        return jsonify({"ok": True, "state": state})

    return jsonify({"ok": False})

@app.route('/api/game/roulette', methods=['POST'])
def roulette():
    name = request.json.get("name")
    bet = int(request.json.get("bet", 0))
    b_type = request.json.get("type")
    b_val = request.json.get("value")

    user = db.get_user(name)
    if not user or bet <= 0 or user["geld"] < bet:
        return jsonify({"ok": False, "msg": "Einsatz ungültig."})

    user["geld"] -= bet
    res = random.randint(0, 36)

    red_nums = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "green"
    if res in red_nums: color = "red"
    elif res != 0: color = "black"

    won = False
    multi = 0

    if b_type == "number" and int(b_val) == res:
        won = True; multi = 36
    elif b_type == "color" and b_val == color:
        won = True; multi = 2
    elif b_type == "dozen":
        if b_val == "1-12" and 1 <= res <= 12: won = True; multi = 3
        elif b_val == "13-24" and 13 <= res <= 24: won = True; multi = 3
        elif b_val == "25-36" and 25 <= res <= 36: won = True; multi = 3
    elif b_type == "parity":
        if b_val == "even" and res != 0 and res % 2 == 0: won = True; multi = 2
        elif b_val == "odd" and res != 0 and res % 2 != 0: won = True; multi = 2

    winnings = 0
    msg = f"Kugel auf {res} ({color}). Verloren."
    if won:
        winnings = bet * multi
        user["geld"] += winnings
        msg = f"Kugel auf {res} ({color})! +{winnings}€"

    db.save()
    return jsonify({"ok": True, "result": res, "color": color, "winnings": winnings, "msg": msg})

@app.route('/api/game/crash', methods=['POST'])
def crash():
    name = request.json.get("name")
    action = request.json.get("action")
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})

    if action == "start":
        bet = int(request.json.get("bet", 0))
        if bet <= 0 or user["geld"] < bet: return jsonify({"ok": False, "msg": "Geldproblem."})

        user["geld"] -= bet

        # Crash algo
        # 3% house edge via instant crash at 1.00
        if random.random() < 0.03:
            crash_p = 1.00
        else:
            # Pareto distribution
            crash_p = 0.99 / (1.0 - random.random())
            crash_p = min(crash_p, 500.0) # Cap
            if crash_p < 1.0: crash_p = 1.0

        user["crash"] = {"bet": bet, "crash_point": crash_p, "start_time": time.time()}
        db.save()
        return jsonify({"ok": True})

    elif action == "cashout":
        if not user.get("crash"): return jsonify({"ok": False, "msg": "Kein Spiel."})
        g = user["crash"]

        # We trust the client claims a multiplier <= Actual Crash Point?
        # No, client sends "cashout" signal, we calculate current multiplier based on time elapsed?
        # Better: Client sends the multiplier they saw.
        # But for security, we should check time.
        # Simplification: Trust client claim IF it is <= server_crash_point

        claimed = float(request.json.get("multiplier", 1.0))
        actual = g["crash_point"]

        if claimed > actual:
            # Lag or cheating: User crashed.
            user["crash"] = None
            db.save()
            return jsonify({"ok": True, "win": False, "crash_point": actual, "msg": f"Crashed @ {actual:.2f}x"})

        win = int(g["bet"] * claimed)
        user["geld"] += win
        user["crash"] = None
        db.save()
        return jsonify({"ok": True, "win": True, "crash_point": actual, "winnings": win, "msg": f"Cashout @ {claimed}x"})

    return jsonify({"ok": False})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
