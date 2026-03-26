"""
Test script to generate HTML preview of the professional documentation template.
Bypasses WeasyPrint (which needs GTK on Windows) and outputs raw HTML for browser preview.
Run: python test_html_preview.py
Output: test_output/preview.html (open in browser)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jinja2 import Environment, FileSystemLoader
from datetime import datetime

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# --- Dummy Video ---
class MockVideo:
    def __init__(self):
        self.title = "How to Set Up Your Online Store"

# --- Dummy Steps ---
dummy_steps_raw = [
    {
        "step_number": 1,
        "timestamp": 0.0,
        "title": "Getting Started",
        "action": 'Navigate to the <strong>Admin Dashboard</strong> by clicking the <strong>Dashboard</strong> link in the left sidebar.',
        "explanation": "The Admin Dashboard is your central hub for managing all aspects of your online store, including products, orders, and settings.",
        "tip": "You can bookmark the dashboard URL for quick access in the future.",
        "url": "https://admin.mystore.com/dashboard",
        "note": "You must be logged in with an admin account to access the dashboard.",
        "section_summary": "Before you begin setting up your store, you need to access the admin panel. This section will guide you through logging in and navigating to the main dashboard.",
    },
    {
        "step_number": 2,
        "timestamp": 5.0,
        "title": "Getting Started",
        "action": 'Click the <strong>Settings</strong> gear icon located in the bottom-left corner of the sidebar.',
        "explanation": "The Settings page contains all store-level configurations including business details, payment providers, and shipping options.",
        "tip": None,
        "url": None,
        "note": None,
        "section_summary": None,
    },
    {
        "step_number": 3,
        "timestamp": 12.0,
        "title": "Configuring Store Details",
        "action": 'Enter your <strong>Store Name</strong> in the text field at the top of the General Settings page.',
        "explanation": "Your store name appears in the browser tab, email notifications, and customer-facing pages. Choose a name that reflects your brand identity.",
        "tip": None,
        "url": None,
        "note": "Changing the store name will not affect your domain URL. To change your domain, visit the Domains section.",
        "section_summary": "In this section, you will configure the fundamental details of your online store, including the store name, contact information, and business address.",
    },
    {
        "step_number": 4,
        "timestamp": 20.0,
        "title": "Configuring Store Details",
        "action": 'Fill in the <strong>Contact Email</strong> field with your business email address.',
        "explanation": "This email address will be used for order notifications, customer inquiries, and account recovery. Make sure it is a monitored inbox.",
        "tip": "Use a dedicated business email (e.g., support@yourstore.com) rather than a personal email for professionalism.",
        "url": None,
        "note": None,
        "section_summary": None,
    },
    {
        "step_number": 5,
        "timestamp": 30.0,
        "title": "Configuring Store Details",
        "action": 'Scroll down to the <strong>Address</strong> section and enter your complete business address.',
        "explanation": "Your business address is required for tax calculations, shipping rate estimates, and legal compliance with e-commerce regulations.",
        "tip": None,
        "url": None,
        "note": "If you operate from multiple locations, you can add additional addresses in the Locations section later.",
        "section_summary": None,
    },
    {
        "step_number": 6,
        "timestamp": 40.0,
        "title": "Setting Up Payments",
        "action": 'Click the <strong>Payments</strong> tab in the left Settings sidebar to open the payment configuration page.',
        "explanation": "Payment configuration determines how your customers can pay for their purchases. Setting this up correctly is critical for receiving payments.",
        "tip": None,
        "url": "https://admin.mystore.com/settings/payments",
        "note": "You will need your bank account details and a valid government-issued ID to complete the payment provider setup.",
        "section_summary": "Payment configuration is a critical step in launching your store. This section walks you through connecting a payment provider so you can start accepting credit cards, debit cards, and other payment methods.",
    },
    {
        "step_number": 7,
        "timestamp": 50.0,
        "title": "Setting Up Payments",
        "action": 'Click the <strong>Activate</strong> button next to the recommended payment provider (e.g., Stripe or PayPal).',
        "explanation": "Activating a payment provider creates the secure connection between your store and the payment processor, enabling real-time transaction handling.",
        "tip": "Stripe is recommended for most stores as it supports the widest range of payment methods and currencies.",
        "url": None,
        "note": None,
        "section_summary": None,
    },
]

# --- Build sections (same logic as pdf_service.py) ---
sections = []
current_section = None

for step in dummy_steps_raw:
    step_title = step.get("title", "General Steps")
    
    step_dict = {
        "step_number": step["step_number"],
        "timestamp": step["timestamp"],
        "action": step["action"],
        "tip": step.get("tip"),
        "url": step.get("url"),
        "explanation": step.get("explanation"),
        "note": step.get("note"),
    }
    
    if current_section is None or current_section["heading"] != step_title:
        current_section = {
            "heading": step_title,
            "summary": step.get("section_summary"),
            "steps": []
        }
        sections.append(current_section)
    
    current_section["steps"].append(step_dict)

# --- Build context ---
section_names = [s["heading"] for s in sections]
total_steps = sum(len(s["steps"]) for s in sections)

context = {
    "data": {
        "title": "How to Set Up Your Online Store",
        "summary": f"This guide walks you through {len(section_names)} key sections: {', '.join(section_names[:-1])}, and {section_names[-1]}. Follow each section in order for the best results.",
        "generated_date": datetime.now().strftime("%B %d, %Y"),
        "total_sections": len(sections),
        "total_steps": total_steps,
        "sections": sections,
    },
}

# --- Render HTML ---
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
template = env.get_template("report.html")
html_content = template.render(context)

# --- Inject CSS inline (for standalone preview) ---
css_path = os.path.join(TEMPLATE_DIR, "style.css")
with open(css_path, "r", encoding="utf-8") as f:
    css_content = f.read()

# Insert CSS into <head>
html_content = html_content.replace("</head>", f"<style>\n{css_content}\n</style>\n</head>")

# --- Save ---
output_dir = os.path.join(BASE_DIR, "test_output")
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "preview.html")

with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"✅ HTML preview generated: {os.path.abspath(output_path)}")
print(f"📂 Open in browser to see the result!")
