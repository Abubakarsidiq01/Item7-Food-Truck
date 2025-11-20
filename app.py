from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from foodtruck import FoodTruck, TIME_SLOTS, WORKING_DAYS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import logging
import os
import csv
from dotenv import load_dotenv
import stripe

# Load environment variables from .env file (override any system env vars)
load_dotenv(override=True)

app = Flask(__name__)

# Secret key for sessions.
# TODO: In production this MUST come from an environment variable and the app should be served over HTTPS.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# Stripe configuration (using test keys)
# NOTE: Get your test keys from https://dashboard.stripe.com/test/apikeys
# For demo purposes, you can use Stripe's test card: 4242 4242 4242 4242
# DEMO MODE: If keys are not set, we'll use demo mode (simulated payments)
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")

# Check if real keys are provided
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY and 
                      not STRIPE_SECRET_KEY.startswith("sk_test_51QEXAMPLE") and
                      not STRIPE_PUBLISHABLE_KEY.startswith("pk_test_51QEXAMPLE"))

# DEMO MODE: Enable Stripe UI even without real keys (for testing)
STRIPE_DEMO_MODE = not STRIPE_ENABLED

if STRIPE_ENABLED:
    stripe.api_key = STRIPE_SECRET_KEY
    print("✅ Stripe enabled with real keys")
elif STRIPE_DEMO_MODE:
    # Use a valid-looking test key format for demo mode (Stripe.js needs valid format)
    # This key format is accepted by Stripe.js for initialization but won't work for real payments
    STRIPE_PUBLISHABLE_KEY = "pk_test_51DemoMode00000000000000000000000000000000000000000000000000000000000000000000"
    stripe.api_key = None  # No real API calls in demo mode
    print("🎮 Stripe DEMO MODE enabled - payments will be simulated (no real charges)")
else:
    stripe.api_key = None

# Basic role handling: admin emails are configured via environment for now.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# Staff registration secret code
STAFF_REGISTRATION_CODE = os.environ.get("STAFF_REGISTRATION_CODE", "1234")
# Senior manager code for staff removal
SENIOR_MANAGER_CODE = os.environ.get("SENIOR_MANAGER_CODE", "1234")

# Tax rate for prepared food (7.5% is a common rate in many US states)
TAX_RATE = float(os.environ.get("TAX_RATE", "0.075"))  # 7.5% default

# Configure logging for the Flask app (file handler is set up in foodtruck.py as well).
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Backend instance (rename brand)
my_truck = FoodTruck("Item7 Food Truck", "GSU Campus")

# Initialize CSV files on startup
try:
    my_truck.initialize_csv_files()
    my_truck.load_staff_from_csv()
    my_truck.load_schedules_from_csv()
    my_truck.load_orders_from_csv()
    my_truck.load_deals_from_csv()
    # Load shifts if method exists (it's defined in foodtruck.py)
    if hasattr(my_truck, 'load_shifts_from_csv'):
        my_truck.load_shifts_from_csv()
    # Load menu items
    if hasattr(my_truck, 'load_menu_from_csv'):
        my_truck.load_menu_from_csv()
    logger.info("CSV files initialized and loaded successfully")
except Exception as e:
    logger.error(f"Error initializing CSV files: {e}", exc_info=True)
    print(f"⚠️  Warning: Error initializing CSV files: {e}")


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


def require_staff_access():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect
    if not (session.get("is_staff") or "admin" in session):
        flash("Staff portal is restricted to Item7 staff.", "error")
        return redirect(url_for("welcome"))
    return None


