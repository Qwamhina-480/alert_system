from flask import Flask, render_template, request, redirect, url_for, flash, session
import json, os, atexit
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Mail, Message
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash


load_dotenv()


DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE   = os.path.join(DATA_DIR, "schedules.json")
USER_FILE = os.path.join(DATA_DIR, "users.json")
for path in (DB_FILE, USER_FILE):
    if not os.path.exists(path):
        with open(path, "w") as fh:
            json.dump([], fh)

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY")

DB_FILE = "schedules.json"

USER_FILE = "users.json"




app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True") == "True"
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER")

mail = Mail(app)

# Reminder config
REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES", "15"))
MAIL_RECIPIENT = os.getenv("MAIL_RECIPIENT", app.config["MAIL_DEFAULT_SENDER"])


# ---------------- Helpers ---------------- #
def load_schedules():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_schedules(schedules):
    # Ensure schedules is a list of dictionaries
    if not isinstance(schedules, list):
        schedules = [schedules]

    # Find current maximum ID
    existing_ids = [s.get("id", 0) for s in schedules if isinstance(s, dict)]
    max_id = max(existing_ids, default=0)

    for schedule in schedules:
        if isinstance(schedule, dict) and "id" not in schedule:
            max_id += 1
            schedule["id"] = max_id
        elif not isinstance(schedule, dict):
            print(f"Invalid schedule format: {schedule}")  # Debug

    with open("schedules.json", "w") as file:
        json.dump(schedules, file, indent=4)

