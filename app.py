from flask import Flask, render_template, request, redirect, url_for
from foodtruck import FoodTruck

app = Flask(__name__)

# Create and load backend
my_truck = FoodTruck("CS120 Food Truck", "GSU Campus")
my_truck.load_staff_from_csv()
my_truck.load_schedules_from_csv()


@app.route("/")
def home():
    return render_template(
        "home.html",
        truck=my_truck,
        staff_count=len(my_truck.staff),
        schedule_count=len(my_truck.schedules),
    )


@app.route("/staff")
def staff_page():
    my_truck.load_staff_from_csv()
    return render_template("staff.html", staff=my_truck.staff)


@app.route("/add_staff", methods=["GET"])
def add_staff_form():
    return render_template("add_staff.html")


@app.route("/add_staff", methods=["POST"])
def add_staff_submit():
    # Get form data
    email = request.form["email"]
    password = request.form["password"]
    first = request.form["first"]
    last = request.form["last"]
    phone = request.form["phone"]
    address = request.form["address"]
    dob = request.form["dob"]
    sex = request.form["sex"]

    # Save to CSV and reload
    my_truck.add_staff_to_csv(email, password, first, last, phone, address, dob, sex)
    my_truck.load_staff_from_csv()

    return redirect("/staff")


@app.route("/schedules")
def schedules_page():
    my_truck.load_schedules_from_csv()
    return render_template("schedules.html", schedules=my_truck.schedules)


@app.route("/book_schedule", methods=["GET"])
def book_schedule_form():
    # need staff list to show in dropdown
    my_truck.load_staff_from_csv()
    return render_template("book_schedule.html", staff=my_truck.staff)


@app.route("/book_schedule", methods=["POST"])
def book_schedule_submit():
    manager = request.form["manager"]
    date = request.form["date"]
    time = request.form["time"]
    staff_email = request.form["staff_email"]
    work_time = request.form["work_time"]

    # find staff name from email
    my_truck.load_staff_from_csv()
    staff_name = None
    for s in my_truck.staff:
        if s["email"] == staff_email:
            staff_name = f"{s['first']} {s['last']}"
            break

    if staff_name is None:
        return "Staff not found. <a href='/book_schedule'>Back</a>"

    # load schedules and try to book (this checks conflicts)
    my_truck.load_schedules_from_csv()
    success = my_truck.book_schedule(
        manager=manager,
        date=date,
        time=time,
        staff_email=staff_email,
        staff_name=staff_name,
        work_time=work_time,
    )

    if not success:
        return (
            "That staff member is already booked at that date/time. "
            "<a href='/book_schedule'>Back</a>"
        )

    return redirect("/schedules")


if __name__ == "__main__":
    app.run(debug=True)