@app.context_processor
def inject_globals():
    cart = get_cart()
    cart_count = sum(int(item.get("qty", 0)) for item in cart.values())
    user_email = session.get("user_email")
    user = my_truck.get_user_details(user_email) if user_email else None
    is_senior_manager = session.get("senior_manager_verified", False)
    return dict(
        is_admin=("admin" in session),
        is_senior_manager=is_senior_manager,
        is_staff=session.get("is_staff"),
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
    # Ensure menu is loaded
    if hasattr(my_truck, 'load_menu_from_csv'):
        my_truck.load_menu_from_csv()
    
    menu_items = my_truck.get_menu_items()
    featured_items = menu_items[:4] if menu_items else []
    active_deals = my_truck.get_active_deals()
    
    return render_template(
        "home.html",
        featured_items=featured_items,
        active_deals=active_deals,
        staff_count=len(my_truck.staff),
        schedule_count=len(my_truck.schedules),
        title="Home - Item7 Food Truck",
    )


@app.route("/menu")
def menu_page():
    menu_items = my_truck.get_menu_items()
    # Group items by category
    categories = {}
    for item in menu_items:
        cat = item.get("category", "Other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)
    
    return render_template("menu.html", menu_items=menu_items, categories=categories, title="Menu")


# --- Staff Portal Helpers ---

def build_staff_portal_context():
    user_email = session.get("user_email")
    if not user_email:
        return None

    try:
        user = my_truck.get_user_details(user_email)
        if not user:
            return None

        if user.get("role", "staff") != "staff" and "admin" not in session:
            return None

        my_truck.load_schedules_from_csv()
        my_truck.load_staff_from_csv()

        def parse_schedule(entry):
            try:
                date_str = entry.get("date", "")
                time_str = entry.get("time", "")
                if date_str and time_str:
                    schedule_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                    return schedule_dt
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Error parsing schedule: {e}, entry: {entry}")
            return datetime.max

        user_schedules = []
        for s in my_truck.schedules:
            if s.get("staff_email", "").lower() == user_email.lower():
                parsed_schedule = {**s, "datetime": parse_schedule(s)}
                user_schedules.append(parsed_schedule)
        
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
            shifts = []
            for s in user_schedules:
                try:
                    dt = s.get("datetime")
                    if dt and dt != datetime.max:
                        if dt.date() == day:
                            shifts.append(s)
                except (AttributeError, TypeError):
                    continue
            week_overview.append(
                {
                    "date": day,
                    "label": label,
                    "shifts": shifts,
                    "is_working_day": label in WORKING_DAYS,
                }
            )

        staff_preview = my_truck.staff[:4] if my_truck.staff else []
        staff_list = list(my_truck.staff)

        return dict(
            user=user,
            next_shift=next_shift,
            upcoming_schedules=upcoming_schedules[:5],
            next_available_date=next_available_date,
            available_slots=available_slots,
            stats=stats,
            week_overview=week_overview,
            staff_preview=staff_preview,
            staff_list=staff_list,
            time_slots=TIME_SLOTS,
        )
    except Exception as e:
        logger.error(f"Error building staff portal context: {e}", exc_info=True)
        return None


@app.route("/staff")
def staff_portal_root():
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    return redirect(url_for("staff_dashboard"))


def render_staff_template(template, **extra):
    ctx = build_staff_portal_context()
    if ctx is None:
        session.pop("is_staff", None)
        session.pop("user_email", None)
        session.pop("user_name", None)
        flash("Please sign in again to access the staff portal.", "error")
        return redirect(url_for("login"))
    ctx.update(extra)
    ctx.setdefault("api_url", url_for("api_appointments"))
    return render_template(template, **ctx)


@app.route("/staff/dashboard")
def staff_dashboard():
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    return render_staff_template(
        "staff_dashboard.html",
        active_tab="dashboard",
        title="Staff Portal - Dashboard",
    )


@app.route("/staff/management")
def staff_management():
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect

    ctx = build_staff_portal_context()
    if ctx is None:
        flash("Staff portal is restricted to Item7 staff.", "error")
        return redirect(url_for("home"))

    query_raw = request.args.get("q", "")
    query = query_raw.strip().lower()

    def matches(staff):
        if not query:
            return True
        haystacks = [
            staff.get("first", ""),
            staff.get("last", ""),
            staff.get("email", ""),
            staff.get("phone", ""),
        ]
        return any(query in (value or "").lower() for value in haystacks)

    filtered_staff = [staff for staff in ctx["staff_list"] if matches(staff)]

    # Check if user is verified as senior manager
    is_senior_manager = session.get("senior_manager_verified", False)

    ctx.update(
        dict(
            staff_filtered=filtered_staff,
            search_query=query_raw,
            active_tab="staff",
            title="Staff Portal - Staff Management",
            api_url=url_for("api_appointments"),
            is_senior_manager=is_senior_manager,
        )
    )
    return render_template("staff_management.html", **ctx)


@app.route("/staff/verify-senior-manager", methods=["POST"])
def verify_senior_manager():
    """Verify senior manager status with secret code"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    code = sanitize_text(request.form.get("senior_manager_code", "")).strip()
    
    if code == SENIOR_MANAGER_CODE:
        session["senior_manager_verified"] = True
        flash("Senior manager access granted. You can now manage staff.", "success")
        logger.info(f"Senior manager verified: {session.get('user_email')}")
    else:
        flash("Invalid senior manager code. Access denied.", "error")
        logger.warning(f"Failed senior manager verification attempt: {session.get('user_email')}")
    
    return redirect(url_for("staff_management"))


@app.route("/staff/revoke-senior-manager", methods=["POST"])
def revoke_senior_manager():
    """Revoke senior manager access"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    session.pop("senior_manager_verified", None)
    flash("Senior manager access revoked.", "info")
    logger.info(f"Senior manager access revoked: {session.get('user_email')}")
    
    return redirect(url_for("staff_management"))


@app.route("/staff/remove-staff", methods=["POST"])
def remove_staff():
    """Remove a staff member from the directory"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    # Check senior manager verification
    if not session.get("senior_manager_verified", False):
        flash("Senior manager verification required to remove staff members.", "error")
        return redirect(url_for("staff_management"))
    
    staff_email = sanitize_text(request.form.get("staff_email", "")).strip().lower()
    
    if not staff_email:
        flash("Invalid staff email.", "error")
        return redirect(url_for("staff_management"))
    
    # Prevent removing yourself
    current_user_email = session.get("user_email", "").lower()
    if staff_email == current_user_email:
        flash("You cannot remove yourself from the staff directory.", "error")
        return redirect(url_for("staff_management"))
    
    # Remove staff from CSV
    try:
        my_truck.load_staff_from_csv()
        path = "data/users.csv"
        
        exists, readable, writable = my_truck.check_file_permissions(path)
        if not exists:
            flash("Users file not found.", "error")
            return redirect(url_for("staff_management"))
        if not readable or not writable:
            flash("Permission denied. Cannot modify staff directory.", "error")
            logger.error(f"Cannot access users CSV for staff removal: {path}")
            return redirect(url_for("staff_management"))
        
        # Read all staff
        rows = []
        staff_found = False
        
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            for row in reader:
                row_email = row.get("Email", "").strip().lower()
                if row_email != staff_email:
                    rows.append(row)
                else:
                    staff_found = True
        
        if not staff_found:
            flash("Staff member not found.", "error")
            logger.warning(f"Attempted to remove non-existent staff: {staff_email}")
            return redirect(url_for("staff_management"))
        
        # Write back without the removed staff
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        # Reload staff list
        my_truck.load_staff_from_csv()
        
        flash(f"Staff member {staff_email} has been removed from the directory.", "success")
        logger.info(f"Staff removed by senior manager: {staff_email} (removed by {current_user_email})")
        
    except FileNotFoundError:
        flash("Users file not found.", "error")
        logger.error("Users CSV file not found when removing staff")
    except PermissionError:
        flash("Permission denied. Cannot modify staff directory.", "error")
        logger.error("Permission error removing staff")
    except Exception as e:
        flash(f"Error removing staff member: {str(e)}", "error")
        logger.error(f"Error removing staff: {e}", exc_info=True)
    
    return redirect(url_for("staff_management"))


@app.route("/staff/deals", methods=["GET"])
def manage_deals():
    """Page for senior managers to create and manage deals"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    if not session.get("senior_manager_verified", False):
        flash("Senior manager verification required to manage deals.", "error")
        return redirect(url_for("staff_management"))
    
    my_truck.load_deals_from_csv()
    all_deals = my_truck.deals
    active_deals = my_truck.get_active_deals()
    
    ctx = build_staff_portal_context()
    if ctx is None:
        flash("Staff portal is restricted to Item7 staff.", "error")
        return redirect(url_for("home"))
    
    ctx.update({
        "active_tab": "deals",
        "title": "Staff Portal - Manage Deals",
        "all_deals": all_deals,
        "active_deals": active_deals,
        "is_senior_manager": True,
    })
    
    return render_template("staff_deals.html", **ctx)


@app.route("/staff/deals/create", methods=["POST"])
def create_deal():
    """Create a new deal/promotion"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    if not session.get("senior_manager_verified", False):
        flash("Senior manager verification required to create deals.", "error")
        return redirect(url_for("staff_management"))
    
    title = sanitize_text(request.form.get("title", "")).strip()
    description = sanitize_text(request.form.get("description", "")).strip()
    discount = sanitize_text(request.form.get("discount", "")).strip()
    expires_at = sanitize_text(request.form.get("expires_at", "")).strip()
    
    if not title or not description or not discount:
        flash("Title, description, and discount are required.", "error")
        return redirect(url_for("manage_deals"))
    
    created_by = session.get("user_email", "Unknown")
    
    success = my_truck.add_deal_to_csv(
        title=title,
        description=description,
        discount=discount,
        created_by=created_by,
        expires_at=expires_at if expires_at else None,
    )
    
    if success:
        flash(f"Deal '{title}' created successfully! It will appear on the homepage.", "success")
        logger.info(f"Deal created by {created_by}: {title}")
    else:
        flash("Error creating deal. Please try again.", "error")
    
    return redirect(url_for("manage_deals"))


# ---------- MENU MANAGEMENT ----------

@app.route("/staff/menu", methods=["GET"])
def manage_menu():
    """Page for staff to manage menu items"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    my_truck.load_menu_from_csv()
    menu_items = my_truck.get_menu_items()
    
    # Group by category
    categories = {}
    for item in menu_items:
        cat = item.get("category", "Other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)
    
    context = build_staff_portal_context()
    context.update({
        "menu_items": menu_items,
        "categories": categories,
        "active_tab": "menu",
    })
    
    return render_template("staff_menu.html", **context)


@app.route("/staff/menu/add", methods=["POST"])
def add_menu_item():
    """Add a new menu item"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    try:
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "0").strip()
        category = request.form.get("category", "Other").strip()
        vegan = request.form.get("vegan", "").lower() == "true"
        allergens_str = request.form.get("allergens", "").strip()
        allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
        
        # Handle image upload
        image_filename = "burger.svg"  # Default
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename:
                # Save uploaded file
                filename = file.filename
                # Sanitize filename
                import re
                filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
                # Ensure unique filename
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{filename}"
                
                upload_path = os.path.join("static", "images", "menu", filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                file.save(upload_path)
                image_filename = f"menu/{filename}"
        
        # Validate inputs
        if not name:
            flash("Item name is required.", "error")
            return redirect(url_for("manage_menu"))
        
        try:
            price_float = float(price)
            if price_float <= 0:
                raise ValueError("Price must be positive")
        except ValueError:
            flash("Invalid price. Please enter a valid number.", "error")
            return redirect(url_for("manage_menu"))
        
        success = my_truck.add_menu_item(name, description, price_float, category, vegan, image_filename, allergens)
        
        if success:
            flash(f"✅ Menu item '{name}' added successfully!", "success")
            logger.info(f"Menu item added: {name} by {session.get('user_email')}")
        else:
            flash("Error adding menu item. Please try again.", "error")
        
    except Exception as e:
        logger.error(f"Error in add_menu_item: {e}", exc_info=True)
        flash("An error occurred. Please try again.", "error")
    
    return redirect(url_for("manage_menu"))


@app.route("/staff/menu/edit/<item_id>", methods=["GET", "POST"])
def edit_menu_item(item_id):
    """Edit an existing menu item"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            price = request.form.get("price", "0").strip()
            category = request.form.get("category", "Other").strip()
            vegan = request.form.get("vegan", "").lower() == "true"
            allergens_str = request.form.get("allergens", "").strip()
            allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
            
            # Get existing item to preserve image if not uploaded
            existing_item = my_truck.get_menu_item_by_id(item_id)
            image_filename = existing_item.get("image", "burger.svg") if existing_item else "burger.svg"
            
            # Check if user wants to remove the current image
            remove_image = request.form.get("remove_image", "").strip() == "1"
            
            if remove_image:
                # User wants to remove the current image
                # Delete the physical file if it exists and is an uploaded file (in menu/ folder)
                if image_filename and image_filename.startswith("menu/"):
                    try:
                        image_path = os.path.join("static", "images", image_filename)
                        if os.path.exists(image_path):
                            os.remove(image_path)
                            logger.info(f"Deleted image file: {image_path}")
                    except Exception as e:
                        logger.warning(f"Could not delete image file {image_path}: {e}")
                
                # Set to default image based on category
                if category.lower() == "drink":
                    image_filename = "drink.svg"
                elif category.lower() in ["side", "veg"]:
                    image_filename = "fries.svg" if category.lower() == "side" else "veggie.svg"
                else:
                    image_filename = "burger.svg"
            
            # Handle image upload if provided (this will override the remove_image action)
            if "image" in request.files:
                file = request.files["image"]
                if file and file.filename:
                    # Save uploaded file
                    filename = file.filename
                    import re
                    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{timestamp}_{filename}"
                    
                    upload_path = os.path.join("static", "images", "menu", filename)
                    os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                    file.save(upload_path)
                    image_filename = f"menu/{filename}"
            
            # Validate inputs
            if not name:
                flash("Item name is required.", "error")
                return redirect(url_for("manage_menu"))
            
            try:
                price_float = float(price)
                if price_float <= 0:
                    raise ValueError("Price must be positive")
            except ValueError:
                flash("Invalid price. Please enter a valid number.", "error")
                return redirect(url_for("manage_menu"))
            
            success = my_truck.update_menu_item(item_id, name, description, price_float, category, vegan, image_filename, allergens)
            
            if success:
                flash(f"✅ Menu item '{name}' updated successfully!", "success")
                logger.info(f"Menu item updated: {item_id} - {name} by {session.get('user_email')}")
            else:
                flash("Error updating menu item. Please try again.", "error")
            
        except Exception as e:
            logger.error(f"Error in edit_menu_item: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")
        
        return redirect(url_for("manage_menu"))
    
    # GET request - show edit form
    item = my_truck.get_menu_item_by_id(item_id)
    if not item:
        flash("Menu item not found.", "error")
        return redirect(url_for("manage_menu"))
    
    context = build_staff_portal_context()
    context.update({
        "item": item,
        "active_tab": "menu",
    })
    
    return render_template("staff_menu_edit.html", **context)


@app.route("/staff/menu/delete/<item_id>", methods=["POST"])
def delete_menu_item(item_id):
    """Delete a menu item"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    try:
        item = my_truck.get_menu_item_by_id(item_id)
        item_name = item.get("name", "Unknown") if item else "Unknown"
        
        success = my_truck.delete_menu_item(item_id)
        
        if success:
            flash(f"✅ Menu item '{item_name}' deleted successfully!", "success")
            logger.info(f"Menu item deleted: {item_id} - {item_name} by {session.get('user_email')}")
        else:
            flash("Error deleting menu item. Please try again.", "error")
        
    except Exception as e:
        logger.error(f"Error in delete_menu_item: {e}", exc_info=True)
        flash("An error occurred. Please try again.", "error")
    
    return redirect(url_for("manage_menu"))


@app.route("/staff/statistics")
def staff_statistics():
    """Statistics dashboard for staff"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect

    my_truck.load_orders_from_csv()
    my_truck.load_staff_from_csv()
    
    now = datetime.now()
    today = now.date()
    this_month_start = today.replace(day=1)
    this_year_start = today.replace(month=1, day=1)
    
    # Parse orders and calculate statistics
    all_orders = my_truck.orders
    today_orders = [o for o in all_orders if o.get("timestamp", "").startswith(today.isoformat())]
    month_orders = [o for o in all_orders if o.get("timestamp", "").startswith(this_month_start.isoformat()[:7])]
    year_orders = [o for o in all_orders if o.get("timestamp", "").startswith(this_year_start.isoformat()[:4])]
    
    # Calculate totals - we'll estimate based on order count
    # In a real system, you'd store the total with each order
    # For now, we'll use an average order value estimate
    AVG_ORDER_VALUE = 12.50  # Estimated average order value
    
    today_total = len(today_orders) * AVG_ORDER_VALUE
    month_total = len(month_orders) * AVG_ORDER_VALUE
    year_total = len(year_orders) * AVG_ORDER_VALUE
    
    # Customer order counts
    customer_orders = {}
    for order in all_orders:
        email = order.get("customer_email", "").lower()
        if email:
            customer_orders[email] = customer_orders.get(email, 0) + 1
    
    top_customers = sorted(customer_orders.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Orders with allergies
    allergy_orders = [o for o in all_orders if o.get("allergy_info", "").strip()]
    unsafe_orders = [o for o in all_orders if o.get("is_safe", "") == "NO"]
    
    # Recent orders (last 20)
    recent_orders = sorted(all_orders, key=lambda x: x.get("timestamp", ""), reverse=True)[:20]
    
    ctx = build_staff_portal_context()
    if ctx is None:
        flash("Staff portal is restricted to Item7 staff.", "error")
        return redirect(url_for("home"))
    
    ctx.update({
        "today_orders": today_orders,
        "month_orders": month_orders,
        "year_orders": year_orders,
        "today_total": today_total,
        "month_total": month_total,
        "year_total": year_total,
        "today_count": len(today_orders),
        "month_count": len(month_orders),
        "year_count": len(year_orders),
        "top_customers": top_customers,
        "allergy_orders": allergy_orders,
        "unsafe_orders": unsafe_orders,
        "recent_orders": recent_orders,
        "active_tab": "statistics",
        "title": "Staff Portal - Statistics",
    })
    
    return render_template("staff_statistics.html", **ctx)


@app.route("/staff/orders")
def staff_orders():
    """View orders for staff on duty"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect

    my_truck.load_orders_from_csv()
    
    # Get filter parameters
    filter_status = request.args.get("status", "all")  # all, pending, preparation_done, ready_for_delivery
    search_query = request.args.get("q", "").strip().lower()
    
    all_orders = my_truck.orders
    
    # Filter orders by status
    if filter_status != "all":
        all_orders = [o for o in all_orders if o.get("status", "Pending").lower() == filter_status.lower()]
    
    # Filter orders by search query
    filtered_orders = all_orders
    if search_query:
        filtered_orders = [
            o for o in filtered_orders
            if search_query in o.get("customer_name", "").lower() or
               search_query in o.get("customer_email", "").lower() or
               search_query in o.get("item", "").lower()
        ]
    
    # Sort by timestamp (newest first)
    filtered_orders = sorted(filtered_orders, key=lambda x: x.get("timestamp", ""), reverse=True)
    
    ctx = build_staff_portal_context()
    if ctx is None:
        flash("Staff portal is restricted to Item7 staff.", "error")
        return redirect(url_for("home"))
    
    ctx.update({
        "orders": filtered_orders,
        "all_orders": my_truck.orders,  # Keep all orders for stats
        "filter_status": filter_status,
        "search_query": request.args.get("q", ""),
        "active_tab": "orders",
        "title": "Staff Portal - Orders",
    })
    
    return render_template("staff_orders.html", **ctx)


@app.route("/staff/update-order-status", methods=["POST"])
def update_order_status():
    """Update order status (Pending -> Preparation Done -> Ready for Delivery)"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect

    order_id = request.form.get("order_id")
    new_status = request.form.get("status")
    
    if not order_id or not new_status:
        flash("Invalid order or status.", "error")
        return redirect(url_for("staff_orders"))
    
    valid_statuses = ["Pending", "Preparation Done", "Ready for Delivery"]
    if new_status not in valid_statuses:
        flash("Invalid status.", "error")
        return redirect(url_for("staff_orders"))
    
    try:
        # Update order status in CSV
        path = "data/orders.csv"
        my_truck.load_orders_from_csv()
        
        # Check if order exists
        order_exists = any(str(o.get("order_id", "")) == str(order_id) for o in my_truck.orders)
        if not order_exists:
            flash("Order not found.", "error")
            return redirect(url_for("staff_orders"))
        
        rows = []
        order_found = False
        
        exists, readable, writable = my_truck.check_file_permissions(path)
        if not exists or not readable or not writable:
            flash("Cannot access orders file.", "error")
            return redirect(url_for("staff_orders"))
        
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            
            # Ensure Status column exists
            if "Status" not in fieldnames:
                fieldnames.append("Status")
            
            for row in reader:
                # Ensure all rows have Status field
                if "Status" not in row:
                    row["Status"] = "Pending"
                
                if str(row.get("Order_ID", "")) == str(order_id):
                    row["Status"] = new_status
                    order_found = True
                
                rows.append(row)
        
        if not order_found:
            flash("Order not found.", "error")
            return redirect(url_for("staff_orders"))
        
        # Write back with updated status
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        # Reload orders
        my_truck.load_orders_from_csv()
        
        status_messages = {
            "Preparation Done": "Order marked as preparation complete!",
            "Ready for Delivery": "Order ready for delivery handoff!",
            "Pending": "Order status reset to pending."
        }
        
        flash(status_messages.get(new_status, "Order status updated."), "success")
        logger.info(f"Order {order_id} status updated to {new_status} by {session.get('user_email')}")
        
    except FileNotFoundError:
        flash("Orders file not found.", "error")
        logger.error("Orders CSV file not found when updating status")
    except PermissionError as e:
        flash("Permission denied. Cannot update order status.", "error")
        logger.error(f"Permission error updating order status: {e}")
    except Exception as e:
        flash(f"Error updating order status: {str(e)}", "error")
        logger.error(f"Error updating order status: {e}", exc_info=True)
    
    return redirect(url_for("staff_orders"))


@app.route("/staff/schedule")
def staff_schedule():
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    ctx = build_staff_portal_context()
    if ctx is None:
        flash("Staff portal is restricted to Item7 staff.", "error")
        return redirect(url_for("home"))
    
    user_email = session.get("user_email")
    user = ctx["user"]
    
    # Get staff shifts
    if hasattr(my_truck, 'load_shifts_from_csv'):
        my_truck.load_shifts_from_csv()
        all_shifts = my_truck.get_staff_shifts(user_email)
        
        # Get today's shift (if any)
        today = datetime.now().date()
        today_shifts = [s for s in all_shifts if s.get("date") == today.isoformat()]
        active_shift = None
        for shift in today_shifts:
            status = shift.get("status", "scheduled")
            if status in ["checked_in", "on_break"]:
                active_shift = shift
                break
        
        # Get upcoming shifts (next 7 days)
        upcoming_shifts = []
        for i in range(7):
            check_date = (today + timedelta(days=i)).isoformat()
            day_shifts = [s for s in all_shifts if s.get("date") == check_date]
            if day_shifts:
                upcoming_shifts.extend(day_shifts)
        
        # Get past shifts with hours worked (last 14 days)
        past_shifts = []
        for i in range(1, 15):
            check_date = (today - timedelta(days=i)).isoformat()
            day_shifts = [s for s in all_shifts if s.get("date") == check_date and s.get("status") == "completed"]
            if day_shifts:
                past_shifts.extend(day_shifts)
        
        past_shifts.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        # Calculate total hours this week
        week_start = today - timedelta(days=today.weekday())
        week_shifts = [s for s in all_shifts if s.get("date") >= week_start.isoformat() and s.get("status") == "completed"]
        total_week_hours = sum(float(s.get("total_hours", 0) or 0) for s in week_shifts)
    else:
        active_shift = None
        upcoming_shifts = []
        past_shifts = []
        total_week_hours = 0.0
        today = datetime.now().date()
    
    ctx.update(
        dict(
            active_tab="schedule",
            title="Staff Portal - Time Clock",
            active_shift=active_shift,
            upcoming_shifts=upcoming_shifts[:10],
            past_shifts=past_shifts[:10],
            total_week_hours=total_week_hours,
            today=today,
        )
    )
    
    return render_template("staff_schedule.html", **ctx)


@app.route("/staff/profile")
def staff_profile():
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    return render_staff_template(
        "staff_profile.html",
        active_tab="profile",
        title="Staff Portal - My Profile",
    )


@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    try:
        item_name = request.form.get("item_name")
        price_str = request.form.get("price")
        
        if not item_name:
            flash("Invalid item name.", "error")
            return redirect(url_for("menu_page"))
        
        try:
            price = float(price_str)
            if price < 0:
                flash("Invalid price.", "error")
                return redirect(url_for("menu_page"))
        except (ValueError, TypeError):
            flash("Invalid price format.", "error")
            return redirect(url_for("menu_page"))
        
        redirect_to = request.form.get("redirect_to", url_for("menu_page"))

        cart = get_cart()
        if item_name in cart:
            # Limit max quantity
            if cart[item_name].get("qty", 0) >= 99:
                flash(f"Maximum quantity (99) reached for {item_name}.", "warning")
            else:
                cart[item_name]["qty"] = cart[item_name].get("qty", 0) + 1
                flash(f"Added {item_name} to cart", "success")
        else:
            cart[item_name] = {"price": price, "qty": 1}
            flash(f"Added {item_name} to cart", "success")
        
        save_cart(cart)

    except Exception as e:
        logger.error(f"Error adding to cart: {e}", exc_info=True)
        flash("Error adding item to cart. Please try again.", "error")
        redirect_to = url_for("menu_page")

    return redirect(redirect_to)


@app.route("/cart")
def cart_page():
    try:
        cart = get_cart()
        subtotal = sum(float(item.get("price", 0)) * int(item.get("qty", 0)) for item in cart.values())
        tax_amount = subtotal * TAX_RATE
        total = subtotal + tax_amount
        return render_template("cart.html", cart=cart, subtotal=subtotal, tax_amount=tax_amount, total=total, tax_rate=TAX_RATE, title="Your Cart")
    except Exception as e:
        logger.error(f"Error in cart_page: {e}", exc_info=True)
        flash("Error loading cart. Please try again.", "error")
        return redirect(url_for("menu_page"))


@app.route("/cart/clear")
def clear_cart():
    save_cart({})
    return redirect(url_for("cart_page"))


@app.route("/cart/update", methods=["POST"])
def update_cart():
    """Update quantity of an item in the cart"""
    try:
        item_name = request.form.get("item_name")
        if not item_name:
            flash("Invalid item name.", "error")
            return redirect(url_for("cart_page"))
        
        try:
            new_qty = int(request.form.get("qty", 1))
            if new_qty < 1:
                new_qty = 1
            if new_qty > 99:
                new_qty = 99
                flash("Maximum quantity is 99 per item.", "warning")
        except (ValueError, TypeError):
            flash("Invalid quantity.", "error")
            return redirect(url_for("cart_page"))
        
        cart = get_cart()
        if item_name not in cart:
            flash("Item not found in cart.", "error")
            return redirect(url_for("cart_page"))
        
        cart[item_name]["qty"] = new_qty
        save_cart(cart)
        flash(f"Updated {item_name} quantity to {new_qty}", "success")
        
    except Exception as e:
        logger.error(f"Error updating cart: {e}", exc_info=True)
        flash("Error updating cart. Please try again.", "error")
    
    return redirect(url_for("cart_page"))


@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    """Remove an item from the cart"""
    try:
        item_name = request.form.get("item_name")
        if not item_name:
            flash("Invalid item name.", "error")
            return redirect(url_for("cart_page"))
        
        cart = get_cart()
        if item_name in cart:
            del cart[item_name]
            save_cart(cart)
            flash(f"Removed {item_name} from cart", "success")
        else:
            flash("Item not found in cart.", "error")
        
    except Exception as e:
        logger.error(f"Error removing from cart: {e}", exc_info=True)
        flash("Error removing item from cart. Please try again.", "error")
    
    return redirect(url_for("cart_page"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    try:
        cart = get_cart()
        if not cart:
            flash("Your cart is empty.", "warning")
            return redirect(url_for("menu_page"))

        # Validate cart data
        try:
            subtotal = sum(float(item.get("price", 0)) * int(item.get("qty", 0)) for item in cart.values())
            if subtotal <= 0:
                flash("Invalid cart total.", "error")
                return redirect(url_for("cart_page"))
            
            # Calculate tax
            tax_amount = subtotal * TAX_RATE
            total = subtotal + tax_amount
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error calculating cart total: {e}")
            flash("Error processing cart. Please try again.", "error")
            return redirect(url_for("cart_page"))

        items_summary = ", ".join(
            f"{name} x{item.get('qty', 0)}" for name, item in cart.items()
        )

        # Calculate tax for display
        tax_amount = subtotal * TAX_RATE

        # Get user info if logged in
        user_email = session.get("user_email")
        user = my_truck.get_user_details(user_email) if user_email else None
        is_logged_in = user_email is not None and user is not None

        if request.method == "POST":
            # If logged in, use session data; otherwise use form data
            if is_logged_in and user:
                customer_name = f"{user.get('first', '')} {user.get('last', '')}".strip()
                customer_email = user_email
            else:
                customer_name = request.form.get("customer_name", "").strip()
                customer_email = request.form.get("customer_email", "").strip().lower()
            
            # Validate customer info
            if not customer_name or not customer_name.replace(" ", ""):
                flash("Customer name is required.", "error")
                return render_template(
                    "checkout.html",
                    cart=cart,
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total=total,
                    items_summary=items_summary,
                    tax_rate=TAX_RATE,
                    customer_name=customer_name if not is_logged_in else (user.get('first', '') + ' ' + user.get('last', '')).strip() if user else "",
                    customer_email=customer_email if not is_logged_in else user_email,
                    is_logged_in=is_logged_in,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY if (STRIPE_ENABLED or STRIPE_DEMO_MODE) else "",
                    stripe_enabled=(STRIPE_ENABLED or STRIPE_DEMO_MODE),
                    stripe_demo_mode=STRIPE_DEMO_MODE,
                    title="Checkout",
                )
            
            if not customer_email or "@" not in customer_email:
                flash("Valid customer email is required.", "error")
                return render_template(
                    "checkout.html",
                    cart=cart,
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total=total,
                    items_summary=items_summary,
                    tax_rate=TAX_RATE,
                    customer_name=customer_name if not is_logged_in else (user.get('first', '') + ' ' + user.get('last', '')).strip() if user else "",
                    customer_email=customer_email if not is_logged_in else user_email,
                    is_logged_in=is_logged_in,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY if (STRIPE_ENABLED or STRIPE_DEMO_MODE) else "",
                    stripe_enabled=(STRIPE_ENABLED or STRIPE_DEMO_MODE),
                    stripe_demo_mode=STRIPE_DEMO_MODE,
                    title="Checkout",
                )
            
            allergy_info = request.form.get("allergy_info", "").strip()
            delivery_address = request.form.get("delivery_address", "").strip()
            delivery_lat = request.form.get("delivery_lat", "")
            delivery_lng = request.form.get("delivery_lng", "")
            payment_method = request.form.get("payment_method", "cash")
            
            # Get tip amount
            try:
                tip_amount = float(request.form.get("tip_amount", "0") or "0")
                tip_percentage = float(request.form.get("tip_percentage", "0") or "0")
            except (ValueError, TypeError):
                tip_amount = 0.0
                tip_percentage = 0.0
            
            # Calculate final total with tip (tax already included in total)
            # total = subtotal + tax, so final_total = subtotal + tax + tip
            final_total = total + tip_amount
            
            # Handle Stripe payment
            if payment_method == "stripe":
                stripe_token = request.form.get("stripeToken")
                if not stripe_token:
                    flash("Payment processing error. Please try again.", "error")
                    return redirect(url_for("checkout"))
                
                if STRIPE_DEMO_MODE:
                    # DEMO MODE: Simulate successful payment
                    import random
                    import string
                    payment_status = "paid"
                    payment_id = "demo_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=24))
                    logger.info(f"DEMO MODE: Simulated Stripe payment - {payment_id}")
                elif STRIPE_ENABLED:
                    try:
                        # Real Stripe payment (include tip in charge)
                        charge = stripe.Charge.create(
                            amount=int(final_total * 100),  # Convert to cents, include tip
                            currency='usd',
                            description=f'Order from {my_truck.name}',
                            source=stripe_token,
                        )
                        payment_status = "paid"
                        payment_id = charge.id
                    except stripe.error.StripeError as e:
                        flash(f"Payment failed: {str(e)}", "error")
                        logger.error(f"Stripe payment error: {e}")
                        return redirect(url_for("checkout"))
                else:
                    flash("Stripe payment is not configured. Please use cash on delivery.", "error")
                    return redirect(url_for("checkout"))
            else:
                # Cash on delivery
                payment_status = "pending"
                payment_id = "cash_on_delivery"

            # Add order with delivery info
            order_info = items_summary
            if delivery_address:
                order_info += f" | Delivery: {delivery_address}"
            order_info += f" | Tax: ${tax_amount:.2f}"
            if tip_amount > 0:
                order_info += f" | Tip: ${tip_amount:.2f}"
            if payment_method == "stripe":
                order_info += f" | Payment: Stripe ({payment_id})"
            else:
                order_info += " | Payment: Cash on Delivery"

            try:
                my_truck.add_order_to_csv(
                    customer_name, customer_email, order_info, allergy_info
                )
                my_truck.load_orders_from_csv()
            except Exception as e:
                logger.error(f"Error saving order: {e}", exc_info=True)
                flash("Error saving order. Please try again.", "error")
                return redirect(url_for("checkout"))

            save_cart({})

            return render_template(
                "checkout_success.html",
                customer_name=customer_name,
                total=final_total,
                subtotal=subtotal,
                tax_amount=tax_amount,
                tip_amount=tip_amount,
                payment_method=payment_method,
                payment_id=payment_id if payment_method == "stripe" else None,
                title="Order Confirmed",
            )

        # Pre-fill customer info if logged in
        customer_name = ""
        customer_email = ""
        if is_logged_in and user:
            customer_name = f"{user.get('first', '')} {user.get('last', '')}".strip()
            customer_email = user_email

        return render_template(
            "checkout.html",
            cart=cart,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
            items_summary=items_summary,
            tax_rate=TAX_RATE,
            customer_name=customer_name,
            customer_email=customer_email,
            is_logged_in=is_logged_in,
            stripe_publishable_key=STRIPE_PUBLISHABLE_KEY if (STRIPE_ENABLED or STRIPE_DEMO_MODE) else "",
            stripe_enabled=(STRIPE_ENABLED or STRIPE_DEMO_MODE),
            stripe_demo_mode=STRIPE_DEMO_MODE,
            title="Checkout",
        )
    
    except Exception as e:
        logger.error(f"Error in checkout: {e}", exc_info=True)
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("cart_page"))


# ---------- AUTH (MANAGER LOGIN/REGISTRATION) ----------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """User registration with detailed staff information"""
    if request.method == "POST":
        email = sanitize_text(request.form.get("email", "")).strip().lower()
        # Ensure email is valid format
        if "@" not in email or "." not in email.split("@")[1]:
            flash("Please provide a valid email address.", "error")
            return render_template("signup.html", title="Register")
        password = request.form.get("password") or ""
        account_type = request.form.get("account_type", "staff")
        staff_code = sanitize_text(request.form.get("staff_code", "")).strip()
        first = sanitize_text(request.form.get("first", "")).strip()
        last = sanitize_text(request.form.get("last", "")).strip()
        phone = sanitize_text(request.form.get("phone", "")).strip()
        address = sanitize_text(request.form.get("address", "")).strip()
        dob = sanitize_text(request.form.get("dob", "")).strip()
        sex = sanitize_text(request.form.get("sex", "")).strip()

        # Validate required fields
        if not email or "@" not in email:
            flash("Please provide a valid email address.", "error")
            return render_template("signup.html", title="Register")
        
        if not password or len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("signup.html", title="Register")
        
        if not first or not last:
            flash("Please provide both first and last name.", "error")
            return render_template("signup.html", title="Register")

        # Validate staff registration code if registering as staff
        if account_type == "staff":
            if not staff_code or staff_code != STAFF_REGISTRATION_CODE:
                flash(f"Invalid staff registration code. Staff registration requires a valid code.", "error")
                logger.warning(f"Failed staff registration attempt for {email} - invalid code")
                return render_template("signup.html", title="Register", account_type=account_type)

        # Check if user already exists (case-insensitive)
        my_truck.load_staff_from_csv()  # Ensure we have latest data
        if my_truck.user_exists(email):
            flash("This email is already registered. Please login instead or use a different email.", "error")
            logger.warning(f"Registration attempt with existing email: {email}")
            return redirect(url_for("login", email=email))

        # Add new user
        try:
            logger.info(f"Starting registration for: {email}")
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            logger.info(f"Password hashed successfully for: {email}")
            role_value = "staff" if account_type == "staff" else "customer"
            logger.info(f"Adding user to CSV: {email}, role: {role_value}")
            
            my_truck.add_staff_to_csv(
                email,
                hashed_password,
                first,
                last,
                phone,
                address,
                dob,
                sex,
                role=role_value,
                verified="YES",  # Auto-verify users on registration
            )
            logger.info(f"User successfully added to CSV: {email}")
            
            # Verify user was saved
            my_truck.load_staff_from_csv()
            saved_user = my_truck.get_user_details(email)
            if not saved_user:
                logger.error(f"CRITICAL: User {email} was not found in CSV after saving!")
                raise Exception("Failed to save user to database. Please try again.")
            logger.info(f"Verified: User {email} exists in database")
            
            flash("Registration successful! You can now log in.", "success")
            logger.info(f"Registration completed successfully for {email}")
            return redirect(url_for("login", email=email))
        except Exception as e:
            logger.error(f"Error during registration: {e}", exc_info=True)
            flash(f"Registration failed: {str(e)}. Please try again.", "error")

    return render_template("signup.html", title="Register")



@app.route("/login", methods=["GET", "POST"])
def login():
    """User authentication using CSV-based user management"""
    if "user_email" in session:
        return redirect(url_for("welcome"))
    
    error = None
    # Get email from query parameter (if redirected from verification)
    prefill_email = sanitize_text(request.args.get("email", ""))
    
    if request.method == "POST":
        email = sanitize_text(request.form.get("email"))
        password = request.form.get("password") or ""
        
        # Normalize email (lowercase, trimmed)
        email = email.strip().lower() if email else ""
        
        if not email or not password:
            error = "Please provide both email and password."
            logger.warning(f"Login attempt with missing credentials")
        else:
            # Reload user data to ensure we have the latest information
            my_truck.load_staff_from_csv()
            user = my_truck.get_user_details(email)
            
            # Handle both hashed and legacy plaintext passwords.
            authenticated = False
            if not user:
                error = "No account found with this email address. Please check your email or register first."
                logger.warning(f"Login attempt with non-existent email: {email}")
            elif user:
                stored_pw = user.get("password", "").strip()
                
                if not stored_pw:
                    error = "Account error: No password found. Please contact support."
                    logger.error(f"User {email} has empty password field")
                else:
                    # Check if password is hashed (pbkdf2 or scrypt format)
                    if stored_pw.startswith("pbkdf2:") or stored_pw.startswith("scrypt:"):
                        authenticated = check_password_hash(stored_pw, password)
                        if not authenticated:
                            error = "Invalid email or password. Please check your credentials and try again."
                            logger.warning(f"Password mismatch for {email}")
                    elif stored_pw == password:
                        # Legacy plaintext password – treat as valid and upgrade to hashed.
                        authenticated = True
                        logger.info(f"Legacy plaintext password matched for {email}, upgrading to hash")
                        try:
                            new_hashed = generate_password_hash(password, method='pbkdf2:sha256')
                            my_truck.update_user_in_csv(
                                email,
                                {"password": new_hashed},
                            )
                            my_truck.load_staff_from_csv()  # Reload to get updated hash
                        except Exception as exc:
                            logger.error(f"Failed upgrading password hash for {email}: {exc}")
                    else:
                        error = "Invalid email or password. Please check your credentials and try again."
                        logger.warning(f"Password format not recognized for {email}, stored_pw starts with: {stored_pw[:30]}")

        if authenticated:
            session["user_email"] = email
            session["user_name"] = f"{user['first']} {user['last']}"
            session["is_staff"] = user.get("role", "customer") == "staff"
            # Set or clear admin flag based on configured admin emails
            if email.lower() in ADMIN_EMAILS:
                session["admin"] = email
            else:
                session.pop("admin", None)

            logger.info(f"User logged in successfully: {email}")
            flash(f"Welcome back, {user.get('first', 'User')}!", "success")
            return redirect(url_for("welcome"))
        
        # If we get here, authentication failed
        if not error:
            error = "Invalid email or password. Please check your credentials and try again."
        logger.warning(f"Failed login attempt: {email}")

    return render_template("login.html", error=error, prefill_email=prefill_email, title="Login")


@app.route("/logout")
def logout():
    """Session termination"""
    email = session.get("user_email")
    session.pop("user_email", None)
    session.pop("user_name", None)
    session.pop("is_staff", None)
    session.pop("admin", None)  # Also clear admin session if exists
    logger.info(f"User logged out: {email}")
    return redirect(url_for("home"))


@app.route("/welcome")
def welcome():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect
    user = my_truck.get_user_details(session.get("user_email"))
    if not user:
        return redirect(url_for("logout"))
    return render_template(
        "welcome.html",
        user=user,
        is_staff=session.get("is_staff"),
        is_admin=("admin" in session),
        title="Welcome",
    )

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

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    my_truck.add_staff_to_csv(email, hashed_password, first, last, phone, address, dob, sex, role="staff", verified="YES")
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

@app.route("/staff/claim-shift", methods=["POST"])
def claim_shift():
    """Claim a shift (create a new shift)"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    if not user_email:
        flash("You must be logged in to claim a shift.", "error")
        return redirect(url_for("staff_schedule"))
    
    date_str = request.form.get("date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    
    if not all([date_str, start_time, end_time]):
        flash("Please fill in all fields.", "error")
        return redirect(url_for("staff_schedule"))
    
    # Validate date is not in the past
    try:
        shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if shift_date < datetime.now().date():
            flash("Cannot claim shifts in the past.", "error")
            return redirect(url_for("staff_schedule"))
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for("staff_schedule"))
    
    # Check if user already has a shift on this date
    if hasattr(my_truck, 'load_shifts_from_csv'):
        my_truck.load_shifts_from_csv()
        existing_shifts = my_truck.get_staff_shifts(user_email, date_str)
        if existing_shifts:
            flash("You already have a shift on this date.", "error")
            return redirect(url_for("staff_schedule"))
    
    success = my_truck.create_shift(
        staff_email=user_email,
        date=date_str,
        scheduled_start=start_time,
        scheduled_end=end_time,
    )
    
    if success:
        flash(f"Shift claimed for {date_str} from {start_time} to {end_time}!", "success")
    else:
        flash("Error claiming shift. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/staff/time-clock/checkin", methods=["POST"])
def time_clock_checkin():
    """Check in for a shift"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    shift_id = request.form.get("shift_id", "").strip()
    
    if not shift_id:
        flash("Invalid shift ID.", "error")
        return redirect(url_for("staff_schedule"))
    
    my_truck.load_shifts_from_csv()
    shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
    
    if not shift:
        flash("Shift not found.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("staff_email", "").lower() != user_email.lower():
        flash("This is not your shift.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("status") != "scheduled":
        flash("This shift has already been checked in or completed.", "error")
        return redirect(url_for("staff_schedule"))
    
    check_in_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = my_truck.update_shift_status(shift_id, "checked_in", check_in_time=check_in_time)
    
    if success:
        flash("✅ Checked in successfully! You're now on the clock.", "success")
        logger.info(f"Staff {user_email} checked in for shift {shift_id}")
    else:
        flash("Error checking in. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/staff/time-clock/checkout", methods=["POST"])
def time_clock_checkout():
    """Check out (end shift)"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    shift_id = request.form.get("shift_id", "").strip()
    
    if not shift_id:
        flash("Invalid shift ID.", "error")
        return redirect(url_for("staff_schedule"))
    
    my_truck.load_shifts_from_csv()
    shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
    
    if not shift:
        flash("Shift not found.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("staff_email", "").lower() != user_email.lower():
        flash("This is not your shift.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("status") not in ["checked_in", "on_break"]:
        flash("You must be checked in to check out.", "error")
        return redirect(url_for("staff_schedule"))
    
    check_out_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = my_truck.update_shift_status(shift_id, "completed", check_out_time=check_out_time)
    
    if success:
        # Get updated shift to show hours
        my_truck.load_shifts_from_csv()
        updated_shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
        hours = updated_shift.get("total_hours", "0") if updated_shift else "0"
        flash(f"✅ Checked out! Total hours worked: {hours} hours", "success")
        logger.info(f"Staff {user_email} checked out from shift {shift_id} - {hours} hours")
    else:
        flash("Error checking out. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/staff/time-clock/break", methods=["POST"])
def time_clock_break():
    """Start break"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    shift_id = request.form.get("shift_id", "").strip()
    
    if not shift_id:
        flash("Invalid shift ID.", "error")
        return redirect(url_for("staff_schedule"))
    
    my_truck.load_shifts_from_csv()
    shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
    
    if not shift or shift.get("staff_email", "").lower() != user_email.lower():
        flash("Shift not found or not authorized.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("status") != "checked_in":
        flash("You must be checked in to start a break.", "error")
        return redirect(url_for("staff_schedule"))
    
    break_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = my_truck.update_shift_status(shift_id, "on_break", break_start=break_start)
    
    if success:
        flash("🍽️ Break started. Enjoy your break!", "success")
    else:
        flash("Error starting break. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/staff/time-clock/break-end", methods=["POST"])
def time_clock_break_end():
    """End break (return to work)"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    shift_id = request.form.get("shift_id", "").strip()
    
    if not shift_id:
        flash("Invalid shift ID.", "error")
        return redirect(url_for("staff_schedule"))
    
    my_truck.load_shifts_from_csv()
    shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
    
    if not shift or shift.get("staff_email", "").lower() != user_email.lower():
        flash("Shift not found or not authorized.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("status") != "on_break":
        flash("You're not currently on break.", "error")
        return redirect(url_for("staff_schedule"))
    
    break_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = my_truck.update_shift_status(shift_id, "checked_in", break_end=break_end)
    
    if success:
        flash("🔄 Back to work! Break ended.", "success")
    else:
        flash("Error ending break. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/staff/time-clock/checkout-early", methods=["POST"])
def time_clock_checkout_early():
    """Check out early (emergency/going home)"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    shift_id = request.form.get("shift_id", "").strip()
    
    if not shift_id:
        flash("Invalid shift ID.", "error")
        return redirect(url_for("staff_schedule"))
    
    my_truck.load_shifts_from_csv()
    shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
    
    if not shift:
        flash("Shift not found.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("staff_email", "").lower() != user_email.lower():
        flash("This is not your shift.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("status") not in ["checked_in", "on_break"]:
        flash("You must be checked in to check out.", "error")
        return redirect(url_for("staff_schedule"))
    
    check_out_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = my_truck.update_shift_status(shift_id, "completed", check_out_time=check_out_time, early_checkout=True)
    
    if success:
        # Get updated shift to show hours
        my_truck.load_shifts_from_csv()
        updated_shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
        hours = updated_shift.get("total_hours", "0") if updated_shift else "0"
        flash(f"✅ Checked out early! Total hours worked: {hours} hours (marked as early checkout)", "success")
        logger.info(f"Staff {user_email} checked out early from shift {shift_id} - {hours} hours")
    else:
        flash("Error checking out. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/staff/shift/add-note", methods=["POST"])
def add_shift_note():
    """Add or update shift notes"""
    access_redirect = require_staff_access()
    if access_redirect:
        return access_redirect
    
    user_email = session.get("user_email")
    shift_id = request.form.get("shift_id", "").strip()
    notes = request.form.get("notes", "").strip()
    
    if not shift_id:
        flash("Invalid shift ID.", "error")
        return redirect(url_for("staff_schedule"))
    
    my_truck.load_shifts_from_csv()
    shift = next((s for s in my_truck.shifts if s.get("shift_id") == shift_id), None)
    
    if not shift:
        flash("Shift not found.", "error")
        return redirect(url_for("staff_schedule"))
    
    if shift.get("staff_email", "").lower() != user_email.lower():
        flash("This is not your shift.", "error")
        return redirect(url_for("staff_schedule"))
    
    success = my_truck.update_shift_status(shift_id, shift.get("status", "scheduled"), notes=notes)
    
    if success:
        flash("📝 Shift notes saved successfully!", "success")
        logger.info(f"Shift notes updated for shift {shift_id} by {user_email}")
    else:
        flash("Error saving notes. Please try again.", "error")
    
    return redirect(url_for("staff_schedule"))


@app.route("/book_appointment", methods=["POST"])
def book_appointment():
    """POST endpoint for booking work times"""
    expects_json = request.is_json

    access_redirect = require_staff_access()
    if access_redirect:
        if expects_json:
            return jsonify({"error": "Authentication required"}), 401
        return access_redirect

    data = request.get_json(silent=True) or request.form
    manager = sanitize_text(data.get("manager", session.get("user_name", "Manager")))
    date_str = sanitize_text(data.get("date"))
    time_slot = sanitize_text(data.get("time"))
    staff_email = sanitize_text(data.get("staff_email"))
    work_time = sanitize_text(data.get("work_time", f"{time_slot} shift"))

    def _json_or_redirect(payload, status=200):
        if expects_json:
            return jsonify(payload), status
        else:
            if payload.get("error"):
                flash(payload["error"], "error")
            elif payload.get("message"):
                flash(payload["message"], "success")
            # Preserve the selected date in redirect
            if date_str:
                return redirect(url_for("staff_schedule", date=date_str))
            return redirect(url_for("staff_schedule"))

    if not all([date_str, time_slot, staff_email]):
        return _json_or_redirect({"error": "Missing required fields"}, status=400)

    success, message = my_truck.book_helper(manager, date_str, time_slot, staff_email, work_time)

    if success:
        return _json_or_redirect({"success": True, "message": message}, status=200)
    else:
        return _json_or_redirect({"success": False, "error": message}, status=400)

@app.route("/get_available_slots/<staff>/<date>")
def get_available_slots(staff, date):
    """GET endpoint for checking slot availability"""
    try:
        staff_email = sanitize_text(staff)
        date_str = sanitize_text(date)

        if not staff_email or not date_str:
            return jsonify({"error": "Staff email and date are required"}), 400

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
    except Exception as e:
        logger.error(f"Error in get_available_slots: {e}", exc_info=True)
        return jsonify({"error": "Failed to get available slots"}), 500


# ---------- ADMIN DASHBOARD + ORDERS ----------

@app.route("/admin")
def admin_dashboard():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response

    my_truck.load_staff_from_csv()
    my_truck.load_schedules_from_csv()
    my_truck.load_orders_from_csv()

    unsafe_count = sum(1 for o in my_truck.orders if o.get("is_safe", "YES") == "NO")

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
        first = sanitize_text(request.form.get("first", user.get("first", "")))
        last = sanitize_text(request.form.get("last", user.get("last", "")))
        phone = sanitize_text(request.form.get("phone", user.get("phone", "")))
        address = sanitize_text(request.form.get("address", user.get("address", "")))
        dob = sanitize_text(request.form.get("dob", user.get("dob", "")))
        sex = sanitize_text(request.form.get("sex", user.get("sex", "")))

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
    try:
        my_truck.load_schedules_from_csv()
        my_truck.load_staff_from_csv()
        
        appointments = []
        for schedule in my_truck.schedules:
            try:
                staff_email = schedule.get("staff_email", "")
                staff = my_truck.get_user_details(staff_email) if staff_email else None
                appointment = {
                    "manager": schedule.get("manager", ""),
                    "date": schedule.get("date", ""),
                    "time": schedule.get("time", ""),
                    "staff_email": staff_email,
                    "staff_name": schedule.get("staff_name", ""),
                    "work_time": schedule.get("work_time", ""),
                    "staff_details": {
                        "first_name": staff.get("first", "") if staff else None,
                        "last_name": staff.get("last", "") if staff else None,
                        "phone": staff.get("phone", "") if staff else None,
                        "address": staff.get("address", "") if staff else None,
                    } if staff else None
                }
                appointments.append(appointment)
            except (KeyError, TypeError) as e:
                logger.warning(f"Error processing schedule entry: {e}, entry: {schedule}")
                continue
        
        return jsonify({
            "appointments": appointments,
            "total": len(appointments),
            "time_slots": TIME_SLOTS,
            "working_days": WORKING_DAYS
        })
    except Exception as e:
        logger.error(f"Error in api_appointments: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve appointments"}), 500


@app.route("/api/menu")
def api_menu():
    """GET endpoint for retrieving menu items"""
    try:
        menu_items = my_truck.get_menu_items()
        
        # Group by category for easier filtering
        categories = {}
        for item in menu_items:
            cat = item.get("category", "Other")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)
        
        return jsonify({
            "menu_items": menu_items,
            "categories": categories,
            "total": len(menu_items)
        })
    except Exception as e:
        logger.error(f"Error in api_menu: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve menu"}), 500


@app.route("/api/menu/<category>")
def api_menu_category(category):
    """GET endpoint for retrieving menu items by category"""
    try:
        all_items = my_truck.get_menu_items()
        category_items = [
            item for item in all_items 
            if item.get("category", "").lower() == category.lower()
        ]
        
        return jsonify({
            "category": category,
            "menu_items": category_items,
            "total": len(category_items)
        })
    except Exception as e:
        logger.error(f"Error in api_menu_category: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve menu items"}), 500


@app.route("/api/cart", methods=["GET"])
def api_cart_get():
    """GET endpoint for retrieving current cart"""
    try:
        cart = get_cart()
        cart_items = []
        total = 0
        
        for name, item in cart.items():
            try:
                price = float(item.get("price", 0))
                qty = int(item.get("qty", 0))
                subtotal = price * qty
                total += subtotal
                cart_items.append({
                    "name": name,
                    "price": price,
                    "quantity": qty,
                    "subtotal": round(subtotal, 2)
                })
            except (ValueError, TypeError, KeyError):
                continue
        
        return jsonify({
            "cart": cart_items,
            "total": round(total, 2),
            "item_count": sum(int(item.get("qty", 0)) for item in cart.values())
        })
    except Exception as e:
        logger.error(f"Error in api_cart_get: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve cart"}), 500


@app.route("/api/cart", methods=["POST"])
def api_cart_add():
    """POST endpoint for adding item to cart"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "JSON data required"}), 400
        
        item_name = data.get("item_name")
        price = data.get("price")
        
        if not item_name or price is None:
            return jsonify({"error": "item_name and price are required"}), 400
        
        try:
            price_float = float(price)
            if price_float < 0:
                return jsonify({"error": "Invalid price"}), 400
            quantity = int(data.get("qty", 1))
            if quantity < 1:
                quantity = 1
            if quantity > 99:
                quantity = 99
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid price or quantity format"}), 400
        
        cart = get_cart()
        if item_name in cart:
            cart[item_name]["qty"] = cart[item_name].get("qty", 0) + quantity
            if cart[item_name]["qty"] > 99:
                cart[item_name]["qty"] = 99
        else:
            cart[item_name] = {"price": price_float, "qty": quantity}
        
        save_cart(cart)
        
        return jsonify({
            "success": True,
            "message": f"Added {item_name} to cart",
            "cart": cart
        }), 200
    except Exception as e:
        logger.error(f"Error in api_cart_add: {e}", exc_info=True)
        return jsonify({"error": "Failed to add item to cart"}), 500


@app.route("/api/cart", methods=["PUT"])
def api_cart_update():
    """PUT endpoint for updating cart item quantity"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "JSON data required"}), 400
        
        item_name = data.get("item_name")
        if not item_name:
            return jsonify({"error": "item_name is required"}), 400
        
        try:
            quantity = int(data.get("qty", 1))
            if quantity < 1:
                quantity = 1
            if quantity > 99:
                quantity = 99
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid quantity format"}), 400
        
        cart = get_cart()
        if item_name not in cart:
            return jsonify({"error": "Item not found in cart"}), 404
        
        if quantity <= 0:
            # Remove item if quantity is 0 or less
            del cart[item_name]
            save_cart(cart)
            return jsonify({
                "success": True,
                "message": f"Removed {item_name} from cart",
                "cart": cart
            }), 200
        
        cart[item_name]["qty"] = quantity
        save_cart(cart)
        
        return jsonify({
            "success": True,
            "message": f"Updated {item_name} quantity to {quantity}",
            "cart": cart
        }), 200
    except Exception as e:
        logger.error(f"Error in api_cart_update: {e}", exc_info=True)
        return jsonify({"error": "Failed to update cart"}), 500


@app.route("/api/cart", methods=["DELETE"])
def api_cart_delete():
    """DELETE endpoint for removing item from cart"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "JSON data required"}), 400
        
        item_name = data.get("item_name")
        
        if not item_name:
            return jsonify({"error": "item_name is required"}), 400
        
        cart = get_cart()
        if item_name not in cart:
            return jsonify({"error": "Item not found in cart"}), 404
        
        del cart[item_name]
        save_cart(cart)
        
        return jsonify({
            "success": True,
            "message": f"Removed {item_name} from cart",
            "cart": cart
        }), 200
    except Exception as e:
        logger.error(f"Error in api_cart_delete: {e}", exc_info=True)
        return jsonify({"error": "Failed to remove item from cart"}), 500


@app.route("/api/cart/clear", methods=["POST", "DELETE"])
def api_cart_clear():
    """POST/DELETE endpoint for clearing entire cart"""
    save_cart({})
    
    return jsonify({
        "success": True,
        "message": "Cart cleared",
        "cart": {}
    }), 200


if __name__ == "__main__":
    # Get port from environment variable (Render provides this) or default to 5000
    port = int(os.environ.get("PORT", 5000))
    # Run in production mode on Render, debug mode locally
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
