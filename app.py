import csv
import io
import os
import re
from datetime import date, datetime
from functools import wraps

import dns.resolver
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email):
    if not EMAIL_RE.match(email):
        return False
    domain = email.rsplit("@", 1)[-1]
    try:
        return len(dns.resolver.resolve(domain, "MX")) > 0
    except Exception:
        return False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'crm.db')}"
app.config["SESSION_COOKIE_NAME"] = "crm_session"
db = SQLAlchemy(app)


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    organization = db.Column(db.String(120))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="lead")  # lead / active / inactive
    follow_up_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contact.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("company_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def get_own_contact(contact_id):
    return db.session.execute(
        db.select(Contact).filter_by(id=contact_id, company_id=session["company_id"])
    ).scalar_one_or_none()


def parse_follow_up_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@app.route("/")
def home():
    if session.get("company_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        exists = db.session.execute(
            db.select(Company).filter_by(email=email)
        ).scalar_one_or_none()
        if not company_name or not email or not password:
            error = "All fields are required."
        elif not is_valid_email(email):
            error = "Please enter a valid, real email address."
        elif exists:
            error = "An account with that email already exists."
        else:
            company = Company(
                company_name=company_name,
                email=email,
                password_hash=generate_password_hash(password),
            )
            db.session.add(company)
            db.session.commit()
            session["company_id"] = company.id
            session["company_name"] = company.company_name
            return redirect(url_for("dashboard"))
    return render_template("signup.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        company = db.session.execute(
            db.select(Company).filter_by(email=email)
        ).scalar_one_or_none()
        if company and check_password_hash(company.password_hash, password):
            session["company_id"] = company.id
            session["company_name"] = company.company_name
            return redirect(url_for("dashboard"))
        error = "Invalid email or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("company_id", None)
    session.pop("company_name", None)
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    company_id = session["company_id"]
    total = db.session.execute(
        db.select(db.func.count()).select_from(Contact).filter_by(company_id=company_id)
    ).scalar()
    by_status = db.session.execute(
        db.select(Contact.status, db.func.count())
        .filter_by(company_id=company_id)
        .group_by(Contact.status)
    ).all()
    recent = db.session.execute(
        db.select(Contact).filter_by(company_id=company_id)
        .order_by(Contact.created_at.desc()).limit(5)
    ).scalars().all()
    today = date.today()
    followups = db.session.execute(
        db.select(Contact).filter_by(company_id=company_id)
        .filter(Contact.follow_up_date.isnot(None))
        .filter(Contact.follow_up_date <= today)
        .order_by(Contact.follow_up_date.asc())
        .limit(10)
    ).scalars().all()
    return render_template(
        "dashboard.html", total=total, by_status=dict(by_status), recent=recent,
        followups=followups, today=today,
    )


@app.route("/contacts")
@login_required
def contacts_list():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    query = db.select(Contact).filter_by(company_id=session["company_id"])
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Contact.name.ilike(like), Contact.email.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    contacts = db.session.execute(query.order_by(Contact.created_at.desc())).scalars().all()
    return render_template("contacts_list.html", contacts=contacts, q=q, status=status, now=date.today())


@app.route("/contacts/add", methods=["GET", "POST"])
@login_required
def contact_add():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            error = "Name is required."
        else:
            db.session.add(Contact(
                company_id=session["company_id"],
                name=name,
                email=request.form.get("email", "").strip(),
                phone=request.form.get("phone", "").strip(),
                organization=request.form.get("organization", "").strip(),
                notes=request.form.get("notes", "").strip(),
                status=request.form.get("status", "lead"),
                follow_up_date=parse_follow_up_date(request.form.get("follow_up_date")),
            ))
            db.session.commit()
            flash("Contact added.")
            return redirect(url_for("contacts_list"))
    return render_template("contact_form.html", contact=None, error=error)


@app.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def contact_edit(contact_id):
    contact = get_own_contact(contact_id)
    if contact is None:
        return "Not found", 404
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            error = "Name is required."
        else:
            contact.name = name
            contact.email = request.form.get("email", "").strip()
            contact.phone = request.form.get("phone", "").strip()
            contact.organization = request.form.get("organization", "").strip()
            contact.notes = request.form.get("notes", "").strip()
            contact.status = request.form.get("status", "lead")
            contact.follow_up_date = parse_follow_up_date(request.form.get("follow_up_date"))
            db.session.commit()
            flash("Contact updated.")
            return redirect(url_for("contacts_list"))
    activities = db.session.execute(
        db.select(Activity).filter_by(contact_id=contact.id).order_by(Activity.created_at.desc())
    ).scalars().all()
    return render_template("contact_form.html", contact=contact, error=error, activities=activities)


@app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def contact_delete(contact_id):
    contact = get_own_contact(contact_id)
    if contact is None:
        return "Not found", 404
    db.session.delete(contact)
    db.session.commit()
    flash("Contact deleted.")
    return redirect(url_for("contacts_list"))


@app.route("/contacts/<int:contact_id>/activity/add", methods=["POST"])
@login_required
def activity_add(contact_id):
    contact = get_own_contact(contact_id)
    if contact is None:
        return "Not found", 404
    text = request.form.get("text", "").strip()
    if not text:
        flash("Activity text is required.")
    else:
        db.session.add(Activity(contact_id=contact.id, text=text))
        db.session.commit()
        flash("Activity logged.")
    return redirect(url_for("contact_edit", contact_id=contact.id))


@app.route("/contacts/export")
@login_required
def contacts_export():
    contacts = db.session.execute(
        db.select(Contact).filter_by(company_id=session["company_id"])
        .order_by(Contact.created_at.desc())
    ).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "email", "phone", "organization", "status", "follow_up_date", "notes"])
    for c in contacts:
        writer.writerow([
            c.name, c.email, c.phone, c.organization, c.status,
            c.follow_up_date.isoformat() if c.follow_up_date else "", c.notes,
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


@app.route("/contacts/import", methods=["POST"])
@login_required
def contacts_import():
    file = request.files.get("csv_file")
    if not file or file.filename == "":
        flash("No file selected.")
        return redirect(url_for("contacts_list"))
    stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(stream)
    success, failed = 0, 0
    for row in reader:
        name = (row.get("name") or "").strip()
        if not name:
            failed += 1
            continue
        db.session.add(Contact(
            company_id=session["company_id"],
            name=name,
            email=(row.get("email") or "").strip(),
            phone=(row.get("phone") or "").strip(),
            organization=(row.get("organization") or "").strip(),
            notes=(row.get("notes") or "").strip(),
            status=(row.get("status") or "lead").strip() or "lead",
            follow_up_date=parse_follow_up_date(row.get("follow_up_date")),
        ))
        success += 1
    db.session.commit()
    flash(f"Imported {success} contact(s), skipped {failed} invalid row(s).")
    return redirect(url_for("contacts_list"))


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5003)