def save_users(data):
    with open(USER_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_users():
    if not os.path.exists(USER_FILE):
        return []
    try:
        with open(USER_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []


def get_user_email(user_id):
    users = load_users()
    for u in users:
        if u["id"] == user_id:
            return u["email"]
    return None

def get_user_by_id(user_id):
    users = load_users()
    return next((u for u in users if u["id"] == user_id), None)



def get_status(class_time, duration):
    now = datetime.now()
    try:
        start = datetime.strptime(class_time, "%Y-%m-%d %H:%M")
    except Exception:
        return "Invalid Date"

    try:
        duration = int(duration) if duration else 0
    except ValueError:
        duration = 0

    end = start + timedelta(minutes=duration)

    if start <= now <= end:
        return "Now"
    elif now < start and start.date() == now.date():
        return "Upcoming"
    elif now < start:
        return "Later"
    else:
        return "Past"


def sort_schedules(schedules):
    def status_rank(status):
        order = {"Now": 0, "Upcoming": 1, "Later": 2, "Past": 3}
        return order.get(status, 4)

    def parse_datetime(s):
        try:
            return datetime.strptime(s.get("datetime", ""), "%Y-%m-%d %H:%M")
        except Exception:
            return datetime.max

    for s in schedules:
        s["status"] = get_status(s.get("datetime"), s.get("duration"))
    schedules.sort(key=lambda x: (status_rank(x["status"]), parse_datetime(x)))
    return schedules



def send_email_reminder(schedule):
    try:
        with app.app_context():
            subject = f"Reminder: {schedule.get('title')} at {schedule.get('time')}"
            
            body_html = f"""
            <h3 style="font-size:18px; color:#2c3e50;">📌 Upcoming Class Reminder</h3>
            <p><span style="font-weight:bold; font-size:18px;">Title: </span> {schedule.get('title')}</p>
            <p><span style="font-weight:bold; font-size:18px;">Time: </span> {schedule.get('time')}</p>
            <p><span style="font-weight:bold; font-size:18px;">Venue: </span> {schedule.get('location', '—')}</p>
            <p><span style="font-weight:bold; font-size:18px;">Duration: </span> {schedule.get('duration', '—')} minutes</p>
            <p><span style="font-weight:bold; font-size:18px;">Notes: </span><br>{schedule.get('notes', '')}</p>
            <hr>
            <small style="color:gray;">This is an automated reminder.</small>
            """

            MAIL_RECIPIENT = schedule.get("user_email")
            if not MAIL_RECIPIENT:
                print("No email found for user:", schedule.get("user_id"))
                return False

            msg = Message(subject=subject, sender=("Class Reminder", app.config["MAIL_USERNAME"]), recipients=[MAIL_RECIPIENT], body=body_html)
            msg.html = body_html   # send HTML formatted email


            mail.send(msg)

            print(f"Reminder sent for schedule id={schedule.get('id')}")
            return True
    except Exception as e:
        print("Failed to send reminder email: %s", e)
        return False


def check_and_send_reminders():
    try:
        schedules = load_schedules()
        now = datetime.now()
        changed = False
        reminder_window_seconds = REMINDER_MINUTES * 60

        for s in schedules:
            dt_str = s.get("datetime")
            if not dt_str:
                continue
            try:
                start = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            except Exception:
                continue

            seconds_until_start = (start - now).total_seconds()

            # Send reminder only once
            if 0 < seconds_until_start <= reminder_window_seconds and not s.get("reminder_sent", False):
                sent = send_email_reminder(s)
                if sent:
                    s["reminder_sent"] = True  
                    changed = True

        if changed:
            save_schedules(schedules)
    except Exception as e:
        print("Error in reminder job: %s", e)
# ---------------- Routes ---------------- #
@app.route("/dashboard", methods=["GET", "POST"])
def index():
    if "user_id" not in session:
        flash("Please log in to access the dashboard.", "info")
        return redirect(url_for("landing_page"))
    
    schedules = load_schedules()
    schedules = sort_schedules(schedules)
    

    for s in schedules:
        s["status"] = get_status(s.get("datetime", ""), s.get("duration", 0))

    """#  Filtering
    filter_status = request.args.get("filter", "all")
    search_query = request.args.get("search", "").lower()

    if filter_status != "all":
        user_schedules = [s for s in user_schedules if s["status"] == filter_status]

    if search_query:
        user_schedules = [
            s for s in user_schedules 
            if search_query in s.get("title", "").lower()
            or search_query in s.get("location", "").lower()
            or search_query in s.get("notes", "").lower()
        ]
"""
    
    today = datetime.now().date()
    today_schedules = [
        s for s in schedules
        if datetime.strptime(s["datetime"], "%Y-%m-%d %H:%M").date() == today and s.get("user_id") == session["user_id"]
    ]

    edit_id = request.args.get("edit_id", type=int) or request.form.get("edit_id", type=int)
    edit_item = next((c for c in schedules if c["id"] == edit_id), None)

    if request.method == "POST":
        form = request.form
        dt = f"{form['date']} {form['time']}"

        if edit_id and edit_item:
            edit_item.update(
                title=form["title"],
                date=form["date"],
                time=form["time"],
                datetime=dt,
                location=form.get("location"),
                duration=form.get("duration"),
                notes=form.get("notes"),
                reminder_sent=False,  
            )
            flash("Schedule updated!", "success")
        else:
            new_id = max([c["id"] for c in schedules], default=0) + 1
            user = get_user_by_id(session["user_id"])
            if not user:
                flash("User not found. Please log in again.", "info")
                return redirect(url_for("landing_page"))

            schedules.append(
                {
                    "id": new_id,
                    "title": form["title"],
                    "date": form["date"],
                    "time": form["time"],
                    "datetime": dt,
                    "location": form.get("location"),
                    "duration": form.get("duration"),
                    "notes": form.get("notes"),
                    "reminder_sent": False,
                    "user_id": user["id"],
                    "user_email": user["email"]   
                }
            )

        save_schedules(schedules)
        return redirect(url_for("index"))
    schedules = load_schedules()
    user_schedules = [s for s in schedules if s.get("user_id") == session["user_id"]]
    return render_template("index.html", schedules=user_schedules, edit_item=edit_item, today_schedules=today_schedules, datetime=datetime)


@app.route("/delete_schedule/<int:schedule_id>")
def delete_schedule(schedule_id):
    schedules = load_schedules()
    schedules = [s for s in schedules if not (s["id"] == schedule_id and s["user_id"] == session["user_id"])]
    save_schedules(schedules)
    flash("Schedule deleted successfully!", "info")
    return redirect(url_for("index"))

@app.route("/")
def landing_page():
    return render_template("landing.html")

@app.route("/signup", methods=["POST"])
def signup():
    data = request.form
    username = data.get("username")
    email = data.get("email")
    password = generate_password_hash(data.get("password"))

    users = load_users()    
    if any(u["email"] == email for u in users): 
        flash("Email already registered!", "info")
        return redirect(url_for("landing_page"))
    
    new_user = {
        "id":  max([u["id"] for u in users], default=0) + 1,
        "username": username,
        "email": email,
        "password": password
    }
    users.append(new_user)
    save_users(users)
    flash("Signup successful, please log in!", "success")

    msg = Message(
    subject="Welcome to StuCh, your best Reminder App!",
    sender=("Class Reminder"),
    recipients=[email],
    body=f"Hello {username},\n\nThanks for signing up. You can now start adding schedules."
)
    try:
        mail.send(msg)
    except Exception as e:
        app.logger.error(f"Failed to send welcome email: {e}")


    return redirect(url_for("landing_page"))


@app.route("/login", methods=["POST"])
def login():
    if request.method == "POST":
        data = request.form
        email = data.get("email")
        password = data.get("password")

        users = load_users()
        user = next((u for u in users if u["email"] == email), None)
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Login successful", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid email or password", "info")
    return render_template("landing.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("landing_page"))       

# ---------------- Scheduler ---------------- #
scheduler = BackgroundScheduler()
scheduler.add_job(check_and_send_reminders, "interval", seconds=30, id="reminder_job", max_instances=1)
atexit.register(lambda: scheduler.shutdown(wait=False))


if __name__ == "__main__":
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        scheduler.start()
        app.logger.info("Scheduler started with Flask-Mail.")
    app.run(debug=True)
