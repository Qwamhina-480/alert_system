from flask import Flask, render_template, request, redirect, url_for, flash
import json, os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "supersecretkey"

DB_FILE = "schedules.json"



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


def sort_schedules(schedules):
    """Sort schedules by status & datetime: Now → Upcoming → Later → Past."""
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


def get_status(class_time, duration):
    #Return Now, Upcoming, or Later based on current time.
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



@app.route("/", methods=["GET", "POST"])
def index():
    schedules = load_schedules()
    schedules = sort_schedules(schedules)

    for s in schedules:
        s["status"] = get_status(s["datetime"], s.get("duration"))

    
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
    flash("Schedule deleted successfully!", "success")
    return redirect(url_for("index"))




if __name__ == "__main__":
    app.run(debug=True)
