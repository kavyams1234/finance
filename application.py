import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("postgres://aarrlrimwknvwa:65d814525ce396dc0b5815823720a9bd4bbc1bd823236d5cb9ac2253d89e9b84@ec2-52-202-22-140.compute-1.amazonaws.com:5432/d2b1r90mub58s9
")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    num_id = int(session['user_id'])
    rows = db.execute("SELECT * FROM totals WHERE user_id=:num", num=num_id)
    cash_left = db.execute("SELECT cash FROM users WHERE id=:num", num=num_id)
    # Get most recent account how how much cash user has left
    cash_left = cash_left[0]["cash"]
    # Each row contains user_id, symbol, stock, and total number of shares
    # Table needs symbol, name, shares, current price, and TOTAL (current price * shares)
    symbols = []
    names = []
    shares = []
    current_prices = []
    totals = []
    for row in rows:
        # get current prices
        symbol = row["symbol"]
        result = lookup(symbol)
        current_price = result["price"]
        total = current_price * row["total_shares"]

        # Append to list
        symbols.append(row["symbol"])
        names.append(row["stock"])
        shares.append(row["total_shares"])
        current_prices.append(current_price)
        totals.append(total)

    worth = 0
    for total in totals:
        worth += total
    worth += cash_left

    # Formatting money
    worth = usd(worth)
    cash_left = usd(cash_left)
    for i in range (len(current_prices)):
        current_prices[i] = usd(current_prices[i])
        totals[i] = usd(totals[i])

    return render_template("index.html", symbols=symbols, names=names, shares=shares,
                            current_prices=current_prices, totals=totals, cash_left=cash_left,
                            worth=worth)

@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")

    else:
        # Check for errors
        if not request.form.get("symbol"):
            return apology("missing symbol", 400)

        if not request.form.get("shares"):
            return apology("missing shares", 400)

        symbol = request.form.get("symbol")
        result = lookup(symbol)
        if result == None:
            return apology("invalid symbol", 400)
        # Check to see if the user has enough money to buy shares
        price = result["price"]
        shares = request.form.get("shares")
        cost = float(price) * float(shares)
        number = int(session['user_id'])
        reserve = db.execute("SELECT cash FROM users WHERE id = :num", num=number)
        cash = reserve[0]["cash"]
        if cost > cash:
            return apology("can't afford", 400)
        else:
            # Cash total of user after purchase
            new_cash = cash - cost
            db.execute("UPDATE users SET cash=:cash WHERE id = :num", cash=new_cash, num=number)

            # Input purchase into SQL table
            user_id = int(session['user_id'])
            name = db.execute("SELECT username FROM users WHERE id = :num", num=user_id)
            name = name[0]["username"]
            symbol = result["symbol"]
            stock = result["name"]
            price = price
            shares = shares
            cost = cost
            new_cash = new_cash
            now = datetime.now()
            db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        user_id, name, symbol, stock, price, shares, cost, new_cash, now)

            # Make a table of the total shares the user owns
            rows = db.execute("SELECT * FROM totals WHERE user_id=:num AND symbol=:sym", num=user_id, sym=symbol)

            # If user hasn't bought this stock before, make a new row
            if (len(rows) == 0):
                db.execute("INSERT INTO totals VALUES (?, ?, ?, ?)", user_id, symbol, stock, shares)
            else:
            # If user has bought this stock before, update their number of shares
                old_num = db.execute("SELECT total_shares FROM totals WHERE user_id=:num AND symbol=:sym", num=user_id, sym=symbol)
                old_num = old_num[0]["total_shares"]
                totalshares = int(old_num) + int(shares)
                db.execute("UPDATE totals SET total_shares=:tot WHERE user_id=:num AND symbol=:sym", tot=totalshares, num=user_id, sym=symbol)

            return redirect("/")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    user_id = int(session['user_id'])
    rows = db.execute("SELECT * FROM transactions WHERE user_id=:num ORDER BY datetime", num=user_id)
    symbols = []
    shares = []
    prices = []
    times = []

    for row in rows:
        symbols.append(row["symbol"])
        shares.append(row["shares"])
        prices.append(row["price"])
        times.append(row["datetime"])

    for i in range(len(prices)):
        prices[i] = usd(prices[i])

    return render_template("history.html", symbols=symbols, shares=shares, prices=prices, times=times)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")
    if request.method == "POST":
        symbol = request.form.get("symbol")
        result = lookup(symbol)

        # Display quoted page if symbol is valid
        if result != None:
            name = result["name"]
            symbol = result["symbol"]
            price = usd(result["price"])
            return render_template("quoted.html", name=name, symbol=symbol, price=price)
        # Display apology if symbol is invalid
        else:
            return apology("invalid symbol", 400)



