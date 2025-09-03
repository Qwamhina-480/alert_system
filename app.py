from flask import Flask, render_template, request, redirect, url_for, flash
import json, os, atexit
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Mail, Message
from dotenv import load_dotenv


app = Flask(__name__)
app.secret_key = "supersecretkey"

DB_FILE = "schedules.json"


load_dotenv()


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
    with open(DB_FILE, "w") as f:
        json.dump(schedules, f, indent=4)


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

            msg = Message(subject=subject, sender=("Class Reminder App", app.config["MAIL_USERNAME"]), recipients=[MAIL_RECIPIENT], body=body_html)
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
@app.route("/", methods=["GET", "POST"])
def index():
    schedules = load_schedules()
    schedules = sort_schedules(schedules)

    for s in schedules:
        s["status"] = get_status(s.get("datetime", ""), s.get("duration", 0))

    today = datetime.now().date()
    today_schedules = [
        s for s in schedules
        if datetime.strptime(s["datetime"], "%Y-%m-%d %H:%M").date() == today
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
                }
            )
            flash("New schedule added!", "success")

        save_schedules(schedules)
        return redirect(url_for("index"))

    return render_template("index.html", schedules=schedules, edit_item=edit_item, today_schedules=today_schedules)


@app.route("/delete_schedule/<int:schedule_id>")
def delete_schedule(schedule_id):
    schedules = load_schedules()
    schedules = [s for s in schedules if s["id"] != schedule_id]
    save_schedules(schedules)
    flash("Schedule deleted successfully!", "info")
    return redirect(url_for("index"))

@app.route("/landing")
def landing_page():
    return render_template("landing.html")

@app.route("/signup")
def signup():
    return render_template("landing.html")

@app.route("/login")
def login():
    return render_template("landing.html")

# ---------------- Scheduler ---------------- #
scheduler = BackgroundScheduler()
scheduler.add_job(check_and_send_reminders, "interval", seconds=30, id="reminder_job", max_instances=1)
atexit.register(lambda: scheduler.shutdown(wait=False))


if __name__ == "__main__":
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        scheduler.start()
        app.logger.info("Scheduler started with Flask-Mail.")
    app.run(debug=True)
