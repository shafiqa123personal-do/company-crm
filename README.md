# Company CRM (Flask)

A simple CRM (customer relationship manager) for small companies.
Each company signs up for its own account and sees **only its own contacts**.

## Features

- **Company accounts:** sign up, log in and log out, with hashed passwords
- **Contacts:** add, edit and delete contacts (name, email, phone, organisation, notes)
- **Status:** mark each contact as *lead*, *active* or *inactive*
- **Follow-ups:** set a follow-up date. The dashboard shows which follow-ups are due
- **Activity notes:** keep a timeline of calls, emails and meetings for each contact
- **Search and filter:** find contacts by name or email, or filter them by status
- **CSV import and export:** bring contacts in from a spreadsheet or download them all
- **Email check:** checks that an email address's domain can really receive mail

## Built with

Python · Flask · Flask-SQLAlchemy · SQLite · HTML/CSS

## Run it on your computer

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5003, sign up as a company, and start adding contacts.
