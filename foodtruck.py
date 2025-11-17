import csv
import os
import logging
import shutil
from datetime import datetime, date, timedelta

# Configure logging for the FT management system.
# NOTE: In a larger app this would typically be configured once in the Flask entrypoint.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("ft_management.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Constants
TIME_SLOTS = [
    "09:00",
    "10:00",
    "11:00",
    "12:00",
    "13:00",
    "14:00",
    "15:00",
    "16:00",
    "17:00",
]  # 9 AM to 5 PM

WORKING_DAYS = ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]  # Monday excluded

# Global cache of staff for quick lookups when needed.
STAFF = []


def _sanitize_for_csv(value):
    """
    Basic input sanitization for CSV fields:
    - Convert None to empty string
    - Strip leading/trailing whitespace
    - Remove newlines/carriage returns to avoid breaking CSV rows

    NOTE: We intentionally keep commas because the csv module handles quoting.
    """
    if value is None:
        return ""
    text = str(value).strip()
    return text.replace("\n", " ").replace("\r", " ")


class FoodTruck:
    """
    Backend class for the CS120 Food Truck system.
    Handles staff, schedules, menu, orders and allergy checks using CSV files.
    """

    def __init__(self, name, location):
        self.name = name
        self.location = location
        self.staff = []
        self.schedules = []
        self.orders = []
        self.menu_items = []

    # ---------- MENU DATA ----------

    def load_menu_from_csv(self, path="data/menu.csv"):
        """Load menu items from CSV"""
        self.menu_items = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                # Initialize with default menu if file doesn't exist
                self.initialize_default_menu()
                return
            if not readable:
                logger.error(f"Menu CSV not readable: {path}")
                return

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get("Name"):  # Skip empty rows
                        continue
                    allergens_str = row.get("Allergens", "") or ""
                    allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
                    
                    try:
                        price = float(row.get("Price", 0) or 0)
                    except (ValueError, TypeError):
                        price = 0.0
                    
                    self.menu_items.append({
                        "item_id": row.get("Item_ID", ""),
                        "name": row.get("Name", "").strip(),
                        "description": row.get("Description", "").strip(),
                        "price": price,
                        "category": row.get("Category", "").strip(),
                        "vegan": row.get("Vegan", "False").lower() == "true",
                        "image": row.get("Image", "burger.svg").strip(),
                        "allergens": allergens,
                        "available": row.get("Available", "True").lower() == "true",
                    })
                logger.info(f"Loaded {len(self.menu_items)} menu items from CSV")
        except FileNotFoundError:
            self.initialize_default_menu()
        except Exception as e:
            logger.error(f"Error loading menu: {e}")

    def initialize_default_menu(self, path="data/menu.csv"):
        """Initialize menu CSV with default items"""
        default_items = [
            # Food Items (9 items)
            {"Item_ID": "1", "Name": "Original Chicken Sandwich Combo", "Description": "Crispy chicken sandwich, fries & drink.", "Price": "7.99", "Category": "Food", "Vegan": "False", "Image": "burger.svg", "Allergens": "gluten,wheat,egg", "Available": "True"},
            {"Item_ID": "2", "Name": "Wings & Wedges Box", "Description": "Spicy wings with seasoned potato wedges.", "Price": "9.49", "Category": "Food", "Vegan": "False", "Image": "wings.svg", "Allergens": "gluten,wheat", "Available": "True"},
            {"Item_ID": "3", "Name": "Family Bucket", "Description": "12 pc chicken, large fries & slaw.", "Price": "19.99", "Category": "Food", "Vegan": "False", "Image": "bucket.svg", "Allergens": "gluten,wheat", "Available": "True"},
            {"Item_ID": "4", "Name": "BBQ Chicken Wrap", "Description": "Grilled chicken, BBQ sauce, lettuce, and cheese in a warm tortilla.", "Price": "8.49", "Category": "Food", "Vegan": "False", "Image": "burger.svg", "Allergens": "gluten,dairy", "Available": "True"},
            {"Item_ID": "5", "Name": "Chicken Quesadilla", "Description": "Grilled chicken, cheese, and peppers in a crispy tortilla.", "Price": "9.99", "Category": "Food", "Vegan": "False", "Image": "veggie.svg", "Allergens": "gluten,dairy", "Available": "True"},
            {"Item_ID": "6", "Name": "Veggie Bowl", "Description": "Rice bowl with crispy veggies and sauce.", "Price": "8.49", "Category": "Food", "Vegan": "True", "Image": "veggie.svg", "Allergens": "soy", "Available": "True"},
            {"Item_ID": "7", "Name": "Smoky Tofu Wrap", "Description": "Grilled tofu, crisp veggies, spicy mayo in a warm wrap.", "Price": "9.25", "Category": "Food", "Vegan": "True", "Image": "veggie.svg", "Allergens": "soy,gluten", "Available": "True"},
            {"Item_ID": "8", "Name": "Garden Salad", "Description": "Mixed greens, tomatoes, cucumbers, carrots, and your choice of dressing.", "Price": "5.99", "Category": "Food", "Vegan": "True", "Image": "veggie.svg", "Allergens": "", "Available": "True"},
            {"Item_ID": "9", "Name": "Veggie Burger", "Description": "Plant-based patty with lettuce, tomato, onion, and special sauce.", "Price": "7.99", "Category": "Food", "Vegan": "True", "Image": "burger.svg", "Allergens": "gluten,soy", "Available": "True"},
            
            # Drinks (4 items)
            {"Item_ID": "10", "Name": "Coca-Cola", "Description": "Classic Coca-Cola soft drink.", "Price": "2.49", "Category": "Drinks", "Vegan": "True", "Image": "drink.svg", "Allergens": "", "Available": "True"},
            {"Item_ID": "11", "Name": "Orange Juice", "Description": "Fresh squeezed orange juice.", "Price": "3.49", "Category": "Drinks", "Vegan": "True", "Image": "drink.svg", "Allergens": "", "Available": "True"},
            {"Item_ID": "12", "Name": "Iced Tea", "Description": "Refreshing iced tea, sweetened or unsweetened.", "Price": "2.99", "Category": "Drinks", "Vegan": "True", "Image": "drink.svg", "Allergens": "", "Available": "True"},
            {"Item_ID": "13", "Name": "Chocolate Milkshake", "Description": "Creamy chocolate milkshake topped with whipped cream.", "Price": "4.99", "Category": "Drinks", "Vegan": "False", "Image": "drink.svg", "Allergens": "dairy", "Available": "True"},
            
            # Desserts (2 items)
            {"Item_ID": "14", "Name": "Chocolate Chip Cookies", "Description": "Freshly baked chocolate chip cookies (3pc).", "Price": "3.99", "Category": "Dessert", "Vegan": "False", "Image": "dessert.svg", "Allergens": "gluten,dairy,egg", "Available": "True"},
            {"Item_ID": "15", "Name": "Apple Pie Slice", "Description": "Warm apple pie slice with vanilla ice cream.", "Price": "5.99", "Category": "Dessert", "Vegan": "False", "Image": "dessert.svg", "Allergens": "gluten,dairy", "Available": "True"},
        ]
        
        exists, readable, writable = self.check_file_permissions(path)
        if not exists:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["Item_ID", "Name", "Description", "Price", "Category", "Vegan", "Image", "Allergens", "Available"])
                    writer.writeheader()
                    writer.writerows(default_items)
                logger.info(f"Initialized default menu: {path}")
            except Exception as e:
                logger.error(f"Error initializing default menu: {e}")
        elif exists and readable:
            # If file exists but is empty or has no items, reinitialize
            try:
                with open(path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    if len(rows) == 0 and writable:
                        # File exists but is empty, reinitialize
                        with open(path, "w", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=["Item_ID", "Name", "Description", "Price", "Category", "Vegan", "Image", "Allergens", "Available"])
                            writer.writeheader()
                            writer.writerows(default_items)
                        logger.info(f"Reinitialized empty menu: {path}")
            except Exception as e:
                logger.error(f"Error checking menu file: {e}")

    def get_menu_items(self):
        """Returns list of available menu items"""
        # Always reload to ensure fresh data
        self.load_menu_from_csv()
        # Return all items, filtering by availability
        available_items = [item for item in self.menu_items if item.get("available", True)]
        # If no items available, try to initialize default menu
        if not available_items:
            logger.warning("No menu items found, initializing default menu")
            self.initialize_default_menu()
            self.load_menu_from_csv()
            available_items = [item for item in self.menu_items if item.get("available", True)]
        logger.info(f"Returning {len(available_items)} menu items")
        return available_items

    def get_menu_allergens(self):
        """Build a mapping from item name -> list of allergens"""
        allergens_map = {}
        for item in self.get_menu_items():
            allergens_map[item["name"]] = item.get("allergens", [])
        return allergens_map

    def save_menu_item(self, item_id, name, description, price, category, vegan, image, allergens, available, path="data/menu.csv"):
        """Save or update a menu item"""
        exists, readable, writable = self.check_file_permissions(path)
        if not exists:
            self.initialize_csv_files()
        if not readable or not writable:
            logger.error(f"Cannot save menu item: {path}")
            return False

        rows = []
        updated = False
        allergens_str = ",".join(allergens) if isinstance(allergens, list) else str(allergens)
        
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                if row.get("Item_ID") == str(item_id):
                    row["Name"] = name
                    row["Description"] = description
                    row["Price"] = str(price)
                    row["Category"] = category
                    row["Vegan"] = "True" if vegan else "False"
                    row["Image"] = image
                    row["Allergens"] = allergens_str
                    row["Available"] = "True" if available else "False"
                    updated = True
                rows.append(row)

        if not updated:
            # Add new item
            new_id = str(max([int(r.get("Item_ID", 0) or 0) for r in rows] + [0]) + 1) if rows else "1"
            rows.append({
                "Item_ID": new_id,
                "Name": name,
                "Description": description,
                "Price": str(price),
                "Category": category,
                "Vegan": "True" if vegan else "False",
                "Image": image,
                "Allergens": allergens_str,
                "Available": "True" if available else "False",
            })

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        self.load_menu_from_csv()
        return True

    def delete_menu_item(self, item_id, path="data/menu.csv"):
        """Delete a menu item"""
        exists, readable, writable = self.check_file_permissions(path)
        if not exists or not readable or not writable:
            return False

        rows = []
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                if row.get("Item_ID") != str(item_id):
                    rows.append(row)

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        self.load_menu_from_csv()
        return True

    def is_order_safe_for_allergy(self, items_text, allergy_text):
        """
        Check if an order (possibly multiple items) is safe based on allergy text.
        items_text can be a single item name or a combined string like
        'Original Chicken Sandwich Combo x2, Wings & Wedges Box x1'.
        Returns True if safe, False if any allergen matches.
        """
        allergy_text = allergy_text.lower().strip()
        if allergy_text == "":
            return True  # no allergy reported

        menu_allergens = self.get_menu_allergens()
        items_text_lower = items_text.lower()

        combined_allergens = set()
        for item_name, allergens in menu_allergens.items():
            if item_name.lower() in items_text_lower:
                combined_allergens.update(allergens)

        if not combined_allergens and items_text in menu_allergens:
            combined_allergens.update(menu_allergens[items_text])

        for allergen in combined_allergens:
            if allergen in allergy_text:
                return False

        return True

    # ---------- STAFF (CSV) ----------

    def _ensure_role_column(self, path="data/users.csv"):
        exists, readable, writable = self.check_file_permissions(path)
        if not exists or not readable or not writable:
            return

        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                if "Role" in fieldnames:
                    return
                rows = list(reader)
        except FileNotFoundError:
            return

        new_fieldnames = fieldnames + ["Role"]
        for row in rows:
            row["Role"] = row.get("Role", "staff")

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=new_fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _ensure_user_columns(self, path="data/users.csv"):
        """Ensure the CSV has required columns (Role, Verified). Only runs if columns are missing.
        This function is SAFE - it preserves all existing data."""
        exists, readable, writable = self.check_file_permissions(path)
        if not exists:
            # File doesn't exist yet, will be created with correct headers by initialize_csv_files
            return
        if not readable or not writable:
            logger.warning(f"Cannot check/update columns for {path}: permissions issue")
            return

        # Read all data first
        rows = []
        fieldnames = []
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                required = ["Role", "Verified"]
                missing = [col for col in required if col not in fieldnames]
                
                if not missing:
                    # All required columns exist, no need to update
                    return
                
                # Read all existing rows - CRITICAL: preserve all data
                rows = list(reader)
                logger.info(f"Adding missing columns to {path}: {missing}. Preserving {len(rows)} existing rows.")
                
                if len(rows) == 0:
                    # Empty file except header - just update header
                    logger.info("File is empty, just updating header")
                    with open(path, "w", newline="", encoding="utf-8") as f:
                        new_fieldnames = fieldnames + missing
                        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
                        writer.writeheader()
                    logger.info(f"Updated header with missing columns: {missing}")
                    return
                
        except FileNotFoundError:
            return
        except Exception as e:
            logger.error(f"Error reading CSV to check columns: {e}")
            return

        # Only update if we have missing columns AND existing data
        new_fieldnames = fieldnames + missing
        for row in rows:
            if "Role" in missing:
                row["Role"] = row.get("Role", "customer")
            if "Verified" in missing:
                row["Verified"] = row.get("Verified", "NO")

        # Write back with new columns - PRESERVE ALL DATA
        try:
            # Use a temporary file approach to be extra safe
            temp_path = path + ".tmp"
            with open(temp_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=new_fieldnames)
                writer.writeheader()
                for row in rows:
                    row.setdefault("Role", "customer")
                    row.setdefault("Verified", "NO")
                    writer.writerow(row)
            
            # Only replace original if temp file was written successfully
            shutil.move(temp_path, path)
            logger.info(f"Successfully updated CSV columns in {path}. Preserved {len(rows)} rows.")
        except Exception as e:
            logger.error(f"Failed to update CSV columns: {e}")
            # Try to restore if temp file exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise

    def load_staff_from_csv(self, path="data/users.csv"):
        self.staff = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                return
            if not readable:
                logger.error(f"Users CSV not readable: {path}")
                return

            self._ensure_user_columns(path)

            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.staff.append(
                        {
                            "email": row["Email"],
                            "password": row["Password"],
                            "first": row["First_Name"],
                            "last": row["Last_Name"],
                            "phone": row["Mobile_Number"],
                            "address": row["Address"],
                            "dob": row["DOB"],
                            "sex": row["Sex"],
                            "role": row.get("Role", "customer"),
                            "verified": row.get("Verified", "NO"),
                        }
                    )
        except FileNotFoundError:
            logger.warning(f"Users CSV not found at {path}")

        # Keep STAFF constant in sync with the current staff list
        global STAFF
        STAFF = list(self.staff)

    def add_staff_to_csv(
        self,
        email,
        password,
        first,
        last,
        phone,
        address,
        dob,
        sex,
        role="staff",
        verified="NO",
        path="data/users.csv",
    ):
        exists, _, writable = self.check_file_permissions(path)
        if not exists:
            # If file is missing here, try to create it with just a header row.
            logger.warning(f"Users CSV missing when adding staff, attempting re-init: {path}")
            self.initialize_csv_files()
        elif not writable:
            logger.error(f"Users CSV not writable: {path}")
            raise PermissionError(f"Users CSV not writable: {path}")

        # Ensure columns exist BEFORE adding user (but don't clear data)
        # Only check, don't modify if columns already exist
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                if "Role" not in fieldnames or "Verified" not in fieldnames:
                    # Only update if columns are missing
                    self._ensure_user_columns(path)
        except FileNotFoundError:
            # File doesn't exist, will be created
            pass
        except Exception as e:
            logger.warning(f"Error checking columns before adding user: {e}")

        # Normalize email to lowercase for consistency
        email = email.strip().lower() if email else ""
        
        logger.info(f"Adding user to CSV: {email}")
        
        try:
            # Use append mode to add new user
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                row_data = [
                    email,  # Store email in lowercase
                    password,  # Don't sanitize password hash - it contains special chars that need to be preserved
                    _sanitize_for_csv(first),
                    _sanitize_for_csv(last),
                    _sanitize_for_csv(phone),
                    _sanitize_for_csv(address),
                    _sanitize_for_csv(dob),
                    _sanitize_for_csv(sex),
                    _sanitize_for_csv(role),
                    _sanitize_for_csv(verified),
                ]
                writer.writerow(row_data)
                f.flush()  # Force write to disk
                os.fsync(f.fileno())  # Ensure data is written
                logger.info(f"User data written to CSV: {email}")
        except Exception as e:
            logger.error(f"Failed to write user to CSV: {e}")
            raise

        # Add to in-memory list
        self.staff.append(
            {
                "email": email,  # Store email in lowercase (already normalized above)
                "password": password,  # Keep password hash as-is, don't sanitize
                "first": _sanitize_for_csv(first),
                "last": _sanitize_for_csv(last),
                "phone": _sanitize_for_csv(phone),
                "address": _sanitize_for_csv(address),
                "dob": _sanitize_for_csv(dob),
                "sex": _sanitize_for_csv(sex),
                "role": _sanitize_for_csv(role),
                "verified": _sanitize_for_csv(verified),
            }
        )
        global STAFF
        STAFF = list(self.staff)
        logger.info(f"User added to in-memory list: {email}")

    # ---------- SCHEDULES (CSV) ----------

    def load_schedules_from_csv(self, path="data/schedules.csv"):
        self.schedules = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                return
            if not readable:
                logger.error(f"Schedules CSV not readable: {path}")
                return

            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.schedules.append(
                        {
                            "manager": row["Manager"],
                            "date": row["Date"],
                            "time": row["Time"],
                            "staff_email": row["staff_Email"],
                            "staff_name": row["staff_Name"],
                            "work_time": row["work_Time"],
                        }
                    )
        except FileNotFoundError:
            pass

    def book_schedule(
        self,
        manager,
        date,
        time,
        staff_email,
        staff_name,
        work_time,
        path="data/schedules.csv",
    ):
        # prevent double booking
        for s in self.schedules:
            if s["staff_email"] == staff_email and s["date"] == date and s["time"] == time:
                return False  # already booked

        exists, _, writable = self.check_file_permissions(path)
        if not exists:
            logger.warning(f"Schedules CSV missing when booking, attempting re-init: {path}")
            self.initialize_csv_files()
        elif not writable:
            logger.error(f"Schedules CSV not writable: {path}")
            raise PermissionError(f"Schedules CSV not writable: {path}")

        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    _sanitize_for_csv(manager),
                    _sanitize_for_csv(date),
                    _sanitize_for_csv(time),
                    _sanitize_for_csv(staff_email),
                    _sanitize_for_csv(staff_name),
                    _sanitize_for_csv(work_time),
                ]
            )

        self.schedules.append(
            {
                "manager": _sanitize_for_csv(manager),
                "date": _sanitize_for_csv(date),
                "time": _sanitize_for_csv(time),
                "staff_email": _sanitize_for_csv(staff_email),
                "staff_name": _sanitize_for_csv(staff_name),
                "work_time": _sanitize_for_csv(work_time),
            }
        )
        return True

    # ---------- ORDERS (CSV) ----------

    def load_orders_from_csv(self, path="data/orders.csv"):
        self.orders = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                return
            if not readable:
                logger.error(f"Orders CSV not readable: {path}")
                return

            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Handle legacy orders without new fields
                    subtotal = row.get("Subtotal", row.get("Price", "0.00"))
                    delivery_fee = row.get("Delivery_Fee", "0.00")
                    tip_amount = row.get("Tip_Amount", "0.00")
                    total_price = row.get("Total_Price", str(float(subtotal) + float(delivery_fee) + float(tip_amount)))
                    
                    self.orders.append(
                        {
                            "order_id": row["Order_ID"],
                            "customer_name": row["Customer_Name"],
                            "customer_email": row["Customer_Email"],
                            "customer_phone": row.get("Customer_Phone", ""),
                            "order_type": row.get("Order_Type", "delivery"),
                            "delivery_address": row.get("Delivery_Address", ""),
                            "address_lat": row.get("Address_Lat", ""),
                            "address_lng": row.get("Address_Lng", ""),
                            "delivery_instructions": row.get("Delivery_Instructions", ""),
                            "pickup_instructions": row.get("Pickup_Instructions", ""),
                            "item": row["Item"],
                            "allergy_info": row["Allergy_Info"],
                            "is_safe": row["Is_Safe"],
                            "timestamp": row["Timestamp"],
                            "status": row.get("Status", "Pending"),
                            "completed_by": row.get("Completed_By", ""),
                            "subtotal": subtotal,
                            "delivery_fee": delivery_fee,
                            "tip_amount": tip_amount,
                            "price": total_price,
                            "payment_method": row.get("Payment_Method", "card"),
                            "masked_card": row.get("Masked_Card", ""),
                            "card_expiry": row.get("Card_Expiry", ""),
                        }
                    )
        except FileNotFoundError:
            pass

    def calculate_order_price(self, items_text):
        """Calculate total price from items text (e.g., 'Item x2, Item2 x1')"""
        menu_items = {item["name"]: item["price"] for item in self.get_menu_items()}
        total = 0.0
        
        # Parse items like "Item x2, Item2 x1" or "Item, Item2"
        items_list = [item.strip() for item in items_text.split(",")]
        for item_str in items_list:
            item_str = item_str.strip()
            if " x" in item_str:
                parts = item_str.rsplit(" x", 1)
                item_name = parts[0].strip()
                try:
                    quantity = int(parts[1].strip())
                except (ValueError, IndexError):
                    quantity = 1
            else:
                item_name = item_str
                quantity = 1
            
            if item_name in menu_items:
                total += menu_items[item_name] * quantity
        
        return round(total, 2)

    def add_order_to_csv(
        self,
        customer_name,
        customer_email,
        items_text,
        allergy_info,
        customer_phone="",
        order_type="delivery",
        delivery_address="",
        address_lat="",
        address_lng="",
        delivery_instructions="",
        pickup_instructions="",
        tip_amount=0.00,
        delivery_fee=0.00,
        payment_method="card",
        masked_card="",
        card_expiry="",
        path="data/orders.csv",
    ):
        is_safe = self.is_order_safe_for_allergy(items_text, allergy_info)
        is_safe_str = "YES" if is_safe else "NO"

        order_id = len(self.orders) + 1
        timestamp = datetime.now().isoformat(timespec="seconds")
        subtotal = self.calculate_order_price(items_text)
        total_price = subtotal + delivery_fee + tip_amount

        exists, _, writable = self.check_file_permissions(path)
        if not exists:
            logger.warning(f"Orders CSV missing when adding order, attempting re-init: {path}")
            self.initialize_csv_files()
        elif not writable:
            logger.error(f"Orders CSV not writable: {path}")
            raise PermissionError(f"Orders CSV not writable: {path}")

        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    order_id,
                    _sanitize_for_csv(customer_name),
                    _sanitize_for_csv(customer_email),
                    _sanitize_for_csv(customer_phone),
                    _sanitize_for_csv(order_type),
                    _sanitize_for_csv(delivery_address),
                    _sanitize_for_csv(address_lat),
                    _sanitize_for_csv(address_lng),
                    _sanitize_for_csv(delivery_instructions),
                    _sanitize_for_csv(pickup_instructions),
                    _sanitize_for_csv(items_text),
                    _sanitize_for_csv(allergy_info),
                    is_safe_str,
                    _sanitize_for_csv(timestamp),
                    "Pending",
                    "",
                    str(subtotal),
                    str(delivery_fee),
                    str(tip_amount),
                    str(total_price),
                    _sanitize_for_csv(payment_method),
                    _sanitize_for_csv(masked_card),
                    _sanitize_for_csv(card_expiry),
                ]
            )

        self.orders.append(
            {
                "order_id": order_id,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
                "order_type": order_type,
                "delivery_address": delivery_address,
                "address_lat": address_lat,
                "address_lng": address_lng,
                "delivery_instructions": delivery_instructions,
                "pickup_instructions": pickup_instructions,
                "item": items_text,
                "allergy_info": allergy_info,
                "is_safe": is_safe_str,
                "timestamp": timestamp,
                "status": "Pending",
                "completed_by": "",
                "subtotal": str(subtotal),
                "delivery_fee": str(delivery_fee),
                "tip_amount": str(tip_amount),
                "price": str(total_price),
                "payment_method": payment_method,
                "masked_card": masked_card,
                "card_expiry": card_expiry,
            }
        )

        return is_safe

    def migrate_orders_csv(self, path="data/orders.csv"):
        """Migrate existing orders CSV to include new fields (Status, Completed_By, Price)"""
        exists, readable, writable = self.check_file_permissions(path)
        if not exists or not readable:
            return
        
        try:
            rows = []
            fieldnames = []
            needs_migration = False
            
            with open(path, "r", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                
                # Check if migration is needed
                if "Status" not in fieldnames or "Completed_By" not in fieldnames or "Price" not in fieldnames:
                    needs_migration = True
                    fieldnames.extend([col for col in ["Status", "Completed_By", "Price"] if col not in fieldnames])
                
                for row in reader:
                    if needs_migration:
                        if "Status" not in row:
                            row["Status"] = "Pending"
                        if "Completed_By" not in row:
                            row["Completed_By"] = ""
                        if "Price" not in row:
                            # Calculate price for existing orders
                            row["Price"] = str(self.calculate_order_price(row.get("Item", "")))
                    rows.append(row)
            
            if needs_migration and writable:
                with open(path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                logger.info(f"Migrated orders CSV: added Status, Completed_By, Price columns")
                self.load_orders_from_csv()
        except Exception as e:
            logger.error(f"Error migrating orders CSV: {e}")

    def update_order_status(self, order_id, status, completed_by="", path="data/orders.csv"):
        """Update order status and completed_by in CSV"""
        exists, readable, writable = self.check_file_permissions(path)
        if not exists or not readable or not writable:
            logger.error(f"Cannot update order status: {path}")
            return False

        rows = []
        updated = False
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            
            # Ensure new fields exist
            if "Status" not in fieldnames:
                fieldnames.append("Status")
            if "Completed_By" not in fieldnames:
                fieldnames.append("Completed_By")
            if "Price" not in fieldnames:
                fieldnames.append("Price")
            
            for row in reader:
                if row["Order_ID"] == str(order_id):
                    row["Status"] = status
                    row["Completed_By"] = completed_by
                    if "Price" not in row:
                        row["Price"] = str(self.calculate_order_price(row.get("Item", "")))
                    updated = True
                # Ensure all rows have the new fields
                row.setdefault("Status", "Pending")
                row.setdefault("Completed_By", "")
                row.setdefault("Price", str(self.calculate_order_price(row.get("Item", ""))))
                rows.append(row)

        if updated:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self.load_orders_from_csv()
            return True
        return False

    # ---------- HELPER FUNCTIONS ----------

    def check_file_permissions(self, file_path):
        """
        Validates file access and permissions.
        Returns (exists, readable, writable) tuple.
        """
        exists = os.path.exists(file_path)
        readable = os.access(file_path, os.R_OK) if exists else False
        writable = os.access(file_path, os.W_OK) if exists else False
        return exists, readable, writable

    def initialize_csv_files(self):
        """
        Sets up CSV files with headers if they don't exist.
        """
        files_config = {
            "data/users.csv": ["Email", "Password", "First_Name", "Last_Name", "Mobile_Number", "Address", "DOB", "Sex", "Role", "Verified"],
            "data/schedules.csv": ["Manager", "Date", "Time", "staff_Email", "staff_Name", "work_Time"],
            "data/orders.csv": ["Order_ID", "Customer_Name", "Customer_Email", "Customer_Phone", "Order_Type", "Delivery_Address", "Address_Lat", "Address_Lng", "Delivery_Instructions", "Pickup_Instructions", "Item", "Allergy_Info", "Is_Safe", "Timestamp", "Status", "Completed_By", "Subtotal", "Delivery_Fee", "Tip_Amount", "Total_Price", "Payment_Method", "Masked_Card", "Card_Expiry"],
            "data/menu.csv": ["Item_ID", "Name", "Description", "Price", "Category", "Vegan", "Image", "Allergens", "Available"],
        }

        for file_path, headers in files_config.items():
            exists, readable, writable = self.check_file_permissions(file_path)
            
            if not exists:
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                try:
                    with open(file_path, 'w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(headers)
                    logger.info(f"Initialized CSV file: {file_path}")
                except Exception as e:
                    logger.error(f"Error initializing {file_path}: {e}")
            elif not readable or not writable:
                logger.warning(f"File {file_path} exists but has permission issues")

    def get_user_details(self, email):
        """
        Retrieves user information by email (case-insensitive).
        Returns user dict or None if not found.
        """
        if not email:
            return None
        email = email.strip().lower()
        self.load_staff_from_csv()
        for user in self.staff:
            if user["email"].strip().lower() == email:
                return user
        return None
    
    def user_exists(self, email):
        """
        Check if a user with this email already exists (case-insensitive).
        Returns True if user exists, False otherwise.
        """
        return self.get_user_details(email) is not None

    def is_time_slot_available(self, staff_email, date_str, time_slot):
        """
        Checks appointment slot availability for a specific staff member.
        Returns True if available, False if booked or invalid (e.g., Monday).
        """
        # Validate working day here to enforce business rule at the lowest level
        try:
            booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            day_name = booking_date.strftime("%A")
            if day_name not in WORKING_DAYS:
                return False
        except ValueError:
            # Invalid date format is treated as not available
            return False

        self.load_schedules_from_csv()
        for schedule in self.schedules:
            if (schedule["staff_email"] == staff_email and 
                schedule["date"] == date_str and 
                schedule["time"] == time_slot):
                return False
        return True

    def get_available_slots(self, staff_email, date_str):
        """
        Returns list of available time slots for a staff member on a given date.
        """
        # Do not return slots for Monday or invalid dates
        try:
            booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            day_name = booking_date.strftime("%A")
            if day_name not in WORKING_DAYS:
                return []
        except ValueError:
            return []

        available = []
        for slot in TIME_SLOTS:
            if self.is_time_slot_available(staff_email, date_str, slot):
                available.append(slot)
        return available

    def book_helper(self, manager, date_str, time_slot, staff_email, work_time):
        """
        Handles staff booking logic with validation.
        Returns (success, message) tuple.
        """
        # Validate date is a working day
        try:
            booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            day_name = booking_date.strftime("%A")
            if day_name not in WORKING_DAYS:
                return False, f"{day_name} is not a working day. Working days: {', '.join(WORKING_DAYS)}"
        except ValueError:
            return False, "Invalid date format. Use YYYY-MM-DD"

        # Validate time slot
        if time_slot not in TIME_SLOTS:
            return False, f"Invalid time slot. Available slots: {', '.join(TIME_SLOTS)}"

        # Check if staff exists
        staff = self.get_user_details(staff_email)
        if not staff:
            return False, "Staff member not found"

        staff_name = f"{staff['first']} {staff['last']}"

        # Check availability
        if not self.is_time_slot_available(staff_email, date_str, time_slot):
            return False, "Time slot is already booked for this staff member"

        # Book the schedule
        success = self.book_schedule(
            manager=manager,
            date=date_str,
            time=time_slot,
            staff_email=staff_email,
            staff_name=staff_name,
            work_time=work_time
        )

        if success:
            logger.info(f"Successfully booked schedule: {staff_name} on {date_str} at {time_slot}")
            return True, "Schedule booked successfully"
        else:
            return False, "Failed to book schedule"

    def update_user_in_csv(self, email, updated_fields, path="data/users.csv"):
        """
        Update an existing user row in the users CSV.

        `updated_fields` uses internal keys: first, last, phone, address, dob, sex, password (optional).
        Returns True on success, False if the user was not found or file issues occurred.
        """
        exists, readable, writable = self.check_file_permissions(path)
        if not exists or not readable or not writable:
            logger.error(f"Cannot update user CSV due to permissions or missing file: {path}")
            return False

        field_map = {
            "password": "Password",
            "first": "First_Name",
            "last": "Last_Name",
            "phone": "Mobile_Number",
            "address": "Address",
            "dob": "DOB",
            "sex": "Sex",
            "role": "Role",
        }

        rows = []
        user_found = False

        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Email") == email:
                        user_found = True
                        for key, value in updated_fields.items():
                            if key in field_map and value is not None:
                                row[field_map[key]] = _sanitize_for_csv(value)
                    rows.append(row)
        except Exception as exc:
            logger.error(f"Error reading users CSV during update: {exc}")
            return False

        if not user_found:
            logger.warning(f"Attempted to update non-existent user: {email}")
            return False

        try:
            with open(path, "w", newline="") as f:
                fieldnames = ["Email", "Password", "First_Name", "Last_Name", "Mobile_Number", "Address", "DOB", "Sex", "Role"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    if "Role" not in row:
                        row["Role"] = "staff"
                    writer.writerow(row)
        except Exception as exc:
            logger.error(f"Error writing users CSV during update: {exc}")
            return False

        # Refresh in-memory staff cache
        self.load_staff_from_csv()
        return True