@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "GET":
        return render_template("register.html")

    else:
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure username isn't taken
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))
        if len(rows) != 0:
            return apology("username already exists", 403)

        # Ensure password was submitted
        if not request.form.get("password"):
            return apology("must provide password", 403)

        # Ensure password confirmation was submitted
        if not request.form.get("confirmation"):
            return apology("passwords don't match", 403)

        # Ensure password and confirmation match
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords don't match", 403)

        # Hash user's password
        pass_hash = generate_password_hash(request.form.get("password"))

        # Insert user into the users table
        username = request.form.get("username")
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, pass_hash)

        return redirect("/")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "GET":
        return render_template("sell.html")

    else:
        # Check for errors
        if not request.form.get("symbol"):
            return apology("missing symbol", 400)

        if not request.form.get("shares"):
            return apology("missing shares", 400)

        symbol = request.form.get("symbol")
        result = lookup(symbol)
        if result == None:
            return apology("invalid symbol", 400)

        # Check to see if the user actually owns shares of stock
        num_id = int(session['user_id'])
        rows = db.execute("SELECT * FROM totals WHERE user_id=:num", num=num_id)
        stocks_owned = []
        for row in rows:
            stock = row["symbol"]
            stocks_owned.append(stock)
        symbol_input = request.form.get("symbol")
        symbol_input = symbol_input.upper()
        if symbol_input not in stocks_owned:
            return apology("must own shares to sell", 400)

        # Check to see if user owns enough shares to sell
        rows = db.execute("SELECT * FROM totals WHERE user_id=:num AND symbol=:sym",
                            num=num_id, sym=symbol_input)
        shares = rows[0]["total_shares"]
        shares = int(shares)
        share_request = request.form.get("shares")
        share_request = int(share_request)
        if share_request > shares:
            return apology("too many shares", 400)

        # At this point, we have determined that the user is able to sell stock
        # Give user their cash back
        price = result["price"]
        cashback = price * share_request
        current_cash = db.execute("SELECT * FROM users WHERE id=:num", num=num_id)
        current_cash = current_cash[0]["cash"]
        update_cash = current_cash + cashback
        db.execute("UPDATE users SET cash=:c WHERE id=:num", c=update_cash, num=num_id)

        # Update SQL table(s)
        updated_shares = shares - share_request
        # remove transaction from TOTALS table if number of shares equals zero
        if updated_shares == 0:
            db.execute("DELETE FROM totals WHERE user_id=:num AND symbol=:sym", num=num_id,
                        sym=symbol_input)
        else:
            db.execute("UPDATE totals SET total_shares=:new WHERE user_id=:num AND symbol=:sym",
                    new=updated_shares, num=num_id, sym=symbol_input)

        # Input sale into SQL table
        # user_id = int(session['user_id'])
        name = db.execute("SELECT username FROM users WHERE id = :num", num=num_id)
        name = name[0]["username"]
        symbol = symbol_input
        stock = result["name"]
        price = price
        shares = -1 * share_request
        cashback = cashback
        update_cash = update_cash
        now = datetime.now()
        db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    num_id, name, symbol, stock, price, shares, cashback, update_cash, now)


        return redirect("/")

# Personal touch: allow users to add cash to their account
@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    """Add cash to your account"""
    if request.method == "GET":
        return render_template("add.html")

    else:
        # Get user specified amount to add
        amount = request.form.get("amount")
        amount = float(amount)

        # Error checking
        if amount < 0:
            return apology("can't add negative cash", 400)

        # Get current cash reserve
        num_id = int(session['user_id'])
        current_amt = db.execute("SELECT cash FROM users WHERE id=:num", num=num_id)
        current_amt = current_amt[0]["cash"]

        # Add cash
        new = float(amount) + float(current_amt)
        db.execute("UPDATE users SET cash=:n WHERE id=:num", n=new, num=num_id)
        return redirect("/")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)

