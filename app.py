from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from foodtruck import FoodTruck, TIME_SLOTS, WORKING_DAYS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import logging
import os

app = Flask(__name__)

# Secret key for sessions.
# TODO: In production this MUST come from an environment variable and the app should be served over HTTPS.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# Basic role handling: admin emails are configured via environment for now.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# Backend instance (rename brand)
my_truck = FoodTruck("Item7 Food Truck", "GSU Campus")

# Initialize CSV files on startup
my_truck.initialize_csv_files()
my_truck.load_staff_from_csv()
my_truck.load_schedules_from_csv()
my_truck.load_orders_from_csv()

# Configure logging for the Flask app (file handler is set up in foodtruck.py as well).
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------- HELPERS ----------


def sanitize_text(value: str) -> str:
    """
    Basic input sanitization:
    - Convert None to empty string
    - Strip leading/trailing whitespace
    """
    if value is None:
        return ""
    return str(value).strip()


def require_admin():
    if "admin" not in session:
        return redirect(url_for("login"))
    return None


def get_cart():
    return session.get("cart", {})


def save_cart(cart):
    session["cart"] = cart


def require_login():
    if "user_email" not in session:
        return redirect(url_for("login"))
    return None


@app.context_processor
def inject_globals():
    cart = get_cart()
    cart_count = sum(item["qty"] for item in cart.values())
    user_email = session.get("user_email")
    user = my_truck.get_user_details(user_email) if user_email else None
    return dict(
        is_admin=("admin" in session),
        admin_email=session.get("admin"),
        user_email=user_email,
        user_name=session.get("user_name"),
        user=user,
        cart_count=cart_count,
        truck=my_truck,
        now=datetime.now,
    )


# ---------- CUSTOMER FLOW: HOME → MENU → CART → CHECKOUT ----------

@app.route("/")
def home():
    # Redirect to dashboard if logged in, otherwise show home
    if "user_email" in session:
        # Admins go to the admin console, staff go to the staff portal
        if "admin" in session:
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("staff_portal"))
    
    featured_items = my_truck.get_menu_items()[:4]
    return render_template(
        "home.html",
        featured_items=featured_items,
        staff_count=len(my_truck.staff),
        schedule_count=len(my_truck.schedules),
        title="Home - Item7 Food Truck",
    )


@app.route("/menu")
def menu_page():
    menu_items = my_truck.get_menu_items()
    return render_template("menu.html", menu_items=menu_items, title="Menu")


@app.route("/staff_portal")
def staff_portal():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    user_email = session.get("user_email")
    user = my_truck.get_user_details(user_email)
    if not user:
        flash("Account not found. Please sign in again.", "error")
        return redirect(url_for("login"))

    my_truck.load_schedules_from_csv()
    my_truck.load_staff_from_csv()

    def parse_schedule(entry):
        try:
            schedule_dt = datetime.strptime(f"{entry['date']} {entry['time']}", "%Y-%m-%d %H:%M")
        except ValueError:
            schedule_dt = datetime.max
        return schedule_dt

    user_schedules = [
        {**s, "datetime": parse_schedule(s)}
        for s in my_truck.schedules
        if s.get("staff_email") == user_email
    ]
    user_schedules.sort(key=lambda s: s["datetime"])

    upcoming_schedules = [s for s in user_schedules if s["datetime"] >= datetime.now()]
    next_shift = upcoming_schedules[0] if upcoming_schedules else None

    def next_working_date(start_date=None):
        current = start_date or datetime.now().date()
        for _ in range(7):
            if current.strftime("%A") in WORKING_DAYS:
                return current
            current += timedelta(days=1)
        return datetime.now().date()

    next_available_date = next_working_date()
    available_slots = my_truck.get_available_slots(user_email, next_available_date.isoformat())

    stats = {
        "total_shifts": len(user_schedules),
        "upcoming_shifts": len(upcoming_schedules),
        "completed_shifts": len([s for s in user_schedules if s["datetime"] < datetime.now()]),
        "next_available_slots": len(available_slots),
    }

    week_overview = []
    today = datetime.now().date()
    for i in range(7):
        day = today + timedelta(days=i)
        label = day.strftime("%A")
        shifts = [
            s
            for s in user_schedules
            if s["datetime"].date() == day
        ]
        week_overview.append(
            {
                "date": day,
                "label": label,
                "shifts": shifts,
                "is_working_day": label in WORKING_DAYS,
            }
        )

    staff_preview = my_truck.staff[:4]

    api_url = url_for("api_appointments")

    return render_template(
        "staff_portal.html",
        user=user,
        next_shift=next_shift,
        upcoming_schedules=upcoming_schedules[:5],
        next_available_date=next_available_date,
        available_slots=available_slots,
        stats=stats,
        week_overview=week_overview,
        staff_preview=staff_preview,
        api_url=api_url,
        time_slots=TIME_SLOTS,
        title="Staff Portal - Item7",
    )


