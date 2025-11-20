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
        self.deals = []
        self.shifts = []
        self.menu_items = []

    # ---------- MENU DATA ----------

    def load_menu_from_csv(self, path="data/menu.csv"):
        """Load menu items from CSV"""
        self.menu_items = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                # If menu.csv doesn't exist, migrate from hardcoded items
                self._migrate_menu_to_csv()
                return
            if not readable:
                logger.error(f"Menu CSV not readable: {path}")
                return

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    allergens_str = row.get("Allergens", "").strip()
                    allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
                    
                    self.menu_items.append({
                        "item_id": row.get("Item_ID", ""),
                        "name": row.get("Name", ""),
                        "description": row.get("Description", ""),
                        "price": float(row.get("Price", "0")),
                        "category": row.get("Category", "Other"),
                        "vegan": row.get("Vegan", "False").upper() == "TRUE",
                        "image": row.get("Image", "burger.svg"),
                        "allergens": allergens,
                    })
        except FileNotFoundError:
            self._migrate_menu_to_csv()
        except Exception as e:
            logger.error(f"Error loading menu from CSV: {e}", exc_info=True)
            # Fallback to hardcoded items
            self.menu_items = self._get_hardcoded_menu_items()

    def _migrate_menu_to_csv(self, path="data/menu.csv"):
        """Migrate hardcoded menu items to CSV"""
        try:
            hardcoded_items = self._get_hardcoded_menu_items()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["Item_ID", "Name", "Description", "Price", "Category", "Vegan", "Image", "Allergens"])
                writer.writeheader()
                
                for idx, item in enumerate(hardcoded_items, 1):
                    item_id = f"MENU_{idx:03d}"
                    writer.writerow({
                        "Item_ID": item_id,
                        "Name": _sanitize_for_csv(item["name"]),
                        "Description": _sanitize_for_csv(item["description"]),
                        "Price": str(item["price"]),
                        "Category": item["category"],
                        "Vegan": "TRUE" if item["vegan"] else "FALSE",
                        "Image": item["image"],
                        "Allergens": ",".join(item["allergens"]),
                    })
            
            logger.info(f"Migrated {len(hardcoded_items)} menu items to {path}")
            self.load_menu_from_csv(path)
        except Exception as e:
            logger.error(f"Error migrating menu to CSV: {e}", exc_info=True)
            self.menu_items = self._get_hardcoded_menu_items()

    def _get_hardcoded_menu_items(self):
        """Returns the original hardcoded menu items"""
        return [
            # Combo Meals
            {
                "name": "Original Chicken Sandwich Combo",
                "description": "Crispy chicken sandwich, fries & drink.",
                "price": 7.99,
                "category": "Combo",
                "vegan": False,
                "image": "burger.svg",
                "allergens": ["gluten", "wheat", "egg"],
            },
            {
                "name": "Classic Burger Combo",
                "description": "Juicy beef patty, lettuce, tomato, pickles, fries & drink.",
                "price": 8.99,
                "category": "Combo",
                "vegan": False,
                "image": "burger.svg",
                "allergens": ["gluten", "wheat", "egg", "dairy"],
            },
            {
                "name": "BBQ Pulled Pork Combo",
                "description": "Slow-cooked pulled pork, coleslaw, fries & drink.",
                "price": 9.99,
                "category": "Combo",
                "vegan": False,
                "image": "burger.svg",
                "allergens": ["gluten", "wheat"],
            },
            {
                "name": "Double Cheeseburger Combo",
                "description": "Two beef patties, double cheese, special sauce, fries & drink.",
                "price": 10.99,
                "category": "Combo",
                "vegan": False,
                "image": "burger.svg",
                "allergens": ["gluten", "wheat", "egg", "dairy"],
            },
            # Main Dishes
            {
                "name": "Wings & Wedges Box",
                "description": "Spicy wings with seasoned potato wedges.",
                "price": 9.49,
                "category": "Main",
                "vegan": False,
                "image": "wings.svg",
                "allergens": ["gluten", "wheat"],
            },
            {
                "name": "Family Bucket",
                "description": "12 pc chicken, large fries & slaw.",
                "price": 19.99,
                "category": "Main",
                "vegan": False,
                "image": "bucket.svg",
                "allergens": ["gluten", "wheat"],
            },
            {
                "name": "Fish Tacos (3pc)",
                "description": "Beer-battered fish, cabbage slaw, lime crema, corn tortillas.",
                "price": 11.99,
                "category": "Main",
                "vegan": False,
                "image": "taco.svg",
                "allergens": ["gluten", "wheat", "fish", "dairy"],
            },
            {
                "name": "Loaded Nachos",
                "description": "Tortilla chips, cheese, jalapeños, sour cream, guacamole.",
                "price": 8.99,
                "category": "Main",
                "vegan": False,
                "image": "nachos.svg",
                "allergens": ["gluten", "wheat", "dairy"],
            },
            # Vegetarian/Vegan Options
            {
                "name": "Veggie Bowl",
                "description": "Rice bowl with crispy veggies and sauce.",
                "price": 8.49,
                "category": "Veg",
                "vegan": True,
                "image": "veggie.svg",
                "allergens": ["soy"],
            },
            {
                "name": "Smoky Tofu Wrap",
                "description": "Grilled tofu, crisp veggies, spicy mayo in a warm wrap.",
                "price": 9.25,
                "category": "Veg",
                "vegan": True,
                "image": "veggie.svg",
                "allergens": ["soy", "gluten"],
            },
            {
                "name": "Black Bean Burger",
                "description": "House-made black bean patty, avocado, chipotle mayo.",
                "price": 7.99,
                "category": "Veg",
                "vegan": True,
                "image": "veggie.svg",
                "allergens": ["gluten", "wheat", "soy"],
            },
            # Sides
            {
                "name": "French Fries",
                "description": "Crispy golden fries with seasoning.",
                "price": 3.99,
                "category": "Side",
                "vegan": True,
                "image": "fries.svg",
                "allergens": [],
            },
            {
                "name": "Onion Rings",
                "description": "Beer-battered onion rings, served crispy.",
                "price": 4.99,
                "category": "Side",
                "vegan": False,
                "image": "fries.svg",
                "allergens": ["gluten", "wheat", "egg"],
            },
            {
                "name": "Mac & Cheese",
                "description": "Creamy macaroni and cheese.",
                "price": 4.99,
                "category": "Side",
                "vegan": False,
                "image": "side.svg",
                "allergens": ["gluten", "wheat", "dairy"],
            },
            {
                "name": "Coleslaw",
                "description": "Fresh cabbage slaw with creamy dressing.",
                "price": 2.99,
                "category": "Side",
                "vegan": False,
                "image": "side.svg",
                "allergens": ["dairy", "egg"],
            },
            {
                "name": "Loaded Fries",
                "description": "Fries topped with cheese, bacon bits, and ranch.",
                "price": 6.99,
                "category": "Side",
                "vegan": False,
                "image": "fries.svg",
                "allergens": ["gluten", "dairy"],
            },
            # Drinks
            {
                "name": "Soft Drink (Can)",
                "description": "Coca-Cola, Sprite, Fanta, or Dr. Pepper.",
                "price": 1.99,
                "category": "Drink",
                "vegan": True,
                "image": "drink.svg",
                "allergens": [],
            },
            {
                "name": "Soft Drink (Large)",
                "description": "32oz fountain drink - choose your flavor.",
                "price": 2.99,
                "category": "Drink",
                "vegan": True,
                "image": "drink.svg",
                "allergens": [],
            },
            {
                "name": "Fresh Lemonade",
                "description": "Freshly squeezed lemonade, sweet and tart.",
                "price": 3.49,
                "category": "Drink",
                "vegan": True,
                "image": "drink.svg",
                "allergens": [],
            },
            {
                "name": "Iced Tea",
                "description": "Sweet or unsweetened iced tea.",
                "price": 2.49,
                "category": "Drink",
                "vegan": True,
                "image": "drink.svg",
                "allergens": [],
            },
            {
                "name": "Bottled Water",
                "description": "16oz bottled water.",
                "price": 1.49,
                "category": "Drink",
                "vegan": True,
                "image": "drink.svg",
                "allergens": [],
            },
            {
                "name": "Fresh Orange Juice",
                "description": "Freshly squeezed orange juice.",
                "price": 3.99,
                "category": "Drink",
                "vegan": True,
                "image": "drink.svg",
                "allergens": [],
            },
            {
                "name": "Milk Shake",
                "description": "Vanilla, chocolate, or strawberry milkshake.",
                "price": 4.99,
                "category": "Drink",
                "vegan": False,
                "image": "drink.svg",
                "allergens": ["dairy"],
            },
        ]

    def get_menu_items(self):
        """
        Returns a list of menu items with details.
        Loads from CSV if available, otherwise returns hardcoded items.
        """
        if not self.menu_items:
            self.load_menu_from_csv()
        
        # Convert to format expected by templates (without item_id for backward compatibility)
        result = []
        for item in self.menu_items:
            result.append({
                "name": item["name"],
                "description": item["description"],
                "price": item["price"],
                "category": item["category"],
                "vegan": item["vegan"],
                "image": item["image"],
                "allergens": item["allergens"],
                "item_id": item.get("item_id", ""),  # Include for management
            })
        return result

    def get_menu_allergens(self):
        """
        Build a mapping from item name -> list of allergens,
        based on the menu items above.
        """
        allergens_map = {}
        for item in self.get_menu_items():
            allergens_map[item["name"]] = item["allergens"]
        return allergens_map

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

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                has_status = "Status" in fieldnames
                
                for row in reader:
                    # Ensure Status field exists
                    if not has_status:
                        row["Status"] = "Pending"
                    
                    self.orders.append(
                        {
                            "order_id": str(row.get("Order_ID", "")),
                            "customer_name": row.get("Customer_Name", ""),
                            "customer_email": row.get("Customer_Email", ""),
                            "item": row.get("Item", ""),
                            "allergy_info": row.get("Allergy_Info", ""),
                            "is_safe": row.get("Is_Safe", "YES"),
                            "timestamp": row.get("Timestamp", ""),
                            "status": row.get("Status", "Pending"),
                        }
                    )
                
                # If Status column was missing, update the CSV file
                if not has_status and len(self.orders) > 0:
                    self._ensure_status_column(path)
                    
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Error loading orders from CSV: {e}", exc_info=True)
    
    def _ensure_status_column(self, path="data/orders.csv"):
        """Ensure Status column exists in orders CSV"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists or not readable or not writable:
                return
            
            rows = []
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                if "Status" not in fieldnames:
                    fieldnames.append("Status")
                for row in reader:
                    if "Status" not in row:
                        row["Status"] = "Pending"
                    rows.append(row)
            
            # Write back with Status column
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            logger.info(f"Added Status column to {path}")
        except Exception as e:
            logger.error(f"Error ensuring Status column: {e}")

    def add_order_to_csv(
        self,
        customer_name,
        customer_email,
        items_text,
        allergy_info,
        path="data/orders.csv",
    ):
        is_safe = self.is_order_safe_for_allergy(items_text, allergy_info)
        is_safe_str = "YES" if is_safe else "NO"

        order_id = len(self.orders) + 1
        timestamp = datetime.now().isoformat(timespec="seconds")

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
                    _sanitize_for_csv(items_text),
                    _sanitize_for_csv(allergy_info),
                    is_safe_str,
                    _sanitize_for_csv(timestamp),
                    "Pending",  # Default status for new orders
                ]
            )

        self.orders.append(
            {
                "order_id": order_id,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "item": items_text,
                "allergy_info": allergy_info,
                "is_safe": is_safe_str,
                "timestamp": timestamp,
                "status": "Pending",
            }
        )

        return is_safe

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
            "data/orders.csv": ["Order_ID", "Customer_Name", "Customer_Email", "Item", "Allergy_Info", "Is_Safe", "Timestamp", "Status"],
            "data/deals.csv": ["Deal_ID", "Title", "Description", "Discount", "Created_By", "Created_At", "Expires_At", "Is_Active"],
            "data/shifts.csv": ["Shift_ID", "Staff_Email", "Date", "Scheduled_Start", "Scheduled_End", "Check_In_Time", "Check_Out_Time", "Break_Start", "Break_End", "Total_Hours", "Status", "Notes", "Early_Checkout"],
            "data/menu.csv": ["Item_ID", "Name", "Description", "Price", "Category", "Vegan", "Image", "Allergens"],
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
    
    # ---------- DEALS MANAGEMENT ----------
    
    def load_deals_from_csv(self, path="data/deals.csv"):
        """Load deals from CSV file"""
        self.deals = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                return
            if not readable:
                logger.error(f"Deals CSV not readable: {path}")
                return

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.deals.append({
                        "deal_id": row.get("Deal_ID", ""),
                        "title": row.get("Title", ""),
                        "description": row.get("Description", ""),
                        "discount": row.get("Discount", ""),
                        "created_by": row.get("Created_By", ""),
                        "created_at": row.get("Created_At", ""),
                        "expires_at": row.get("Expires_At", ""),
                        "is_active": row.get("Is_Active", "YES").upper() == "YES",
                    })
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Error loading deals from CSV: {e}", exc_info=True)
    
    def add_deal_to_csv(self, title, description, discount, created_by, expires_at=None, path="data/deals.csv"):
        """Add a new deal to CSV"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists:
                # Initialize file if it doesn't exist
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Deal_ID", "Title", "Description", "Discount", "Created_By", "Created_At", "Expires_At", "Is_Active"])
            
            if not readable or not writable:
                logger.error(f"Cannot access deals CSV: {path}")
                return False
            
            # Generate deal ID
            deal_id = f"DEAL_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Read existing deals
            rows = []
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
            
            # Add new deal
            new_row = {
                "Deal_ID": deal_id,
                "Title": _sanitize_for_csv(title),
                "Description": _sanitize_for_csv(description),
                "Discount": _sanitize_for_csv(discount),
                "Created_By": _sanitize_for_csv(created_by),
                "Created_At": created_at,
                "Expires_At": _sanitize_for_csv(expires_at) if expires_at else "",
                "Is_Active": "YES",
            }
            rows.append(new_row)
            
            # Write back
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Reload deals
            self.load_deals_from_csv()
            logger.info(f"Deal added: {deal_id} by {created_by}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding deal to CSV: {e}", exc_info=True)
            return False
    
    def get_active_deals(self):
        """Get all active deals that haven't expired"""
        self.load_deals_from_csv()
        now = datetime.now()
        active_deals = []
        
        for deal in self.deals:
            if not deal.get("is_active", False):
                continue
            
            # Check expiration
            expires_at = deal.get("expires_at", "")
            if expires_at:
                try:
                    expire_date = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                    if expire_date < now:
                        continue
                except ValueError:
                    try:
                        expire_date = datetime.strptime(expires_at, "%Y-%m-%d")
                        if expire_date.date() < now.date():
                            continue
                    except ValueError:
                        pass
            
            active_deals.append(deal)
        
        # Sort by created_at (newest first)
        active_deals.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return active_deals
    
    # ---------- TIME CLOCK / SHIFT MANAGEMENT ----------
    
    def load_shifts_from_csv(self, path="data/shifts.csv"):
        """Load shift records from CSV"""
        self.shifts = []
        try:
            exists, readable, _ = self.check_file_permissions(path)
            if not exists:
                return
            if not readable:
                logger.error(f"Shifts CSV not readable: {path}")
                return

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.shifts.append({
                        "shift_id": row.get("Shift_ID", ""),
                        "staff_email": row.get("Staff_Email", ""),
                        "date": row.get("Date", ""),
                        "scheduled_start": row.get("Scheduled_Start", ""),
                        "scheduled_end": row.get("Scheduled_End", ""),
                        "check_in_time": row.get("Check_In_Time", ""),
                        "check_out_time": row.get("Check_Out_Time", ""),
                        "break_start": row.get("Break_Start", ""),
                        "break_end": row.get("Break_End", ""),
                        "total_hours": row.get("Total_Hours", "0"),
                        "status": row.get("Status", "scheduled"),  # scheduled, checked_in, on_break, completed
                        "notes": row.get("Notes", ""),
                        "early_checkout": row.get("Early_Checkout", "NO").upper() == "YES",
                    })
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Error loading shifts from CSV: {e}", exc_info=True)
    
    def create_shift(self, staff_email, date, scheduled_start, scheduled_end, path="data/shifts.csv"):
        """Create a new shift for a staff member"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Shift_ID", "Staff_Email", "Date", "Scheduled_Start", "Scheduled_End", "Check_In_Time", "Check_Out_Time", "Break_Start", "Break_End", "Total_Hours", "Status", "Notes", "Early_Checkout"])
            
            if not readable or not writable:
                logger.error(f"Cannot access shifts CSV: {path}")
                return False
            
            # Generate shift ID
            shift_id = f"SHIFT_{datetime.now().strftime('%Y%m%d%H%M%S')}_{staff_email[:5]}"
            
            # Read existing shifts
            rows = []
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
            
            # Add new shift
            new_row = {
                "Shift_ID": shift_id,
                "Staff_Email": _sanitize_for_csv(staff_email),
                "Date": _sanitize_for_csv(date),
                "Scheduled_Start": _sanitize_for_csv(scheduled_start),
                "Scheduled_End": _sanitize_for_csv(scheduled_end),
                "Check_In_Time": "",
                "Check_Out_Time": "",
                "Break_Start": "",
                "Break_End": "",
                "Total_Hours": "0",
                "Status": "scheduled",
                "Notes": "",
                "Early_Checkout": "NO",
            }
            rows.append(new_row)
            
            # Write back
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Reload shifts
            self.load_shifts_from_csv()
            logger.info(f"Shift created: {shift_id} for {staff_email}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating shift: {e}", exc_info=True)
            return False
    
    def update_shift_status(self, shift_id, status, check_in_time=None, check_out_time=None, break_start=None, break_end=None, notes=None, early_checkout=False, path="data/shifts.csv"):
        """Update shift status (check in, check out, break, etc.)"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists or not readable or not writable:
                logger.error(f"Cannot access shifts CSV: {path}")
                return False
            
            rows = []
            shift_found = False
            
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                for row in reader:
                    if row.get("Shift_ID", "") == shift_id:
                        shift_found = True
                        row["Status"] = status
                        if check_in_time:
                            row["Check_In_Time"] = check_in_time
                        if check_out_time:
                            row["Check_Out_Time"] = check_out_time
                        if break_start:
                            row["Break_Start"] = break_start
                        if break_end:
                            row["Break_End"] = break_end
                        if notes is not None:
                            row["Notes"] = _sanitize_for_csv(notes)
                        if early_checkout:
                            row["Early_Checkout"] = "YES"
                        
                        # Calculate total hours if we have check in and check out
                        if row.get("Check_In_Time") and row.get("Check_Out_Time"):
                            try:
                                check_in = datetime.strptime(row["Check_In_Time"], "%Y-%m-%d %H:%M:%S")
                                check_out = datetime.strptime(row["Check_Out_Time"], "%Y-%m-%d %H:%M:%S")
                                
                                # Subtract break time if exists
                                break_duration = timedelta(0)
                                if row.get("Break_Start") and row.get("Break_End"):
                                    try:
                                        break_start_dt = datetime.strptime(row["Break_Start"], "%Y-%m-%d %H:%M:%S")
                                        break_end_dt = datetime.strptime(row["Break_End"], "%Y-%m-%d %H:%M:%S")
                                        break_duration = break_end_dt - break_start_dt
                                    except ValueError:
                                        pass
                                
                                total_time = check_out - check_in - break_duration
                                total_hours = total_time.total_seconds() / 3600
                                row["Total_Hours"] = f"{total_hours:.2f}"
                            except ValueError:
                                pass
                    
                    rows.append(row)
            
            if not shift_found:
                logger.warning(f"Shift not found: {shift_id}")
                return False
            
            # Write back
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Reload shifts
            self.load_shifts_from_csv()
            logger.info(f"Shift updated: {shift_id} - Status: {status}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating shift: {e}", exc_info=True)
            return False
    
    def get_staff_shifts(self, staff_email, date_filter=None):
        """Get all shifts for a staff member, optionally filtered by date"""
        self.load_shifts_from_csv()
        shifts = [s for s in self.shifts if s.get("staff_email", "").lower() == staff_email.lower()]
        
        if date_filter:
            shifts = [s for s in shifts if s.get("date", "") == date_filter]
        
        # Sort by date and scheduled start time
        shifts.sort(key=lambda x: (x.get("date", ""), x.get("scheduled_start", "")))
        return shifts
    
    # ---------- MENU MANAGEMENT ----------
    
    def add_menu_item(self, name, description, price, category, vegan, image, allergens, path="data/menu.csv"):
        """Add a new menu item"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Item_ID", "Name", "Description", "Price", "Category", "Vegan", "Image", "Allergens"])
            
            if not readable or not writable:
                logger.error(f"Cannot access menu CSV: {path}")
                return False
            
            # Generate item ID
            self.load_menu_from_csv()
            existing_ids = [item.get("item_id", "") for item in self.menu_items]
            item_id = f"MENU_{len(existing_ids) + 1:03d}"
            
            # Read existing items
            rows = []
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
            
            # Add new item
            new_row = {
                "Item_ID": item_id,
                "Name": _sanitize_for_csv(name),
                "Description": _sanitize_for_csv(description),
                "Price": str(float(price)),
                "Category": category,
                "Vegan": "TRUE" if vegan else "FALSE",
                "Image": image,
                "Allergens": ",".join([a.strip() for a in allergens if a.strip()]) if isinstance(allergens, list) else _sanitize_for_csv(allergens),
            }
            rows.append(new_row)
            
            # Write back
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Reload menu
            self.load_menu_from_csv()
            logger.info(f"Menu item added: {item_id} - {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding menu item: {e}", exc_info=True)
            return False
    
    def update_menu_item(self, item_id, name, description, price, category, vegan, image, allergens, path="data/menu.csv"):
        """Update an existing menu item"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists or not readable or not writable:
                logger.error(f"Cannot access menu CSV: {path}")
                return False
            
            rows = []
            item_found = False
            
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                for row in reader:
                    if row.get("Item_ID", "") == item_id:
                        item_found = True
                        row["Name"] = _sanitize_for_csv(name)
                        row["Description"] = _sanitize_for_csv(description)
                        row["Price"] = str(float(price))
                        row["Category"] = category
                        row["Vegan"] = "TRUE" if vegan else "FALSE"
                        row["Image"] = image
                        row["Allergens"] = ",".join([a.strip() for a in allergens if a.strip()]) if isinstance(allergens, list) else _sanitize_for_csv(allergens)
                    rows.append(row)
            
            if not item_found:
                logger.warning(f"Menu item not found: {item_id}")
                return False
            
            # Write back
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Reload menu
            self.load_menu_from_csv()
            logger.info(f"Menu item updated: {item_id} - {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating menu item: {e}", exc_info=True)
            return False
    
    def delete_menu_item(self, item_id, path="data/menu.csv"):
        """Delete a menu item"""
        try:
            exists, readable, writable = self.check_file_permissions(path)
            if not exists or not readable or not writable:
                logger.error(f"Cannot access menu CSV: {path}")
                return False
            
            rows = []
            item_found = False
            
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                for row in reader:
                    if row.get("Item_ID", "") != item_id:
                        rows.append(row)
                    else:
                        item_found = True
            
            if not item_found:
                logger.warning(f"Menu item not found: {item_id}")
                return False
            
            # Write back
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Reload menu
            self.load_menu_from_csv()
            logger.info(f"Menu item deleted: {item_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting menu item: {e}", exc_info=True)
            return False
    
    def get_menu_item_by_id(self, item_id):
        """Get a specific menu item by ID"""
        self.load_menu_from_csv()
        for item in self.menu_items:
            if item.get("item_id") == item_id:
                return item
        return None