@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    item_name = request.form["item_name"]
    price = float(request.form["price"])
    redirect_to = request.form.get("redirect_to", url_for("menu_page"))

    cart = get_cart()
    if item_name in cart:
        cart[item_name]["qty"] += 1
    else:
        cart[item_name] = {"price": price, "qty": 1}
    save_cart(cart)

    return redirect(redirect_to)


@app.route("/cart")
def cart_page():
    cart = get_cart()
    total = sum(item["price"] * item["qty"] for item in cart.values())
    return render_template("cart.html", cart=cart, total=total, title="Your Cart")


@app.route("/cart/clear")
def clear_cart():
    save_cart({})
    return redirect(url_for("cart_page"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = get_cart()
    if not cart:
        return redirect(url_for("menu_page"))

    total = sum(item["price"] * item["qty"] for item in cart.values())
    items_summary = ", ".join(
        f"{name} x{item['qty']}" for name, item in cart.items()
    )

    if request.method == "POST":
        customer_name = request.form["customer_name"]
        customer_email = request.form["customer_email"]
        allergy_info = request.form["allergy_info"]

        my_truck.add_order_to_csv(
            customer_name, customer_email, items_summary, allergy_info
        )
        my_truck.load_orders_from_csv()

        save_cart({})

        return render_template(
            "checkout_success.html",
            customer_name=customer_name,
            total=total,
            title="Order Confirmed",
        )

    return render_template(
        "checkout.html",
        cart=cart,
        total=total,
        items_summary=items_summary,
        title="Checkout",
    )


# ---------- AUTH (MANAGER LOGIN/REGISTRATION) ----------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """User registration with detailed staff information"""
    if request.method == "POST":
        email = sanitize_text(request.form.get("email"))
        password = request.form.get("password") or ""
        account_type = request.form.get("account_type", "staff")
        first = sanitize_text(request.form.get("first"))
        last = sanitize_text(request.form.get("last"))
        phone = sanitize_text(request.form.get("phone"))
        address = sanitize_text(request.form.get("address"))
        dob = sanitize_text(request.form.get("dob"))
        sex = sanitize_text(request.form.get("sex"))

        account_type = request.form.get("account_type", "staff")

        # Check if user already exists
        if my_truck.get_user_details(email):
            flash("Email already registered. Please login instead.", "error")
            logger.warning(f"Registration attempt with existing email: {email}")
            return redirect(url_for("login"))

        # Add new user
        try:
            # Hash password before storing
            hashed_password = generate_password_hash(password)
            my_truck.add_staff_to_csv(email, hashed_password, first, last, phone, address, dob, sex)
            logger.info(f"New user registered: {email}")
            if account_type == "staff":
                session["user_email"] = email
                session["user_name"] = f"{first} {last}"
                session.pop("admin", None)
                flash("Registration successful. Welcome to Item7!", "success")
                return redirect(url_for("staff_portal"))
            else:
                flash("Registration successful. Please log in to continue.", "success")
                return redirect(url_for("login"))
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            flash("Registration failed. Please try again.", "error")

    return render_template("signup.html", title="Register")

@app.route("/login", methods=["GET", "POST"])
def login():
    """User authentication using CSV-based user management"""
    if "user_email" in session:
        # Already logged in: route by role
        if "admin" in session:
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("staff_portal"))
    
    error = None
    if request.method == "POST":
        email = sanitize_text(request.form.get("email"))
        password = request.form.get("password") or ""
        account_type = request.form.get("account_type", "staff")

        user = my_truck.get_user_details(email)
        # Handle both hashed and legacy plaintext passwords.
        authenticated = False
        if user:
            stored_pw = user.get("password", "")
            if stored_pw.startswith("pbkdf2:") or stored_pw.startswith("scrypt:"):
                authenticated = check_password_hash(stored_pw, password)
            elif stored_pw == password:
                # Legacy plaintext password – treat as valid and upgrade to hashed.
                authenticated = True
                try:
                    new_hashed = generate_password_hash(password)
                    my_truck.update_user_in_csv(
                        email,
                        {"password": new_hashed},
                    )
                except Exception as exc:
                    logger.error(f"Failed upgrading password hash for {email}: {exc}")

        if authenticated:
            session["user_email"] = email
            session["user_name"] = f"{user['first']} {user['last']}"
            # Set or clear admin flag based on configured admin emails
            if email.lower() in ADMIN_EMAILS:
                session["admin"] = email
            else:
                session.pop("admin", None)

            logger.info(f"User logged in: {email}")
            # Admins go to admin dashboard, staff to the staff management portal
            if "admin" in session:
                return redirect(url_for("admin_dashboard"))
            if account_type == "staff":
                return redirect(url_for("staff_portal"))
            return redirect(url_for("home"))
        else:
            error = "Invalid email or password."
            logger.warning(f"Failed login attempt: {email}")

    return render_template("login.html", error=error, title="Manager Login")


@app.route("/logout")
def logout():
    """Session termination"""
    email = session.get("user_email")
    session.pop("user_email", None)
    session.pop("user_name", None)
    session.pop("admin", None)  # Also clear admin session if exists
    logger.info(f"User logged out: {email}")
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    """Main user interface - redirects based on user type"""
    login_redirect = require_login()
    if login_redirect:
        return login_redirect
    
    user_email = session.get("user_email")
    user = my_truck.get_user_details(user_email)
    
    if not user:
        session.pop("user_email", None)
        return redirect(url_for("login"))
    
    # Load data for dashboard
    my_truck.load_staff_from_csv()
    my_truck.load_schedules_from_csv()
    
    # Get user's schedules
    user_schedules = [s for s in my_truck.schedules if s.get("staff_email") == user_email]
    
    return render_template(
        "dashboard.html",
        user=user,
        schedules=user_schedules,
        title="Dashboard"
    )


# ---------- STAFF (ADMIN) ----------

@app.route("/staff")
def staff_page():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    my_truck.load_staff_from_csv()
    return render_template("staff.html", staff=my_truck.staff, title="Staff")


@app.route("/add_staff", methods=["GET"])
def add_staff_form():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    return render_template("add_staff.html", title="Add Staff")


@app.route("/add_staff", methods=["POST"])
def add_staff_submit():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    email = sanitize_text(request.form.get("email"))
    password = request.form.get("password") or ""
    first = sanitize_text(request.form.get("first"))
    last = sanitize_text(request.form.get("last"))
    phone = sanitize_text(request.form.get("phone"))
    address = sanitize_text(request.form.get("address"))
    dob = sanitize_text(request.form.get("dob"))
    sex = sanitize_text(request.form.get("sex"))

    hashed_password = generate_password_hash(password)
    my_truck.add_staff_to_csv(email, hashed_password, first, last, phone, address, dob, sex)
    my_truck.load_staff_from_csv()

    return redirect(url_for("staff_page"))


# ---------- SCHEDULES (ADMIN) ----------

@app.route("/schedules")
def schedules_page():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    my_truck.load_schedules_from_csv()
    return render_template("schedules.html", schedules=my_truck.schedules, title="Schedules")


@app.route("/book_schedule", methods=["GET"])
def book_schedule_form():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    my_truck.load_staff_from_csv()
    return render_template("book_schedule.html", staff=my_truck.staff, title="Book Schedule")


@app.route("/book_schedule", methods=["POST"])
def book_schedule_submit():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    manager = request.form.get("manager", session.get("user_name", "Manager"))
    date_str = request.form["date"]
    time_slot = request.form["time"]
    staff_email = request.form["staff_email"]
    work_time = request.form.get("work_time", f"{time_slot} shift")

    # Use book_helper for validation and booking
    success, message = my_truck.book_helper(manager, date_str, time_slot, staff_email, work_time)
    
    if success:
        flash(message, "success")
        return redirect(url_for("schedules_page"))
    else:
        flash(message, "error")
        return redirect(url_for("book_schedule_form"))

@app.route("/book_appointment", methods=["POST"])
def book_appointment():
    """POST endpoint for booking work times"""
    if "user_email" not in session:
        return jsonify({"error": "Authentication required"}), 401
    
    data = request.get_json() or request.form
    manager = sanitize_text(data.get("manager", session.get("user_name", "Manager")))
    date_str = sanitize_text(data.get("date"))
    time_slot = sanitize_text(data.get("time"))
    staff_email = sanitize_text(data.get("staff_email"))
    work_time = sanitize_text(data.get("work_time", f"{time_slot} shift"))

    if not all([date_str, time_slot, staff_email]):
        return jsonify({"error": "Missing required fields"}), 400

    success, message = my_truck.book_helper(manager, date_str, time_slot, staff_email, work_time)
    
    if success:
        return jsonify({"success": True, "message": message}), 200
    else:
        return jsonify({"success": False, "error": message}), 400

@app.route("/get_available_slots/<staff>/<date>")
def get_available_slots(staff, date):
    """GET endpoint for checking slot availability"""
    staff_email = sanitize_text(staff)
    date_str = sanitize_text(date)

    # Enforce working days rule at the API level as well.
    from datetime import datetime as _dt

    try:
        booking_date = _dt.strptime(date_str, "%Y-%m-%d").date()
        day_name = booking_date.strftime("%A")
        if day_name not in WORKING_DAYS:
            return (
                jsonify(
                    {
                        "error": f"{day_name} is not a working day. Working days: {', '.join(WORKING_DAYS)}"
                    }
                ),
                400,
            )
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    available = my_truck.get_available_slots(staff_email, date_str)
    return jsonify(
        {
            "staff": staff_email,
            "date": date_str,
            "available_slots": available,
        }
    )


# ---------- ADMIN DASHBOARD + ORDERS ----------

@app.route("/admin")
def admin_dashboard():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    my_truck.load_staff_from_csv()
    my_truck.load_schedules_from_csv()
    my_truck.load_orders_from_csv()

    unsafe_count = sum(1 for o in my_truck.orders if o["is_safe"] == "NO")

    return render_template(
        "admin_dashboards.html",
        staff_count=len(my_truck.staff),
        schedule_count=len(my_truck.schedules),
        orders_count=len(my_truck.orders),
        unsafe_orders_count=unsafe_count,
        title="Admin Dashboard",
    )


@app.route("/admin/orders")
def admin_orders_page():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    my_truck.load_orders_from_csv()
    return render_template("admin_orders.html", orders=my_truck.orders, title="Admin Orders")


# ---------- PROFILE MANAGEMENT ----------

@app.route("/update_profile", methods=["GET", "POST"])
def update_profile():
    """View and update user profile"""
    if "user_email" not in session:
        return redirect(url_for("login"))
    
    user_email = session.get("user_email")
    user = my_truck.get_user_details(user_email)
    
    if not user:
        return redirect(url_for("login"))
    
    if request.method == "POST":
        # Update user information
        first = sanitize_text(request.form.get("first", user["first"]))
        last = sanitize_text(request.form.get("last", user["last"]))
        phone = sanitize_text(request.form.get("phone", user["phone"]))
        address = sanitize_text(request.form.get("address", user["address"]))
        dob = sanitize_text(request.form.get("dob", user["dob"]))
        sex = sanitize_text(request.form.get("sex", user["sex"]))

        updated = my_truck.update_user_in_csv(
            user_email,
            {
                "first": first,
                "last": last,
                "phone": phone,
                "address": address,
                "dob": dob,
                "sex": sex,
            },
        )

        if updated:
            # Keep session display name in sync
            session["user_name"] = f"{first} {last}"
            flash("Profile updated successfully.", "success")
            logger.info(f"Profile updated for: {user_email}")
        else:
            flash("Could not update profile. Please try again.", "error")
            logger.error(f"Failed to update profile for: {user_email}")

        return redirect(url_for("dashboard"))

    return render_template("update_profile.html", user=user, title="Update Profile")


# ---------- API ENDPOINTS ----------

@app.route("/api/appointments")
def api_appointments():
    """GET endpoint for retrieving all timeslots with staff details"""
    my_truck.load_schedules_from_csv()
    my_truck.load_staff_from_csv()
    
    appointments = []
    for schedule in my_truck.schedules:
        staff = my_truck.get_user_details(schedule["staff_email"])
        appointment = {
            "manager": schedule["manager"],
            "date": schedule["date"],
            "time": schedule["time"],
            "staff_email": schedule["staff_email"],
            "staff_name": schedule["staff_name"],
            "work_time": schedule["work_time"],
            "staff_details": {
                "first_name": staff["first"] if staff else None,
                "last_name": staff["last"] if staff else None,
                "phone": staff["phone"] if staff else None,
                "address": staff["address"] if staff else None,
            } if staff else None
        }
        appointments.append(appointment)
    
    return jsonify({
        "appointments": appointments,
        "total": len(appointments),
        "time_slots": TIME_SLOTS,
        "working_days": WORKING_DAYS
    })


if __name__ == "__main__":
    app.run(debug=True)
